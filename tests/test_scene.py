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
    tmpl = Template(name="main_battle_button", file="main_battle_button_bonus.png",
                    area=(354, 958, 565, 1045))
    canvas = np.zeros((REF_HEIGHT, REF_WIDTH, 3), dtype=np.uint8)
    res = tmpl.match(canvas)
    assert not res.matched


def test_in_battle_marker_loads():
    """对局中标志模板可加载(用于动作前的状态确认)。"""
    tmpl = TEMPLATES["battle_emote"]
    assert tmpl.image.ndim == 3


def test_all_templates_load_and_area_matches_image():
    """所有登记模板(含每个变体)都能加载,且尺寸与 area 一致(防止再切图后忘改 area)。"""
    for name, tmpl in TEMPLATES.items():
        x1, y1, x2, y2 = tmpl.area
        for i, img in enumerate(tmpl.images):
            h, w = img.shape[:2]
            assert (w, h) == (x2 - x1, y2 - y1), (
                f"{name} 变体#{i}: 图 {w}x{h} 与 area {x2-x1}x{y2-y1} 不符"
            )


def test_all_templates_self_match():
    """每个模板的**每个变体**放回其 area 原位都应高分命中。"""
    for name, tmpl in TEMPLATES.items():
        x1, y1, x2, y2 = tmpl.area
        for i, img in enumerate(tmpl.images):
            canvas = np.zeros((REF_HEIGHT, REF_WIDTH, 3), dtype=np.uint8)
            canvas[y1:y2, x1:x2] = img
            res = tmpl.match(canvas)
            assert res.matched and res.score > 0.95, f"{name} 变体#{i}: score={res.score:.3f}"


def test_multi_variant_matches_any():
    """多变体模板:画面里出现任一变体都应命中(以'对战'按钮的两种样式为例)。"""
    tmpl = TEMPLATES["main_battle_button"]
    assert len(tmpl.images) >= 2, "对战按钮应登记多种样式变体"
    x1, y1, x2, y2 = tmpl.area
    for i in range(len(tmpl.images)):
        canvas = np.zeros((REF_HEIGHT, REF_WIDTH, 3), dtype=np.uint8)
        canvas[y1:y2, x1:x2] = tmpl.images[i]
        assert tmpl.match(canvas).matched, f"变体#{i} 未命中"


def test_scenes_reference_known_templates():
    """场景标志引用的模板都已登记。"""
    from crplayer.scene.registry import SCENES

    for scene in SCENES.values():
        for marker in scene.markers:
            assert marker in TEMPLATES, f"{scene.name} 引用未登记模板 {marker}"


def test_insert_swipe_path():
    """贝塞尔滑动路径:起终点正确、点数足够。"""
    from crplayer.control.maatouch import insert_swipe

    pts = insert_swipe((300, 1150), (700, 600))
    assert len(pts) >= 5
    assert pts[0] == [300, 1150]
    # 终点因 min_distance 过滤未必精确落在 p3,但应很接近
    assert abs(pts[-1][0] - 700) <= 12 and abs(pts[-1][1] - 600) <= 12
