"""感知层冒烟测试:无需真机、无需权重也能跑通全链路。"""

import numpy as np

from crplayer.perception import PerceptionPipeline
from crplayer.perception.elixir import read_elixir
from crplayer.perception.layout import ROI, Layout
from crplayer.state.schema import GameState, Phase


def _synthetic_frame(w=720, h=1280):
    """造一张带粉色圣水条的假画面,验证规则法 + 链路。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # 圣水条区域(与 layout 默认 roi 大致对齐),画一半的品红填充
    y = int(0.945 * h)
    bar_h = int(0.028 * h)
    x1 = int(0.205 * w)
    x2 = int(0.205 * w + 0.775 * w)
    mid = (x1 + x2) // 2
    img[y:y + bar_h, x1:mid] = (200, 0, 200)  # BGR 品红
    return img


def test_layout_loads():
    layout = Layout.load()
    assert layout.canvas_wh == (720, 1280)
    assert isinstance(layout.roi("elixir", "roi"), ROI)


def test_elixir_rule_based_reads_half():
    layout = Layout.load()
    img = _synthetic_frame()
    val = read_elixir(img, layout.roi("elixir", "roi"), 10)
    assert val is not None
    # 填充到中点,约等于 5(容忍归一化/边界误差)
    assert 3.5 <= val <= 6.5


def test_pipeline_runs_without_model():
    """无 YOLO 权重时应返回空单位列表,但状态结构完整可序列化。"""
    pipe = PerceptionPipeline(enable_ocr=False)
    state = pipe.process_image(_synthetic_frame(), timestamp=123.0)
    assert isinstance(state, GameState)
    assert state.units == []            # 无权重
    assert len(state.towers) == 6       # 六座塔占位
    assert state.phase == Phase.BATTLE  # 有圣水读数
    # JSON 可序列化
    s = state.to_json()
    assert "elixir" in s
