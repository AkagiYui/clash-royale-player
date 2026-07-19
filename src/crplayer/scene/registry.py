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
    # 底部导航栏"对战"标签(交叉金剑):主菜单**不变**元素(实测两种按钮状态下逐像素零差异),
    # 用作 main_menu 的稳定判定标志。中央黄色"对战"按钮面会随每日奖励状态变化,不适合当标志。
    "battle_tab": Template(
        name="battle_tab",
        file="battle_tab.png",
        area=(388, 1185, 472, 1270),
        similarity=0.85,
    ),
    # 中央黄色"对战"按钮:作**点击目标**(位置固定,点其中心开始匹配)。按钮面会随活动/节日/
    # 每日奖励变化,故用**多变体**:每种样式各一张,命中任一即可。新增节日皮肤只需截图放进
    # assets/scenes/ 并加进下面列表,无需改任何逻辑。main_menu 判定另由不变的 battle_tab 负责。
    "main_battle_button": Template(
        name="main_battle_button",
        file=[
            "main_battle_button_bonus.png",   # 带"每日额外奖励"副文
            "main_battle_button_plain.png",   # 只有"对战"大字
        ],
        area=(354, 958, 565, 1045),
        click=(459, 1001),
        similarity=0.85,
    ),
    # 对战中左下角的表情气泡图标:整局常驻、稳定,用作"是否在对局中"的判定标志
    "battle_emote": Template(
        name="battle_emote",
        file="battle_emote.png",
        area=(80, 1035, 200, 1130),
        similarity=0.80,
    ),
    # 搜索对手(matchmaking):顶部放大镜 +"搜索对手"黑色横幅,匹配阶段常驻
    "matchmaking": Template(
        name="matchmaking",
        file="matchmaking.png",
        area=(90, 143, 339, 219),
        similarity=0.80,
    ),
    # 对局结算(battle_end):底部中央蓝色"确定"键,胜/负结算界面都在同一位置出现
    # click 默认取 area 中心 = 确定键中心,可直接用于点击关闭结算。
    "battle_end": Template(
        name="battle_end",
        file="battle_end.png",
        area=(368, 1088, 537, 1160),
        similarity=0.82,
    ),
}

# —— 场景登记表 ——
# 顺序敏感:current_scene() 取首个命中的场景。battle_end 结算界面左下角同样有表情气泡
# (battle_emote 会命中 ~0.90),故必须把 battle_end 排在 in_battle 之前,先用底部"确定"键
# 把结算界面区分出来;真正对局内 battle_end 模板只有 ~0.16,不会误判。
SCENES: dict[str, Scene] = {
    "main_menu": Scene(name="main_menu", markers=["battle_tab"]),
    "matchmaking": Scene(name="matchmaking", markers=["matchmaking"]),
    "battle_end": Scene(name="battle_end", markers=["battle_end"]),
    "in_battle": Scene(name="in_battle", markers=["battle_emote"]),
}

# —— 导航边:在某场景点击某模板 -> 目标场景 ——
# 点"对战"后先进 matchmaking(搜索对手),匹配到再进 in_battle;结算后点"确定"回主菜单。
EDGES: list[tuple[str, str, str]] = [
    ("main_menu", "main_battle_button", "matchmaking"),
    ("battle_end", "battle_end", "main_menu"),
]
