"""圣水条识别 —— 规则法(像素计数),不需要训练模型。

原理:圣水条填充部分是高饱和的品红/粉色,空槽偏暗。沿条带从左到右统计
"粉色"列的占比,乘以最大值(10)得到当前圣水估计。
"""

from __future__ import annotations

import cv2
import numpy as np

from crplayer.perception.layout import ROI

# OpenCV HSV: H∈[0,180]。皇室战争圣水为品红/粉色,H 约在 140~175。
_PINK_LOWER = np.array([140, 80, 120], dtype=np.uint8)
_PINK_UPPER = np.array([176, 255, 255], dtype=np.uint8)


def read_elixir(canvas: np.ndarray, roi: ROI, max_elixir: int = 10) -> float | None:
    """返回当前圣水估计(0~max,浮点)。无法判断时返回 None。"""
    strip = roi.crop(canvas)
    if strip.size == 0 or strip.shape[1] < max_elixir:
        return None

    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _PINK_LOWER, _PINK_UPPER)

    # 每一列粉色像素占比,超过阈值视为"已填充"
    col_frac = mask.mean(axis=0) / 255.0
    filled_cols = col_frac > 0.4

    if not filled_cols.any():
        return 0.0

    # 取从左侧起最靠右的已填充位置,更贴近"液面"位置(抗中间噪点)
    width = filled_cols.shape[0]
    rightmost = int(np.where(filled_cols)[0][-1]) + 1
    frac = rightmost / width
    return round(frac * max_elixir, 2)
