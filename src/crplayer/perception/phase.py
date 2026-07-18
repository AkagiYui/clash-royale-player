"""游戏阶段判断 —— 简单分类(对战中/加时/结算)。

MVP 用启发式:能读到圣水条+计时器基本判为对战中;计时器进入个位数区间
可粗判加时。后续可替换为小型分类器(架构文档 1.1)。
"""

from __future__ import annotations

from crplayer.state.schema import Phase


def classify_phase(elixir: float | None, time_left: int | None) -> Phase:
    if elixir is None:
        return Phase.UNKNOWN
    if time_left is not None and time_left <= 0:
        return Phase.OVERTIME
    return Phase.BATTLE
