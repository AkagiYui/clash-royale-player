"""scrcpy 控制通道触控注入(与视频采集不同的第二条 scrcpy 通道)。

复用 scrcpy-server:起一个 **control-only**(video=false control=true)的 server 实例,
通过其控制 socket 发送 INJECT_TOUCH_EVENT 消息注入触控。这是有别于 MaaTouch
(InputManager 反射) / adb input 的第三条注入路径。

实测:
- 国际服:可正常点击/开战。
- 国服(腾讯 ACE):能注册为真实触点(pointer location 显示 P:1/1)并触发部分 UI,
  但"对战/开始匹配"仍被拦(与 MaaTouch/adb input/evdev 结论一致——ACE 针对开战操作
  在输入层之下鉴别,换注入方式无法绕过)。

坐标:传入逻辑显示坐标(与截图一致),消息里带上屏幕宽高,server 端负责映射。
"""

from __future__ import annotations

import socket
import struct
import subprocess
import time

from loguru import logger

_DEVICE_SERVER = "/data/local/tmp/scrcpy-server.jar"
_SERVER_CLASS = "com.genymobile.scrcpy.Server"

# scrcpy 控制消息类型
_TYPE_INJECT_TOUCH = 2
# AMOTION_EVENT_ACTION
_ACTION_DOWN, _ACTION_UP, _ACTION_MOVE = 0, 1, 2
_POINTER_ID = 0x1234


class ScrcpyControl:
    def __init__(self, serial: str | None = None, version: str = "3.3.4"):
        self.serial = serial
        self.version = version
        self._srv: subprocess.Popen | None = None
        self._sock: socket.socket | None = None
        self._port: int | None = None
        self._scid = "1a2b3c4d"
        self.width = 0
        self.height = 0

    def _adb(self, *args: str) -> list[str]:
        base = ["adb"]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def _device_size(self) -> tuple[int, int]:
        out = subprocess.check_output(self._adb("shell", "wm", "size"), text=True)
        import re

        m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(
            r"Physical size:\s*(\d+)x(\d+)", out
        )
        if not m:
            raise RuntimeError(f"无法解析屏幕尺寸: {out!r}")
        return int(m.group(1)), int(m.group(2))

    def open(self) -> None:
        from crplayer.capture.scrcpy import _find_server_jar  # 复用 server 定位

        subprocess.check_call(self._adb("push", _find_server_jar(), _DEVICE_SERVER),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.width, self.height = self._device_size()

        socket_name = f"localabstract:scrcpy_{self._scid}"
        out = subprocess.check_output(self._adb("forward", "tcp:0", socket_name), text=True)
        self._port = int(out.strip())

        cmd = (
            f"CLASSPATH={_DEVICE_SERVER} app_process / {_SERVER_CLASS} {self.version} "
            f"scid={self._scid} log_level=info video=false audio=false control=true "
            f"tunnel_forward=true cleanup=false"
        )
        self._srv = subprocess.Popen(self._adb("shell", cmd),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 连接控制 socket(forward 模式起来需一点时间)
        deadline = time.time() + 8.0
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                self._sock = socket.create_connection(("127.0.0.1", self._port), timeout=2.0)
                break
            except OSError as e:  # pragma: no cover
                last_err = e
                time.sleep(0.15)
        if self._sock is None:
            raise RuntimeError(f"连接 scrcpy 控制通道失败: {last_err}")
        # forward 模式首字节为 dummy(0x00),读掉
        self._sock.settimeout(2.0)
        try:
            self._sock.recv(1)
        except OSError:
            pass
        self._sock.settimeout(None)
        logger.info(f"scrcpy 控制通道就绪:{self.width}x{self.height}")

    def _send_touch(self, action: int, x: int, y: int) -> None:
        assert self._sock is not None
        pressure = 0xFFFF if action != _ACTION_UP else 0
        buttons = 1 if action != _ACTION_UP else 0
        # >B type, B action, Q pointer_id, i x, i y, H w, H h, H pressure, I action_button, I buttons
        pkt = struct.pack(
            ">BBQiiHHHII", _TYPE_INJECT_TOUCH, action, _POINTER_ID,
            int(x), int(y), self.width, self.height, pressure, 0, buttons,
        )
        self._sock.send(pkt)

    def tap(self, x: int, y: int, hold_ms: int = 60) -> None:
        self._send_touch(_ACTION_DOWN, x, y)
        time.sleep(hold_ms / 1000.0)
        self._send_touch(_ACTION_UP, x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300, steps: int = 16) -> None:
        self._send_touch(_ACTION_DOWN, x1, y1)
        for i in range(1, steps + 1):
            t = i / steps
            self._send_touch(_ACTION_MOVE, int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
            time.sleep(duration_ms / 1000.0 / steps)
        self._send_touch(_ACTION_UP, x2, y2)

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._srv:
            self._srv.terminate()
            self._srv = None
        if self._port is not None:
            subprocess.call(self._adb("forward", "--remove", f"tcp:{self._port}"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._port = None

    def __enter__(self) -> ScrcpyControl:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
