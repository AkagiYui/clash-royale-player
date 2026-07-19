from crplayer.control.adb_input import AdbInputController
from crplayer.control.maatouch import MaaTouchController
from crplayer.control.scrcpy_control import ScrcpyControl

__all__ = ["AdbInputController", "MaaTouchController", "ScrcpyControl", "open_touch"]

# 触控后端选择:
#   adb      —— 经 InputManager,事件带正确 displayId,国服 Android 16 实测可用(默认)。
#   maatouch —— 常驻管道、低延迟,但本机 Android 16 上事件不派发到游戏窗口(见 adb_input.py)。
#   scrcpy   —— scrcpy 控制通道,常驻 socket、多点。
_BACKENDS = {
    "adb": AdbInputController,
    "maatouch": MaaTouchController,
    "scrcpy": ScrcpyControl,
}


def open_touch(backend: str = "adb", *, serial: str | None = None, **kwargs):
    """按名字构造触控后端(不 open)。默认 adb —— 本机唯一稳定派发到游戏窗口的注入路径。"""
    try:
        cls = _BACKENDS[backend]
    except KeyError:
        raise ValueError(f"未知触控后端: {backend}(可选 {list(_BACKENDS)})") from None
    return cls(serial=serial, **kwargs)
