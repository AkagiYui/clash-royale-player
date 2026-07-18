"""手牌识别 —— 图像分类。

卡牌不形变,模板匹配即可行(架构文档 1.1)。这里实现可插拔的模板匹配识别器:
- 若 data/card_templates/<name>.png 存在,做归一化模板匹配挑最相似卡;
- 无模板时返回 unknown,但链路完整(后续换成小型 CNN/ResNet 只需替换本类)。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from crplayer.perception.layout import ROI, Layout
from crplayer.state.schema import Card

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "data" / "card_templates"
_MATCH_THRESHOLD = 0.55  # 归一化相关系数低于此值视为 unknown


class HandRecognizer:
    def __init__(
        self,
        templates_dir: str | Path | None = None,
        card_meta: dict | None = None,
        match_size: tuple[int, int] = (64, 80),
    ):
        self.match_size = match_size
        self.card_meta = card_meta or {}
        self.templates = self._load_templates(Path(templates_dir or _TEMPLATES_DIR))

    def _load_templates(self, d: Path) -> dict[str, np.ndarray]:
        templates: dict[str, np.ndarray] = {}
        if not d.exists():
            return templates
        for p in sorted(d.glob("*.png")):
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                continue
            templates[p.stem] = cv2.resize(img, self.match_size, interpolation=cv2.INTER_AREA)
        return templates

    def _classify(self, patch: np.ndarray) -> Card:
        if patch.size == 0 or not self.templates:
            return Card(name="unknown", confidence=0.0)
        probe = cv2.resize(patch, self.match_size, interpolation=cv2.INTER_AREA)
        best_name, best_score = "unknown", -1.0
        for name, tmpl in self.templates.items():
            res = cv2.matchTemplate(probe, tmpl, cv2.TM_CCOEFF_NORMED)
            score = float(res.max())
            if score > best_score:
                best_name, best_score = name, score
        if best_score < _MATCH_THRESHOLD:
            return Card(name="unknown", confidence=round(max(best_score, 0.0), 3))
        cost = self.card_meta.get(best_name, {}).get("elixir")
        return Card(name=best_name, confidence=round(best_score, 3), elixir_cost=cost)

    def recognize(self, canvas: np.ndarray, layout: Layout) -> tuple[list[Card], Card | None]:
        slots_roi = layout.roi("hand", "slots_roi")
        n = int(layout.get("hand", "slot_count", default=4))

        hand: list[Card] = []
        for i in range(n):
            slot = ROI(slots_roi.x + slots_roi.w * i / n, slots_roi.y, slots_roi.w / n, slots_roi.h)
            hand.append(self._classify(slot.crop(canvas)))

        next_card = None
        next_roi = layout.roi("hand", "next_roi")
        next_card = self._classify(next_roi.crop(canvas))
        return hand, next_card
