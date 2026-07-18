"""adb screencap 采集源。

最简单、零额外依赖,但每帧要完整截图+编码+传输往返,延迟最高。
适合起步跑通链路与单帧调试;实时 CV 输入建议换 scrcpy(见 capture/scrcpy.py)。
"""

from __future__ import annotations

import time

import numpy as np

from crplayer.capture.base import CaptureSource, Frame


class AdbCapture(CaptureSource):
    def __init__(self, serial: str | None = None):
        """serial 为 None 时使用唯一在线设备;多设备需显式指定(见 `adb devices`)。"""
        self.serial = serial
        self._device = None

    def open(self) -> None:
        import adbutils

        if self.serial:
            self._device = adbutils.adb.device(serial=self.serial)
        else:
            devices = adbutils.adb.device_list()
            if not devices:
                raise RuntimeError(
                    "未检测到 adb 设备。请先连接安卓设备并开启 USB 调试,"
                    "然后 `adb devices` 确认。"
                )
            if len(devices) > 1:
                serials = ", ".join(d.serial for d in devices)
                raise RuntimeError(f"检测到多个设备,请用 serial 指定其一: {serials}")
            self._device = devices[0]

    def grab(self) -> Frame:
        if self._device is None:
            self.open()
        ts = time.time()
        pil_img = self._device.screenshot()  # PIL.Image, RGB
        rgb = np.asarray(pil_img.convert("RGB"))
        bgr = rgb[:, :, ::-1].copy()  # RGB -> BGR(OpenCV 约定)
        return Frame(image=bgr, timestamp=ts)
