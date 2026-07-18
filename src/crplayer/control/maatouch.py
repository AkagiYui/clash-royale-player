"""MaaTouch 触控注入(常驻 socket,最贴近真实物理触控)。

架构文档阶段零:MaaTouch 优于 adb input / scrcpy 控制通道——常驻进程免去 spawn 开销,
多点触控原生支持。100% Java,通过 app_process 运行,不需按 CPU 架构匹配二进制。

部署:adb push bin/maatouch 到 /data/local/tmp/,app_process 起进程,stdin 收命令。
建连时只用一次 adb,之后每次点击/拖拽走常驻 stdin 管道。采集(scrcpy)与执行(本模块)
是两条独立通道。

Wire 协议(来自 MaaTouch InputThread):
  d <id> <x> <y> <pressure>   按下
  m <id> <x> <y> <pressure>   移动
  u <id>                      抬起
  c                           提交(把前面的事件作为一组执行)
  w <ms>                      等待
  r                           复位所有触点
  k <keycode> <d|u|o>         按键 down/up/一次
  t <text>                    文本输入
注意:pressure 在设备端按整数除以 255,必须传 255 才算真实按下。
坐标为显示像素(header 的 ^ 行给出 max_x/max_y = 显示分辨率)。
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from loguru import logger

_LOCAL_BINARY = Path(__file__).resolve().parents[3] / "bin" / "maatouch"
_DEVICE_BINARY = "/data/local/tmp/maatouch"
_MAIN_CLASS = "com.shxyke.MaaTouch.App"
_PRESSURE = 255  # 必须为 255(设备端整数除法)


class MaaTouchController:
    def __init__(self, serial: str | None = None, binary: str | Path | None = None):
        self.serial = serial
        self.binary = Path(binary) if binary else _LOCAL_BINARY
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.max_x = 0
        self.max_y = 0
        self.max_contacts = 10

    def _adb(self, *args: str) -> list[str]:
        base = ["adb"]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def open(self) -> None:
        if not self.binary.exists():
            raise RuntimeError(
                f"未找到 MaaTouch 二进制: {self.binary}。"
                "从 github.com/MaaAssistantArknights/MaaTouch releases 下载 maatouch 放到 bin/。"
            )
        subprocess.check_call(self._adb("push", str(self.binary), _DEVICE_BINARY),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.call(self._adb("shell", "chmod", "755", _DEVICE_BINARY),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cmd = f"CLASSPATH={_DEVICE_BINARY} app_process / {_MAIN_CLASS}"
        self._proc = subprocess.Popen(
            self._adb("shell", cmd),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._read_header()

    def _read_header(self) -> None:
        """解析 `^ <max_contacts> <max_x> <max_y> <max_pressure>` 与 `$ <pid>`。"""
        assert self._proc and self._proc.stdout
        deadline = time.time() + 5.0
        while time.time() < deadline:
            line = self._proc.stdout.readline().decode(errors="replace").strip()
            if not line:
                if self._proc.poll() is not None:
                    err = ""
                    if self._proc.stderr:
                        err = self._proc.stderr.read().decode(errors="replace")
                    raise RuntimeError(f"MaaTouch 进程退出。stderr:\n{err[-500:]}")
                continue
            if line.startswith("^"):
                parts = line.split()
                # ^ max_contacts max_x max_y max_pressure
                self.max_contacts = int(parts[1])
                self.max_x = int(parts[2])
                self.max_y = int(parts[3])
            elif line.startswith("$"):
                logger.info(
                    f"MaaTouch 就绪:{self.max_x}x{self.max_y},最多 {self.max_contacts} 触点"
                )
                return
        raise RuntimeError("MaaTouch 未在 5 秒内返回握手头")

    # —— 底层写入 ——
    def _write(self, *lines: str) -> None:
        assert self._proc and self._proc.stdin
        payload = ("".join(f"{ln}\n" for ln in lines)).encode()
        with self._lock:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        cx = min(max(int(x), 0), self.max_x - 1) if self.max_x else int(x)
        cy = min(max(int(y), 0), self.max_y - 1) if self.max_y else int(y)
        return cx, cy

    # —— 设备像素坐标 API ——
    def tap(self, x: int, y: int, hold_ms: int = 40, contact: int = 0) -> None:
        """在设备像素 (x,y) 点击。"""
        x, y = self._clamp(x, y)
        self._write(f"d {contact} {x} {y} {_PRESSURE}", "c")
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        self._write(f"u {contact}", "c")

    def swipe(
        self,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300, steps: int = 16, contact: int = 0,
    ) -> None:
        """从 (x1,y1) 拖到 (x2,y2)。用设备端 w 事件控制节奏。"""
        x1, y1 = self._clamp(x1, y1)
        x2, y2 = self._clamp(x2, y2)
        steps = max(steps, 1)
        step_ms = max(duration_ms // steps, 1)
        self._write(f"d {contact} {x1} {y1} {_PRESSURE}", "c")
        for i in range(1, steps + 1):
            t = i / steps
            xi = int(x1 + (x2 - x1) * t)
            yi = int(y1 + (y2 - y1) * t)
            self._write(f"m {contact} {xi} {yi} {_PRESSURE}", f"w {step_ms}", "c")
        self._write(f"u {contact}", "c")

    # —— 归一化坐标 API(0~1),按 header 分辨率换算 ——
    def tap_norm(self, nx: float, ny: float, **kw) -> None:
        self.tap(int(nx * self.max_x), int(ny * self.max_y), **kw)

    def swipe_norm(self, nx1, ny1, nx2, ny2, **kw) -> None:
        self.swipe(int(nx1 * self.max_x), int(ny1 * self.max_y),
                   int(nx2 * self.max_x), int(ny2 * self.max_y), **kw)

    # —— 按键 / 文本(MaaTouch 扩展)——
    def key(self, keycode: int, action: str = "o") -> None:
        """action: d 按下 / u 抬起 / o 单次(down+up)。keycode 为 Android KEYCODE。"""
        self._write(f"k {keycode} {action}")

    def text(self, s: str) -> None:
        self._write(f"t {s}")

    def reset(self) -> None:
        self._write("r")

    def close(self) -> None:
        if self._proc:
            try:
                self.reset()
                self._proc.stdin.close()
            except Exception:
                pass
            self._proc.terminate()
            self._proc = None

    def __enter__(self) -> MaaTouchController:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
