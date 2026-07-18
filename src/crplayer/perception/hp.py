"""血量识别 —— 规则法(血条像素比例),不是 OCR 问题。

通用血条读取:在给定 ROI 内,己方血条偏绿、敌方偏红/蓝,统计"有色填充"
沿水平方向的占比即血量比例。用于塔血量,也可复用到单位血条。
"""

from __future__ import annotations

import cv2
import numpy as np

from crplayer.perception.layout import ROI, Layout
from crplayer.state.schema import Side, TowerState

# 血条颜色范围(HSV)。绿色=满血友方常见,红色=敌方/残血。取二者并集。
_GREEN_LOWER = np.array([35, 80, 80], dtype=np.uint8)
_GREEN_UPPER = np.array([85, 255, 255], dtype=np.uint8)
_RED1_LOWER = np.array([0, 90, 90], dtype=np.uint8)
_RED1_UPPER = np.array([10, 255, 255], dtype=np.uint8)
_RED2_LOWER = np.array([170, 90, 90], dtype=np.uint8)
_RED2_UPPER = np.array([180, 255, 255], dtype=np.uint8)


def _bar_mask(bar_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bar_bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, _GREEN_LOWER, _GREEN_UPPER)
    m |= cv2.inRange(hsv, _RED1_LOWER, _RED1_UPPER)
    m |= cv2.inRange(hsv, _RED2_LOWER, _RED2_UPPER)
    return m


def read_hp_ratio(region_bgr: np.ndarray) -> float | None:
    """从一小块血条图像估计血量比例 [0,1]。无有效血条返回 None。"""
    if region_bgr.size == 0:
        return None
    mask = _bar_mask(region_bgr)
    col_has = mask.mean(axis=0) > (0.3 * 255)
    if not col_has.any():
        return None
    width = col_has.shape[0]
    filled = int(col_has.sum())
    return round(filled / width, 3)


def _tower_hp_roi(cx: float, cy: float, hp_cfg: dict) -> ROI:
    """由塔中心比例坐标 + 偏移配置算出血条 ROI(比例)。"""
    w = float(hp_cfg["w"])
    h = float(hp_cfg["h"])
    dy = float(hp_cfg["dy"])
    x = cx - w / 2.0
    y = cy + dy - h / 2.0
    return ROI(x, y, w, h)


def read_towers(canvas: np.ndarray, layout: Layout) -> list[TowerState]:
    """读取六座塔的血量比例。"""
    towers_cfg = layout.get("towers", default={}) or {}
    hp_cfg = towers_cfg.get("hp_bar", {"dy": -0.045, "w": 0.11, "h": 0.012})

    mapping = [
        ("enemy_king", "king", Side.ENEMY),
        ("enemy_princess_l", "left_princess", Side.ENEMY),
        ("enemy_princess_r", "right_princess", Side.ENEMY),
        ("ally_princess_l", "left_princess", Side.ALLY),
        ("ally_princess_r", "right_princess", Side.ALLY),
        ("ally_king", "king", Side.ALLY),
    ]

    result: list[TowerState] = []
    for key, name, side in mapping:
        anchor = towers_cfg.get(key)
        if not anchor:
            continue
        roi = _tower_hp_roi(float(anchor[0]), float(anchor[1]), hp_cfg)
        ratio = read_hp_ratio(roi.crop(canvas))
        result.append(TowerState(name=name, side=side, hp_ratio=ratio))
    return result
