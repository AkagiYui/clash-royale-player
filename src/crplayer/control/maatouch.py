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

坑(来自 StarRailCopilot 经验):MaaTouch 在**启动时缓存屏幕方向**,握手返回的 max_x/max_y
对应当时的方向。若设备发生横竖屏旋转,坐标系会错位,需要重启 MaaTouch 进程(调用
reinit())。皇室战争对战恒为竖屏,通常无此问题,但退到桌面/其它方向界面时要留意。
另:长时间运行管道可能断开,_write() 会自动重连一次自愈。
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
        # 屏幕旋转(0/1/2/3 = 0/90/180/270)。MaaTouch 注入到自然方向的输入层,
        # 若显示处于旋转态,需把逻辑坐标转换回自然方向坐标(见 _to_native)。
        self.rotation = 0

    def _adb(self, *args: str) -> list[str]:
        base = ["adb"]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def _query_rotation(self) -> int:
        """读取当前显示旋转(0/1/2/3)。跨 OEM 尽量兼容。"""
        try:
            out = subprocess.check_output(
                self._adb("shell", "dumpsys", "window", "displays"), text=True, timeout=5
            )
        except Exception:  # pragma: no cover
            return 0
        import re

        m = re.search(r"mRotation=ROTATION_(\d+)", out) or re.search(r"mRotation=(\d)", out)
        if not m:
            return 0
        val = int(m.group(1))
        return {0: 0, 90: 1, 180: 2, 270: 3}.get(val, val if val in (0, 1, 2, 3) else 0)

    def _to_native(self, x: int, y: int) -> tuple[int, int]:
        """把逻辑显示坐标转换为 MaaTouch 注入所用的自然方向坐标。

        本设备自然方向为竖屏(max_x x max_y)。屏幕旋转 180° 时,adb input 走逻辑坐标不受
        影响,但 MaaTouch 直写输入层(自然方向),坐标会整体翻转,需在此校正。
        """
        r = self.rotation
        if r == 0:
            return x, y
        if r == 2:  # 180° 上下颠倒
            return self.max_x - x, self.max_y - y
        # 90/270:竖屏游戏通常不会走到,做一次坐标轴交换的近似并告警
        logger.warning(f"MaaTouch 遇到旋转 {r*90}°,坐标变换未充分验证")
        if r == 1:  # 90
            return y, self.max_y - x
        return self.max_x - y, x  # 270

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
        self.rotation = self._query_rotation()
        if self.rotation:
            logger.info(f"当前屏幕旋转 {self.rotation * 90}°,MaaTouch 坐标将做方向校正")

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
            if line == "Aborted":
                # MaaTouch 未正确安装(二进制缺失/损坏)时的典型输出
                raise RuntimeError("MaaTouch 返回 Aborted:二进制可能未正确 push 到设备")
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

    def _reconnect(self) -> None:
        """重建 MaaTouch 进程(长时间运行中管道断开 / adb 重连后自愈)。"""
        logger.warning("MaaTouch 管道断开,重连中…")
        try:
            if self._proc:
                self._proc.terminate()
        except Exception:
            pass
        self._proc = None
        self.open()

    # —— 底层写入 ——
    def _write(self, *lines: str) -> None:
        payload = ("".join(f"{ln}\n" for ln in lines)).encode()
        for attempt in (1, 2):
            if self._proc is None or self._proc.stdin is None:
                self._reconnect()
            try:
                with self._lock:
                    self._proc.stdin.write(payload)  # type: ignore[union-attr]
                    self._proc.stdin.flush()          # type: ignore[union-attr]
                return
            except (BrokenPipeError, OSError) as e:
                if attempt == 2:
                    raise
                logger.warning(f"MaaTouch 写入失败({e}),尝试重连")
                self._reconnect()

    def _prep(self, x: int, y: int) -> tuple[int, int]:
        """输入逻辑显示坐标 -> 裁剪到屏内 -> 转换为注入用的自然方向坐标。"""
        cx = min(max(int(x), 0), self.max_x - 1) if self.max_x else int(x)
        cy = min(max(int(y), 0), self.max_y - 1) if self.max_y else int(y)
        return self._to_native(cx, cy)

    # —— 设备像素坐标 API(传入逻辑显示坐标,与截图坐标系一致)——
    def tap(self, x: int, y: int, hold_ms: int = 0, contact: int = 0) -> None:
        """在设备像素 (x,y) 点击(逻辑坐标,自动做旋转校正)。

        关键:down/commit/up/commit 必须**一次性**写入同一 payload(参考 SRC)。
        若在 down 与 up 之间用 Python sleep 分成两次写,触点会保持按下,下一次 down
        变成拖拽,按钮永远收不到"点击"。hold 用设备端 `w` 事件实现,仍在同一 payload。
        """
        x, y = self._prep(x, y)
        cmds = [f"d {contact} {x} {y} {_PRESSURE}", "c"]
        if hold_ms > 0:
            cmds.append(f"w {hold_ms}")
        cmds += [f"u {contact}", "c"]
        self._write(*cmds)

    def swipe(
        self,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300, steps: int = 16, contact: int = 0,
    ) -> None:
        """从 (x1,y1) 拖到 (x2,y2)(逻辑坐标)。用设备端 w 事件控制节奏。"""
        x1, y1 = self._prep(x1, y1)
        x2, y2 = self._prep(x2, y2)
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

    def reinit(self) -> None:
        """重启 MaaTouch(屏幕方向变化后必须调用,以刷新缓存的坐标系)。"""
        self._reconnect()

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
