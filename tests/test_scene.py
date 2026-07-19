"""场景模板匹配的离线测试:不需要真机,验证模板引擎 + 已入库的资源。"""

import numpy as np

from crplayer.scene.registry import TEMPLATES
from crplayer.scene.template import REF_HEIGHT, REF_WIDTH, Template


def test_ref_canvas_size():
    assert (REF_WIDTH, REF_HEIGHT) == (904, 1280)


def test_battle_button_template_loads():
    tmpl = TEMPLATES["main_battle_button"]
    img = tmpl.image
    assert img.ndim == 3 and img.shape[2] == 3


def test_template_self_match():
    """把模板放进空白参考画布的原位,应当高分命中,且点击点落在 area 中心附近。"""
    tmpl = TEMPLATES["main_battle_button"]
    x1, y1, x2, y2 = tmpl.area
    canvas = np.zeros((REF_HEIGHT, REF_WIDTH, 3), dtype=np.uint8)
    canvas[y1:y2, x1:x2] = tmpl.image

    res = tmpl.match(canvas)
    assert res.matched
    assert res.score > 0.95
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    assert abs(res.click[0] - cx) <= 2 and abs(res.click[1] - cy) <= 2


def test_no_false_match_on_blank():
    """纯黑画面不应命中按钮。"""
    tmpl = Template(name="main_battle_button", file="main_battle_button.png",
                    area=(360, 955, 552, 1052))
    canvas = np.zeros((REF_HEIGHT, REF_WIDTH, 3), dtype=np.uint8)
    res = tmpl.match(canvas)
    assert not res.matched


def test_in_battle_marker_loads():
    """对局中标志模板可加载(用于动作前的状态确认)。"""
    tmpl = TEMPLATES["battle_emote"]
    assert tmpl.image.ndim == 3


def test_insert_swipe_path():
    """贝塞尔滑动路径:起终点正确、点数足够。"""
    from crplayer.control.maatouch import insert_swipe

    pts = insert_swipe((300, 1150), (700, 600))
    assert len(pts) >= 5
    assert pts[0] == [300, 1150]
    # 终点因 min_distance 过滤未必精确落在 p3,但应很接近
    assert abs(pts[-1][0] - 700) <= 12 and abs(pts[-1][1] - 600) <= 12
