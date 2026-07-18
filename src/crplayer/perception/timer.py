"""计时器 / 比分 —— OCR(可插拔后端)。

tesseract 未安装时用 easyocr(`pip install '.[ocr]'`)。两者都没有时返回 None,
不阻塞链路。OCR 只用于计时器/比分这类少量数字,不是主感知路径。
"""

from __future__ import annotations

import re

from loguru import logger

from crplayer.perception.layout import Layout

_TIME_RE = re.compile(r"(\d{1,2})[:：'](\d{2})")


class TimerReader:
    def __init__(self):
        self._reader = None
        self._backend = self._init_backend()

    def _init_backend(self) -> str:
        try:
            import easyocr  # type: ignore

            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            return "easyocr"
        except Exception:
            logger.info("未启用 OCR 后端(可选:uv pip install '.[ocr]');计时器将为 None")
            return "none"

    def _ocr_text(self, region_bgr) -> str:
        if self._backend != "easyocr" or self._reader is None or region_bgr.size == 0:
            return ""
        # easyocr 吃 RGB
        rgb = region_bgr[:, :, ::-1]
        try:
            parts = self._reader.readtext(rgb, detail=0)
            return " ".join(parts)
        except Exception as e:  # pragma: no cover
            logger.debug(f"OCR 失败: {e}")
            return ""

    def read_time_left(self, canvas, layout: Layout) -> int | None:
        """读取剩余秒数。识别不到返回 None。"""
        roi = layout.roi("timer", "roi")
        text = self._ocr_text(roi.crop(canvas))
        m = _TIME_RE.search(text)
        if not m:
            return None
        return int(m.group(1)) * 60 + int(m.group(2))
