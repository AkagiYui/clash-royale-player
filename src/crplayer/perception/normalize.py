"""分辨率归一化 + 校正。

架构文档 1.2 第一步:把任意分辨率输入统一归一化到固定虚拟画布。
MVP 实现:去黑边(letterbox trim)→ 缩放到画布尺寸。
后续可在此加入游戏区域检测 + 透视/仿射校正。
"""

from __future__ import annotations

import cv2
import numpy as np


def _trim_black_borders(image: np.ndarray, thresh: int = 12) -> np.ndarray:
    """去掉四周近黑边(异形屏/录屏留边)。找到最大非黑内容区域。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = gray > thresh
    if not mask.any():
        return image
    ys = np.where(mask.any(axis=1))[0]
    xs = np.where(mask.any(axis=0))[0]
    y1, y2 = int(ys[0]), int(ys[-1]) + 1
    x1, x2 = int(xs[0]), int(xs[-1]) + 1
    return image[y1:y2, x1:x2]


def to_canvas(
    image: np.ndarray,
    canvas_wh: tuple[int, int],
    *,
    trim_borders: bool = True,
) -> np.ndarray:
    """归一化到虚拟画布(BGR, canvas_wh=(W,H))。

    注:直接缩放会改变宽高比。竖屏截图与目标画布同为竖屏时形变可忽略;
    若输入含黑边或宽高比差异大,先 trim 再缩放。
    """
    img = image
    if trim_borders:
        img = _trim_black_borders(img)
    w, h = canvas_wh
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
