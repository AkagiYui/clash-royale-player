from crplayer.control.adb_input import AdbInputController
from crplayer.control.maatouch import MaaTouchController
from crplayer.control.scrcpy_control import ScrcpyControl

__all__ = ["AdbInputController", "MaaTouchController", "ScrcpyControl", "open_touch"]

# 触控后端选择(2026-07-19 两设备实测):
#   adb      —— 经 InputManager,带正确 displayId,简单稳定零部署,两台均可用(默认)。
#   maatouch —— 常驻管道、低延迟,两台均可用(早先"本机不派发"结论已证伪,见 maatouch.py)。
#   scrcpy   —— scrcpy 控制通道,常驻 socket、多点,但当前实现两台都不通、待调试。
_BACKENDS = {
    "adb": AdbInputController,
    "maatouch": MaaTouchController,
    "scrcpy": ScrcpyControl,
}


def open_touch(backend: str = "adb", *, serial: str | None = None, **kwargs):
    """按名字构造触控后端(不 open)。默认 adb —— 简单稳定、两台设备实测均可用。"""
    try:
        cls = _BACKENDS[backend]
    except KeyError:
        raise ValueError(f"未知触控后端: {backend}(可选 {list(_BACKENDS)})") from None
    return cls(serial=serial, **kwargs)
