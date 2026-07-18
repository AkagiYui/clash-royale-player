"""布局配置加载 + ROI 比例裁剪工具。

所有区域都用 [0,1] 比例表达(架构文档 1.2:UI 用比例裁剪,不用绝对像素)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

# 默认配置路径:仓库根下的 config/layout.yaml
_DEFAULT_LAYOUT = Path(__file__).resolve().parents[3] / "config" / "layout.yaml"


@dataclass(frozen=True)
class ROI:
    """比例 ROI:x, y, w, h ∈ [0,1]。"""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_list(cls, v) -> ROI:
        return cls(float(v[0]), float(v[1]), float(v[2]), float(v[3]))

    def to_pixels(self, img_w: int, img_h: int) -> tuple[int, int, int, int]:
        """返回 (x1, y1, x2, y2) 整数像素坐标,已裁剪到图像边界内。"""
        x1 = int(round(self.x * img_w))
        y1 = int(round(self.y * img_h))
        x2 = int(round((self.x + self.w) * img_w))
        y2 = int(round((self.y + self.h) * img_h))
        x1 = max(0, min(x1, img_w))
        x2 = max(0, min(x2, img_w))
        y1 = max(0, min(y1, img_h))
        y2 = max(0, min(y2, img_h))
        return x1, y1, x2, y2

    def crop(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        x1, y1, x2, y2 = self.to_pixels(w, h)
        return image[y1:y2, x1:x2]


class Layout:
    """布局配置的类型化访问器。"""

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def load(cls, path: str | Path | None = None) -> Layout:
        p = Path(path) if path else _DEFAULT_LAYOUT
        with open(p, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    # —— 便捷访问 ——
    @property
    def canvas_wh(self) -> tuple[int, int]:
        c = self.data["canvas"]
        return int(c["width"]), int(c["height"])

    def roi(self, *keys) -> ROI:
        node = self.data
        for k in keys:
            node = node[k]
        return ROI.from_list(node)

    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node
