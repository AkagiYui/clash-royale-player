"""模板匹配的场景元素(Button/Marker)—— 传统 CV,不用大模型。

设计参考 StarRailCopilot/ALAS 的 Button:
  - file   : 模板图,可给**一张**或**一组变体**(list)。同一目标在不同活动/节日/皮肤下
             外观不同(如"对战"按钮),把每种样式各截一张,命中任一即算出现。
  - area   : 模板在参考画布中的位置(x1,y1,x2,y2),用于反推点击偏移
  - search : 匹配搜索区(比 area 略大,容忍按钮轻微位移/动画)
  - click  : 命中后要点击的坐标(参考画布像素)
匹配:在 search 区内对每个变体跑 cv2.matchTemplate,取最高分;最高分 > similarity 即"出现"。
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
    # 模板图文件名(相对 assets/scenes/)。可给**一张**,或给**一组变体**(list):
    # 同一逻辑目标在不同活动/节日/皮肤下外观不同(如"对战"按钮),把每种样式各截一张放进
    # 列表,命中**任一**即算出现——新增样式只需丢一张图并加进列表,匹配逻辑不变。
    # 所有变体应对齐到同一 area 左上角(位置一致、仅外观不同),点击点换算才准确。
    file: str | list[str]
    area: tuple[int, int, int, int]             # 模板在参考画布中的位置
    click: tuple[int, int] | None = None        # 命中后点击点(默认 area 中心)
    search: tuple[int, int, int, int] | None = None  # 搜索区(默认 area 外扩 pad)
    color: tuple[int, int, int] | None = None   # 可选:期望平均色(BGR),叠加校验
    similarity: float = 0.85
    search_pad: int = 24

    _imgs: list[np.ndarray] | None = field(default=None, repr=False, compare=False)

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
    def files(self) -> list[str]:
        """归一化成文件名列表(单图也当作长度 1 的列表)。"""
        return [self.file] if isinstance(self.file, str) else list(self.file)

    @property
    def images(self) -> list[np.ndarray]:
        """所有变体图(懒加载 + 缓存)。"""
        if self._imgs is None:
            imgs = []
            for fn in self.files:
                path = _ASSETS_DIR / fn
                img = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if img is None:
                    raise FileNotFoundError(f"模板图不存在: {path}")
                imgs.append(img)
            self._imgs = imgs
        return self._imgs

    @property
    def image(self) -> np.ndarray:
        """首个变体(兼容旧调用/单图场景)。"""
        return self.images[0]

    def match(self, ref_frame: np.ndarray) -> MatchResult:
        """在参考帧上匹配。ref_frame 必须已是参考画布尺寸。

        多变体时逐一匹配,取**最高分**那张;命中任一变体(最高分过阈值)即算出现。
        """
        sx1, sy1, sx2, sy2 = self.search
        roi = ref_frame[sy1:sy2, sx1:sx2]

        best_score = -1.0
        best_loc = (0, 0)
        for tmpl in self.images:
            if roi.shape[0] < tmpl.shape[0] or roi.shape[1] < tmpl.shape[1]:
                continue
            res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if score > best_score:
                best_score, best_loc = score, loc

        if best_score < 0:  # 所有变体都比搜索区大,无法匹配
            return MatchResult(False, 0.0, self.click)  # type: ignore[arg-type]

        # 命中位置相对模板原始 area 的偏移,用于修正点击点
        off_x = best_loc[0] + sx1 - self.area[0]
        off_y = best_loc[1] + sy1 - self.area[1]
        cx, cy = self.click  # type: ignore[misc]
        click = (cx + off_x, cy + off_y)

        matched = best_score >= self.similarity
        if matched and self.color is not None:
            matched = self._color_ok(ref_frame)
        return MatchResult(matched, float(best_score), click)

    def _color_ok(self, ref_frame: np.ndarray, threshold: int = 25) -> bool:
        x1, y1, x2, y2 = self.area
        avg = ref_frame[y1:y2, x1:x2].reshape(-1, 3).mean(axis=0)
        diff = np.abs(avg - np.array(self.color, dtype=float)).sum()
        return diff <= threshold * 3
