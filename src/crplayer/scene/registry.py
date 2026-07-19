"""场景与导航图定义(数据)。

- TEMPLATES:所有可匹配元素(场景标志 / 可点击按钮)。
- SCENES  :每个场景由一组标志模板判定(默认需全部出现)。
- EDGES   :导航边 (from_scene, click_template, to_scene) —— 在 from 场景点击某模板到达 to。

随着接入更多界面,在此登记新模板与场景即可,匹配/导航逻辑不变。
坐标均为参考画布(REF_WIDTH x REF_HEIGHT)像素。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from crplayer.scene.template import Template


@dataclass
class Scene:
    name: str
    markers: list[str]              # 判定该场景的模板名
    require_all: bool = True        # True=全部命中才算此场景;False=任一命中

    _extra: dict = field(default_factory=dict)


# —— 模板登记表 ——
TEMPLATES: dict[str, Template] = {
    # 主界面中央的黄色"对战"按钮(国服皮肤):既是主界面标志,也是开始匹配的点击目标
    # 注:国际服"对战"按钮外观不同,接入国际服时需另裁一张 intl 变体。
    "main_battle_button": Template(
        name="main_battle_button",
        file="main_battle_button.png",
        area=(360, 955, 552, 1052),
        similarity=0.85,
    ),
    # 对战中左下角的表情气泡图标:整局常驻、稳定,用作"是否在对局中"的判定标志
    "battle_emote": Template(
        name="battle_emote",
        file="battle_emote.png",
        area=(80, 1035, 200, 1130),
        similarity=0.80,
    ),
}

# —— 场景登记表 ——
SCENES: dict[str, Scene] = {
    "main_menu": Scene(name="main_menu", markers=["main_battle_button"]),
    "in_battle": Scene(name="in_battle", markers=["battle_emote"]),
    # 后续接入:matchmaking(匹配中)、battle_end(结算)…
}

# —— 导航边:在某场景点击某模板 -> 目标场景 ——
EDGES: list[tuple[str, str, str]] = [
    ("main_menu", "main_battle_button", "in_battle"),
]
