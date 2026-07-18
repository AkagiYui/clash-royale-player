"""感知层流水线:一帧图像 -> 结构化 GameState。

组合各子模块(归一化 / 圣水 / 手牌 / 塔血 / 单位检测 / 计时器 / 阶段),
输出干净的 JSON 状态。感知与决策解耦——本层不返回任何像素。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from crplayer.capture.base import Frame
from crplayer.perception.cards import HandRecognizer
from crplayer.perception.detector import UnitDetector
from crplayer.perception.elixir import read_elixir
from crplayer.perception.hp import read_towers
from crplayer.perception.layout import Layout
from crplayer.perception.normalize import to_canvas
from crplayer.perception.phase import classify_phase
from crplayer.perception.timer import TimerReader
from crplayer.state.schema import GameState

_CARDS_YAML = Path(__file__).resolve().parents[3] / "config" / "cards.yaml"


def _load_card_meta() -> dict:
    if not _CARDS_YAML.exists():
        return {}
    with open(_CARDS_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("cards", {})


class PerceptionPipeline:
    def __init__(
        self,
        layout: Layout | None = None,
        model_path: str | Path | None = None,
        device: str | None = None,
        enable_ocr: bool = True,
    ):
        self.layout = layout or Layout.load()
        card_meta = _load_card_meta()
        self.hand = HandRecognizer(card_meta=card_meta)
        self.detector = UnitDetector(model_path=model_path, device=device)
        self.timer = TimerReader() if enable_ocr else None

    def process(self, frame: Frame, frame_id: int = 0) -> GameState:
        canvas = to_canvas(frame.image, self.layout.canvas_wh)
        return self._process_canvas(canvas, frame.timestamp, frame_id)

    def process_image(
        self, image: np.ndarray, timestamp: float = 0.0, frame_id: int = 0
    ) -> GameState:
        canvas = to_canvas(image, self.layout.canvas_wh)
        return self._process_canvas(canvas, timestamp, frame_id)

    def _process_canvas(self, canvas: np.ndarray, timestamp: float, frame_id: int) -> GameState:
        elixir = read_elixir(canvas, self.layout.roi("elixir", "roi"),
                             int(self.layout.get("elixir", "max", default=10)))
        hand, next_card = self.hand.recognize(canvas, self.layout)
        towers = read_towers(canvas, self.layout)
        units = self.detector.detect(canvas, self.layout)
        time_left = self.timer.read_time_left(canvas, self.layout) if self.timer else None
        phase = classify_phase(elixir, time_left)

        return GameState(
            timestamp=timestamp,
            frame_id=frame_id,
            phase=phase,
            elixir=elixir,
            hand=hand,
            next_card=next_card,
            towers=towers,
            units=units,
            time_left=time_left,
        )
