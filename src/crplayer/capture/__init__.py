from crplayer.capture.adb import AdbCapture
from crplayer.capture.base import CaptureSource, Frame

__all__ = ["CaptureSource", "Frame", "AdbCapture", "open_capture"]


def open_capture(backend: str = "adb", **kwargs) -> CaptureSource:
    """按名称打开采集源。

    backend:
      - "adb"    : adb screencap,零额外依赖,延迟最高,适合起步/单帧调试
      - "scrcpy" : scrcpy H264 视频流,延迟最低(需 `pip install '.[scrcpy]'`)
    """
    if backend == "adb":
        return AdbCapture(**kwargs)
    if backend == "scrcpy":
        from crplayer.capture.scrcpy import ScrcpyCapture

        return ScrcpyCapture(**kwargs)
    raise ValueError(f"未知采集后端: {backend!r}(可选: adb / scrcpy)")
