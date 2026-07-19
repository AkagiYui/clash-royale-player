"""场景与导航图定义(数据)—— 支持多设备(profile)。

- Template:所有可匹配元素(场景标志 / 可点击按钮),坐标基于**各自 profile 的参考画布**。
- Scene  :每个场景由一组标志模板判定(默认需全部出现)。
- Edge   :导航边 (from_scene, click_template, to_scene) —— 在 from 场景点击某模板到达 to。
- SceneProfile:一台(或一类)设备的完整 CV 配置 = 参考画布尺寸 + 素材目录 + 模板集。

多设备设计
----------
不同设备分辨率/宽高比差异大(平板 2400x3392≈0.71,手机 1264x2780≈0.45),**不能**共用一
张参考画布强行 resize——会变形导致模板匹配失效。故每台设备一个 profile:各自的参考画布
(通常取该设备 native 分辨率或其等比缩小)与各自裁剪的模板集(assets/scenes*/)。
`select_profile(w, h)` 按设备 native 分辨率挑 profile;SceneController 在 open() 时据此绑定。

场景图(SCENES/EDGES)两设备**共用**(游戏逻辑相同),只有模板坐标/素材按 profile 不同。
新增一台设备:截该机各场景图、裁模板到 assets/scenes_<x>/、加一个 _build_profile 即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from crplayer.scene.template import Template

_ASSETS = Path(__file__).resolve().parents[3] / "assets"


@dataclass
class Scene:
    name: str
    markers: list[str]              # 判定该场景的模板名
    require_all: bool = True        # True=全部命中才算此场景;False=任一命中

    _extra: dict = field(default_factory=dict)


@dataclass
class SceneProfile:
    """一台/一类设备的 CV 配置。ref_* 为该 profile 的参考画布;native_* 为设备原生分辨率
    (用于 select_profile 匹配)。templates 已注入 ref_size/assets_dir。"""

    name: str
    ref_width: int
    ref_height: int
    native_width: int
    native_height: int
    templates: dict[str, Template]
    scenes: dict[str, "Scene"]
    edges: list[tuple[str, str, str]]

    @property
    def aspect(self) -> float:
        return self.native_width / self.native_height


# —— 场景图:两设备共用(仅模板坐标/素材随 profile 变)——
# 顺序敏感:current_scene() 取首个命中的场景。battle_end 结算界面左下角同样有表情气泡
# (battle_emote 会命中),故必须把 battle_end 排在 in_battle 之前,先用底部"确定"键区分。
_SCENES: dict[str, Scene] = {
    "main_menu": Scene(name="main_menu", markers=["battle_tab"]),
    "matchmaking": Scene(name="matchmaking", markers=["matchmaking"]),
    "battle_end": Scene(name="battle_end", markers=["battle_end"]),
    "in_battle": Scene(name="in_battle", markers=["battle_emote"]),
}

# —— 导航边:点"对战"进 matchmaking(搜索对手),结算后点"确定"回主菜单 ——
_EDGES: list[tuple[str, str, str]] = [
    ("main_menu", "main_battle_button", "matchmaking"),
    ("battle_end", "battle_end", "main_menu"),
]


def _build_profile(
    name: str,
    ref_wh: tuple[int, int],
    native_wh: tuple[int, int],
    assets_subdir: str,
    template_defs: dict[str, dict],
) -> SceneProfile:
    """把模板定义注入 ref_size/assets_dir,组装成 profile。scenes/edges 共用。"""
    ref_w, ref_h = ref_wh
    assets_dir = _ASSETS / assets_subdir
    templates = {
        tname: Template(name=tname, ref_size=(ref_w, ref_h), assets_dir=assets_dir, **kw)
        for tname, kw in template_defs.items()
    }
    return SceneProfile(
        name=name, ref_width=ref_w, ref_height=ref_h,
        native_width=native_wh[0], native_height=native_wh[1],
        templates=templates, scenes=_SCENES, edges=_EDGES,
    )


# ============================ 平板 profile(OPD2413)============================
# 参考画布 904x1280 = native 2400x3392 经 scrcpy max_size1280 等比缩小;既有模板即基于此。
_TABLET_DEFS: dict[str, dict] = {
    # 底部导航栏"对战"标签(交叉金剑):主菜单**不变**元素,用作 main_menu 稳定判定标志。
    "battle_tab": dict(file="battle_tab.png", area=(388, 1185, 472, 1270), similarity=0.85),
    # 中央黄色"对战"按钮:作**点击目标**(位置固定)。多变体容忍活动/每日奖励皮肤变化。
    "main_battle_button": dict(
        file=["main_battle_button_bonus.png", "main_battle_button_plain.png"],
        area=(354, 958, 565, 1045), click=(459, 1001), similarity=0.85,
    ),
    "battle_emote": dict(file="battle_emote.png", area=(80, 1035, 200, 1130), similarity=0.80),
    "matchmaking": dict(file="matchmaking.png", area=(90, 143, 339, 219), similarity=0.80),
    "battle_end": dict(file="battle_end.png", area=(368, 1088, 537, 1160), similarity=0.82),
}

# ============================ 手机 profile(PKR110)=============================
# 参考画布取该机 native 1264x2780(adb 截图同分辨率,免缩放);模板从本机各场景图裁剪。
_PHONE_DEFS: dict[str, dict] = {
    "battle_tab": dict(file="battle_tab.png", area=(525, 2620, 720, 2712), similarity=0.82),
    "main_battle_button": dict(
        file=["main_battle_button_plain.png"],
        area=(555, 2205, 795, 2345), click=(545, 2275), similarity=0.80,
    ),
    "battle_emote": dict(file="battle_emote.png", area=(25, 2435, 170, 2575), similarity=0.78),
    "matchmaking": dict(file="matchmaking.png", area=(75, 355, 780, 520), similarity=0.78),
    "battle_end": dict(file="battle_end.png", area=(500, 2240, 700, 2350), click=(630, 2305),
                       similarity=0.80),
}

PROFILES: dict[str, SceneProfile] = {
    "tablet": _build_profile("tablet", (904, 1280), (2400, 3392), "scenes", _TABLET_DEFS),
    "phone": _build_profile("phone", (1264, 2780), (1264, 2780), "scenes_phone", _PHONE_DEFS),
}

DEFAULT_PROFILE = PROFILES["tablet"]


def select_profile(width: int, height: int) -> SceneProfile:
    """按设备 native 分辨率挑 profile:先精确匹配,再取宽高比最接近者(兜底)。"""
    for p in PROFILES.values():
        if (p.native_width, p.native_height) == (width, height):
            return p
    aspect = width / height if height else 0.0
    best = min(PROFILES.values(), key=lambda p: abs(p.aspect - aspect))
    return best


# —— 向后兼容:旧代码直接 import TEMPLATES/SCENES/EDGES 时,取平板 profile ——
TEMPLATES: dict[str, Template] = DEFAULT_PROFILE.templates
SCENES: dict[str, Scene] = DEFAULT_PROFILE.scenes
EDGES: list[tuple[str, str, str]] = DEFAULT_PROFILE.edges
