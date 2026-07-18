"""结构化游戏状态的数据模型。

设计目标:感知层输出干净、可 JSON 序列化的状态,决策层完全不碰像素。
单位的状态维度直接借鉴 KataCR 的标注思路——很多"单位当前处于什么状态"的问题
在检测这一步就解决,不靠跨帧硬猜。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Side(StrEnum):
    """阵营。"""

    ALLY = "ally"
    ENEMY = "enemy"
    UNKNOWN = "unknown"


class Action(StrEnum):
    """单位动作状态。"""

    IDLE = "idle"
    WALK = "walk"
    ATTACK = "attack"
    DEPLOY = "deploy"
    FROZEN = "frozen"
    DASH = "dash"
    UNKNOWN = "unknown"


class Phase(StrEnum):
    """游戏阶段。"""

    UNKNOWN = "unknown"
    BATTLE = "battle"      # 对战中
    OVERTIME = "overtime"  # 加时
    RESULT = "result"      # 结算


@dataclass
class BBox:
    """归一化虚拟画布上的像素包围盒(左上/右下),坐标范围 [0, 1]。"""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


@dataclass
class GridPos:
    """战场逻辑网格坐标(第 col 列、第 row 行),由塔锚点反推,而非像素。"""

    col: float
    row: float


@dataclass
class Unit:
    """场上一个检测目标(单位/建筑/法术效果)。

    坐标:bbox 为归一化像素框,grid 为逻辑网格坐标(可选)。
    状态维度参考 KataCR:阵营 / 动作 / 护盾蓄力 / 可见性 / 暴怒减速 / 治疗复制 /
    地空 / 单位建筑。
    """

    # —— 身份与位置 ——
    name: str                       # unit name(非 card name,便于同卡复用去重)
    bbox: BBox
    confidence: float = 0.0
    grid: GridPos | None = None
    side: Side = Side.UNKNOWN

    # —— 动态状态维度 ——
    action: Action = Action.UNKNOWN
    shield: bool = False            # 护盾 / 蓄力
    rage: bool = False              # 暴怒
    slow: bool = False              # 减速
    healing: bool = False           # 被治疗 / 复制标记
    visible: bool = True

    # —— 静态常量维度 ——
    is_air: bool = False            # 空中 / 地面
    is_building: bool = False       # 建筑 / 单位

    # —— 血量(规则法:血条像素比例,范围 [0,1];未知为 None)——
    hp_ratio: float | None = None

    # —— 跨帧关联(阶段二填充,当前为占位)——
    track_id: int | None = None
    vx: float | None = None
    vy: float | None = None


@dataclass
class Card:
    """一张手牌槽。"""

    name: str = "unknown"
    confidence: float = 0.0
    ready: bool = True              # 圣水是否足够部署(由决策层配合圣水判断,占位默认 True)
    elixir_cost: int | None = None


@dataclass
class TowerState:
    """一座塔的血量状态。"""

    name: str                       # king / left_princess / right_princess
    side: Side
    hp_ratio: float | None = None   # 规则法血条比例 [0,1]
    hp: int | None = None           # 若能 OCR 到绝对数值则填
    activated: bool = False         # 国王塔是否已激活


@dataclass
class GameState:
    """一帧感知输出的完整结构化状态。"""

    timestamp: float                # 采集该帧的时间戳(秒),供延迟补偿使用
    frame_id: int = 0
    phase: Phase = Phase.UNKNOWN

    # 圣水(0~10,可为小数)
    elixir: float | None = None

    # 手牌:4 张在手 + 1 张下一张
    hand: list[Card] = field(default_factory=list)
    next_card: Card | None = None

    # 塔血量
    towers: list[TowerState] = field(default_factory=list)

    # 场上单位
    units: list[Unit] = field(default_factory=list)

    # 计时器 / 比分(OCR;不可用时为 None)
    time_left: int | None = None    # 剩余秒数
    score_ally: int | None = None
    score_enemy: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
