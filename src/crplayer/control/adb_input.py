"""adb input 触控注入(经 InputManager,带正确 displayId,本机 Android 16 实测可用)。

为什么需要它(MaaTouch 不通根因,已对照官方源码求证):
    本机(OPPO OPD2413,Android 16 / SDK 36)上,MaaTouch 的注入**能被输入监视层看到**
    (开发者选项"指针位置"叠层显示 P:1/1、坐标、压力都对),但**不会被派发到游戏窗口**
    —— 点"对战""确定"等按钮毫无反应。对同一坐标改用 `adb shell input tap` 则正常触发
    (能开始匹配、能关对话框)。此问题**与设备/系统版本有关,与反外挂无关**,别的设备没有。

    根因在 MotionEvent 的 **displayId**。查 MaaTouch 官方源码 Controller.java:
        MotionEvent.obtain(..., DEFAULT_DEVICE_ID, 0, SOURCE_TOUCHSCREEN, 0);
        injectEvent(event, InputManager.INJECT_MODE_ASYNC);
    它**从不调用 setDisplayId**,事件 displayId 为 INVALID_DISPLAY(-1);又用 ASYNC 模式
    (不等结果),失败时**静默无报错**。Android 12+ 的 InputDispatcher 会把无有效目标显示的
    注入事件丢弃(logcat 典型 "no touched window on display"),但仍会被输入监视器(指针叠层)
    看到 —— 恰好解释"叠层有、游戏无反应"。`adb shell input` 会带上有效 displayId,故能派发。

    官方 MaaTouch(截至 master)并未修复此问题;scrcpy 早已解决(见其 issue #3186):注入前用
    反射 `InputEvent.setDisplayId(displayId)` 把事件绑定目标显示——MaaTouch 缺的正是这一步。
    MAA 主项目对多显示器的处理(issue #12175)只在 screencap 层(-d 指定显示),与注入无关。
    MaaTouch 是编译好的 dex 无法从外部补 displayId,故本机改用本后端。scrcpy 控制通道设计上
    带 displayId(理应可用),但本仓当前实现实测未注入(P:0/1),待调试——见 scrcpy_control.py。

接口与 MaaTouchController 对齐(tap/swipe/drag/tap_norm/swipe_norm/open/close),
供 SceneController 直接替换。坐标为**逻辑显示坐标**(与截图/adb 同坐标系)。

代价:每次动作 spawn 一次 `adb shell input`(约几十毫秒),不如 MaaTouch 常驻管道低延迟;
但菜单导航与皇室战争的低频决策足够用。需要更低延迟时可换 scrcpy 控制通道。
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
