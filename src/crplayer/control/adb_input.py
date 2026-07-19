"""adb input 触控注入(经 InputManager,带正确 displayId)。当前默认触控后端。

选型说明(2026-07-19 三后端×两设备实测):
    adb input 在 69dbcd7c(OPD2413/Android16)与 8ddbcbe5(PKR110/Android15)上均稳定可用
    ——`adb shell input -d <display>` 带有效 displayId,可靠派发到游戏窗口(点"对战"开局、
    点"确定"关结算)。作为默认后端主要图其**简单稳定、零额外部署**(不依赖推 maatouch 二进制、
    不依赖 scrcpy-server)。

    历史更正:早先曾认为 MaaTouch 在 69dbcd7c 上"注入不派发到游戏窗口、根因缺 setDisplayId",
    并以此作为改用本后端的理由——**该诊断已证伪**。MaaTouch 现两台都能正常点"对战"(见
    control/maatouch.py 顶部),早期"点不动"实为其坐标/旋转换算 bug(已修)+ 当时肉眼估坐标
    估歪。故 adb 与 maatouch 均可用;scrcpy 控制通道两台都不通、待调试(见 scrcpy_control.py)。

接口与 MaaTouchController 对齐(tap/swipe/drag/tap_norm/swipe_norm/open/close),
供 SceneController 直接替换。坐标为**逻辑显示坐标**(与截图/adb 同坐标系)。

代价:每次动作 spawn 一次 `adb shell input`(约几十毫秒),不如 MaaTouch 常驻管道低延迟;
但菜单导航与皇室战争的低频决策足够用。需要更低延迟时可换 MaaTouch(常驻管道,已实测可用)。
"""

from __future__ import annotations

import re
import subprocess

from loguru import logger


class AdbInputController:
    def __init__(self, serial: str | None = None, display_id: int = 0):
        self.serial = serial
        self.display_id = display_id
        self.max_x = 0
        self.max_y = 0
        self.max_contacts = 1  # adb input 单点

    # —— 资源 ——
    def _adb(self, *args: str) -> list[str]:
        base = ["adb"]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def _query_size(self) -> tuple[int, int]:
        out = subprocess.check_output(self._adb("shell", "wm", "size"), text=True, timeout=5)
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(
            r"Physical size:\s*(\d+)x(\d+)", out
        )
        if not m:
            raise RuntimeError(f"无法解析屏幕尺寸: {out!r}")
        return int(m.group(1)), int(m.group(2))

    def open(self) -> None:
        self.max_x, self.max_y = self._query_size()
        logger.info(f"adb input 就绪:{self.max_x}x{self.max_y}(display {self.display_id})")

    def close(self) -> None:  # 无常驻资源
        pass

    def __enter__(self) -> AdbInputController:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # —— 底层 ——
    def _input(self, *args: str) -> None:
        cmd = self._adb("shell", "input", "-d", str(self.display_id), *args)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)

    def _clip(self, x: int, y: int) -> tuple[int, int]:
        cx = min(max(int(x), 0), self.max_x - 1) if self.max_x else int(x)
        cy = min(max(int(y), 0), self.max_y - 1) if self.max_y else int(y)
        return cx, cy

    # —— 设备像素坐标 API(逻辑显示坐标,与截图一致)——
    def tap(self, x: int, y: int, hold_ms: int = 0, contact: int = 0) -> None:
        """点击 (x,y)。hold_ms>0 时用零位移 swipe 实现长按(adb input tap 不支持时长)。"""
        x, y = self._clip(x, y)
        if hold_ms > 0:
            self._input("swipe", str(x), str(y), str(x), str(y), str(hold_ms))
        else:
            self._input("tap", str(x), str(y))

    def swipe(
        self,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300, contact: int = 0, settle: bool = False,
    ) -> None:
        """从 (x1,y1) 拖到 (x2,y2)。settle 对 adb input 无对应语义(单命令),忽略。"""
        x1, y1 = self._clip(x1, y1)
        x2, y2 = self._clip(x2, y2)
        self._input("swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        """带停顿的拖拽(放牌用)。adb input 用较长时长近似 settle。"""
        self.swipe(x1, y1, x2, y2, duration_ms=duration_ms)

    # —— 归一化坐标 API(0~1)——
    def tap_norm(self, nx: float, ny: float, **kw) -> None:
        self.tap(int(nx * self.max_x), int(ny * self.max_y), **kw)

    def swipe_norm(self, nx1, ny1, nx2, ny2, **kw) -> None:
        self.swipe(int(nx1 * self.max_x), int(ny1 * self.max_y),
                   int(nx2 * self.max_x), int(ny2 * self.max_y), **kw)

    # —— 按键 / 文本 ——
    def key(self, keycode: int, action: str = "o") -> None:
        """action 兼容 MaaTouch 语义,但 adb input 只有一次性 keyevent。"""
        self._input("keyevent", str(keycode))

    def text(self, s: str) -> None:
        self._input("text", s)

    def reset(self) -> None:  # 无常驻触点
        pass
