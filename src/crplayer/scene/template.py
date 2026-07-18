"""模板匹配的场景元素(Button/Marker)—— 传统 CV,不用大模型。

设计参考 StarRailCopilot/ALAS 的 Button:
  - file   : 模板图(从参考分辨率截图裁下的小图)
  - area   : 模板在参考画布中的位置(x1,y1,x2,y2),用于反推点击偏移
  - search : 匹配搜索区(比 area 略大,容忍按钮轻微位移/动画)
  - click  : 命中后要点击的坐标(参考画布像素)
匹配:在 search 区内 cv2.matchTemplate,相关系数 > similarity 即"出现"。
可选叠加平均色校验(match_color),抗误配。

所有坐标基于**参考画布**(REF_WIDTH x REF_HEIGHT)。任意来源帧先 to_reference() 归一化,
匹配/点击都在参考坐标系;点击时再由上层换算到设备像素。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

# 参考画布:等于本设备 scrcpy 输出(2400x3392 -> max_size1280 -> 904x1280),宽高比正确。
# 换设备时只需保证 to_reference 把帧缩放到同一尺寸即可复用模板。
REF_WIDTH = 904
REF_HEIGHT = 1280

_ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "scenes"


def to_reference(frame_bgr: np.ndarray) -> np.ndarray:
    """把任意分辨率帧缩放到参考画布(BGR)。"""
    h, w = frame_bgr.shape[:2]
    if (w, h) == (REF_WIDTH, REF_HEIGHT):
        return frame_bgr
    return cv2.resize(frame_bgr, (REF_WIDTH, REF_HEIGHT), interpolation=cv2.INTER_AREA)


@dataclass
class MatchResult:
    matched: bool
    score: float
    click: tuple[int, int]  # 参考画布像素


@dataclass
class Template:
    name: str
    file: str                                   # 相对 assets/scenes/ 的文件名
    area: tuple[int, int, int, int]             # 模板在参考画布中的位置
    click: tuple[int, int] | None = None        # 命中后点击点(默认 area 中心)
    search: tuple[int, int, int, int] | None = None  # 搜索区(默认 area 外扩 pad)
    color: tuple[int, int, int] | None = None   # 可选:期望平均色(BGR),叠加校验
    similarity: float = 0.85
    search_pad: int = 24

    _img: np.ndarray | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self.click is None:
            x1, y1, x2, y2 = self.area
            self.click = ((x1 + x2) // 2, (y1 + y2) // 2)
        if self.search is None:
            x1, y1, x2, y2 = self.area
            p = self.search_pad
            self.search = (
                max(x1 - p, 0), max(y1 - p, 0),
                min(x2 + p, REF_WIDTH), min(y2 + p, REF_HEIGHT),
            )

    @property
    def image(self) -> np.ndarray:
        if self._img is None:
            path = _ASSETS_DIR / self.file
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise FileNotFoundError(f"模板图不存在: {path}")
            self._img = img
        return self._img

    def match(self, ref_frame: np.ndarray) -> MatchResult:
        """在参考帧上匹配。ref_frame 必须已是参考画布尺寸。"""
        sx1, sy1, sx2, sy2 = self.search
        roi = ref_frame[sy1:sy2, sx1:sx2]
        tmpl = self.image
        if roi.shape[0] < tmpl.shape[0] or roi.shape[1] < tmpl.shape[1]:
            return MatchResult(False, 0.0, self.click)  # type: ignore[arg-type]

        res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)

        # 命中位置相对模板原始 area 的偏移,用于修正点击点
        off_x = loc[0] + sx1 - self.area[0]
        off_y = loc[1] + sy1 - self.area[1]
        cx, cy = self.click  # type: ignore[misc]
        click = (cx + off_x, cy + off_y)

        matched = score >= self.similarity
        if matched and self.color is not None:
            matched = self._color_ok(ref_frame)
        return MatchResult(matched, float(score), click)

    def _color_ok(self, ref_frame: np.ndarray, threshold: int = 25) -> bool:
        x1, y1, x2, y2 = self.area
        avg = ref_frame[y1:y2, x1:x2].reshape(-1, 3).mean(axis=0)
        diff = np.abs(avg - np.array(self.color, dtype=float)).sum()
        return diff <= threshold * 3
