"""scrcpy 低延迟视频流采集源(自包含实现,ffmpeg CLI 解码)。

原理:手机端硬件编码 H264 连续视频流,电脑端硬解码,延迟最低(架构文档推荐方案)。
不依赖已停更的 PyPI scrcpy-client(其钉死旧版 adbutils 与本项目冲突)。流程:
  1. adb push 官方 scrcpy-server 到设备;
  2. app_process 起服务,raw_stream 模式输出纯 H264 裸流;
  3. adb forward 打隧道,socket 取流;
  4. 喂给 ffmpeg 子进程解码成 rawvideo(bgr24)。

为什么用 ffmpeg CLI 而非 PyAV:cv2 与 PyAV 各自打包了不同版本的 libavcodec,
同进程会发生 C 符号冲突导致 PyAV 静默解码失败。ffmpeg 独立进程彻底规避该问题。

后台线程持续解码到 _latest,grab() 取最近一帧。采集(视频)与 MaaTouch 执行(触控)
是两条独立通道,互不影响。
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
from loguru import logger

from crplayer.capture.base import CaptureSource, Frame

_DEFAULT_SERVER_CANDIDATES = [
    os.environ.get("SCRCPY_SERVER_PATH", ""),
    "/opt/homebrew/share/scrcpy/scrcpy-server",
    "/usr/local/share/scrcpy/scrcpy-server",
    "/usr/share/scrcpy/scrcpy-server",
]
_DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
_SIZE_RE = re.compile(r"(\d{2,5})x(\d{2,5})")


def _detect_server_version() -> str:
    exe = shutil.which("scrcpy")
    if exe:
        try:
            out = subprocess.check_output([exe, "--version"], text=True, timeout=5)
            for tok in out.splitlines()[0].split():
                if tok[:1].isdigit() and "." in tok:
                    return tok
        except Exception:  # pragma: no cover
            pass
    return "3.3.4"


def _find_server_jar() -> str:
    for c in _DEFAULT_SERVER_CANDIDATES:
        if c and Path(c).exists():
            return c
    raise RuntimeError(
        "未找到 scrcpy-server。请 `brew install scrcpy`,或设 SCRCPY_SERVER_PATH 指向 server 文件。"
    )


def _round_down8(v: int) -> int:
    return max(8, (v // 8) * 8)


def _output_size(dev_w: int, dev_h: int, max_size: int) -> tuple[int, int]:
    """按 scrcpy 规则由设备显示尺寸算出编码后尺寸:长边缩到 max_size,保持宽高比,
    两维向下取到 8 的倍数(与 scrcpy 一致,避免逐帧 reshape 错位)。"""
    if max_size <= 0 or max(dev_w, dev_h) <= max_size:
        return _round_down8(dev_w), _round_down8(dev_h)
    scale = max_size / max(dev_w, dev_h)
    return _round_down8(round(dev_w * scale)), _round_down8(round(dev_h * scale))


class ScrcpyCapture(CaptureSource):
    def __init__(
        self,
        serial: str | None = None,
        max_size: int = 1280,
        max_fps: int = 30,
        bit_rate: int = 8_000_000,
    ):
        self.serial = serial
        self.max_size = max_size
        self.max_fps = max_fps
        self.bit_rate = bit_rate

        self._server: subprocess.Popen | None = None
        self._ff: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._latest: np.ndarray | None = None
        self._latest_ts: float = 0.0
        self._lock = threading.Lock()
        self._port: int | None = None
        self._primer = b""  # 建连时预读的首包码流,交给 feed 线程先写入 ffmpeg
        self._wh: tuple[int, int] | None = None  # (W, H) 由设备尺寸推算
        # scid 需为正的 31 位十六进制(server 按有符号 int radix16 解析,上限 7fffffff)
        self._scid = f"{int.from_bytes(os.urandom(4), 'big') & 0x7FFFFFFF:08x}"

    def _adb(self, *args: str) -> list[str]:
        base = ["adb"]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def _device_size(self) -> tuple[int, int]:
        """当前显示尺寸(优先 Override,否则 Physical)。"""
        out = subprocess.check_output(self._adb("shell", "wm", "size"), text=True)
        phys = override = None
        for line in out.splitlines():
            m = _SIZE_RE.search(line)
            if not m:
                continue
            wh = (int(m.group(1)), int(m.group(2)))
            if "Override" in line:
                override = wh
            elif "Physical" in line:
                phys = wh
        size = override or phys
        if not size:
            raise RuntimeError(f"无法解析设备尺寸: {out!r}")
        return size

    def open(self) -> None:
        server_jar = _find_server_jar()
        version = _detect_server_version()

        dev_w, dev_h = self._device_size()
        self._wh = _output_size(dev_w, dev_h, self.max_size)
        logger.info(f"设备 {dev_w}x{dev_h} -> 编码 {self._wh[0]}x{self._wh[1]}")

        subprocess.check_call(self._adb("push", server_jar, _DEVICE_SERVER_PATH),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        socket_name = f"localabstract:scrcpy_{self._scid}"
        out = subprocess.check_output(self._adb("forward", "tcp:0", socket_name), text=True)
        self._port = int(out.strip())

        server_cmd = (
            f"CLASSPATH={_DEVICE_SERVER_PATH} app_process / "
            f"com.genymobile.scrcpy.Server {version} "
            f"scid={self._scid} log_level=info "
            f"video=true audio=false control=false "
            f"tunnel_forward=true raw_stream=true "
            f"max_size={self.max_size} max_fps={self.max_fps} "
            f"video_bit_rate={self.bit_rate}"
        )
        self._server = subprocess.Popen(
            self._adb("shell", server_cmd),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        # 连接视频 socket。server 需时间在设备侧 bind localabstract socket;若在此之前连接,
        # adb 可能返回一个立刻 EOF 的空连接。故连上后先确认能收到首包数据,否则重连。
        deadline = time.time() + 8.0
        last_err: Exception | None = None
        primer = b""
        while time.time() < deadline and not self._stop.is_set():
            try:
                s = socket.create_connection(("127.0.0.1", self._port), timeout=2.0)
            except OSError as e:  # pragma: no cover
                last_err = e
                time.sleep(0.2)
                continue
            s.settimeout(1.0)
            try:
                primer = s.recv(65536)  # 确认有真实码流
            except OSError:
                primer = b""
            if primer:
                s.settimeout(None)
                self._sock = s
                self._primer = primer
                break
            s.close()
            time.sleep(0.2)
        if self._sock is None:
            raise RuntimeError(f"连接 scrcpy 视频流失败(无码流): {last_err}")

        # 起 ffmpeg:h264(stdin) -> 固定尺寸 rawvideo bgr24(stdout)。
        # 强制 scale 到确定尺寸,即使 scrcpy 实际编码尺寸有 ±几像素出入也不会 reshape 错位。
        w, h = self._wh
        self._ff = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "info",
                "-flags", "low_delay",
                "-f", "h264", "-i", "pipe:0",
                "-vf", f"scale={w}:{h}",
                "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._feed_loop, daemon=True),
            threading.Thread(target=self._stderr_loop, daemon=True),
            threading.Thread(target=self._decode_loop, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _feed_loop(self) -> None:
        """socket -> ffmpeg.stdin。"""
        assert self._sock and self._ff and self._ff.stdin
        try:
            if self._primer:
                self._ff.stdin.write(self._primer)
                self._primer = b""
            while not self._stop.is_set():
                data = self._sock.recv(65536)
                if not data:
                    break
                self._ff.stdin.write(data)
        except Exception:  # pragma: no cover
            pass
        finally:
            try:
                self._ff.stdin.close()
            except Exception:
                pass

    def _stderr_loop(self) -> None:
        """必须排空 ffmpeg.stderr,否则管道写满会阻塞解码。"""
        assert self._ff and self._ff.stderr
        for _raw in iter(self._ff.stderr.readline, b""):
            if self._stop.is_set():
                break  # 丢弃即可

    def _decode_loop(self) -> None:
        """ffmpeg.stdout -> 一帧帧 bgr24 ndarray。"""
        if self._wh is None:
            return
        w, h = self._wh
        frame_bytes = w * h * 3
        assert self._ff and self._ff.stdout
        stdout = self._ff.stdout
        buf = bytearray()
        while not self._stop.is_set():
            chunk = stdout.read(frame_bytes - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) >= frame_bytes:
                img = np.frombuffer(bytes(buf[:frame_bytes]), np.uint8).reshape(h, w, 3)
                with self._lock:
                    self._latest = img
                    self._latest_ts = time.time()
                del buf[:frame_bytes]

    def grab(self) -> Frame:
        if self._sock is None:
            self.open()
        deadline = time.time() + 8.0
        while True:
            with self._lock:
                img, ts = self._latest, self._latest_ts
            if img is not None:
                return Frame(image=img.copy(), timestamp=ts)
            if time.time() > deadline:
                raise RuntimeError("scrcpy 8 秒内未产出画面帧(检查设备是否亮屏)")
            time.sleep(0.005)

    def close(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        for proc in (self._ff, self._server):
            if proc:
                proc.terminate()
        self._ff = self._server = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._port is not None:
            subprocess.call(self._adb("forward", "--remove", f"tcp:{self._port}"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._port = None
