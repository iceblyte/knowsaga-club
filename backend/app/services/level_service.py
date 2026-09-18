"""等级与头衔（方案设计 §8.2）。

## 曲线

```
门槛(1) = 0
门槛(n) = 400 + 800 × (n − 2)      (n ≥ 2)
→ 0, 400, 1200, 2000, 2800, 3600, …
```

这组数字不是拍的 —— 它要能**精确对上原型**：

> 原型 04·1：`Lv.3` 区间 `[1200, 2000)`，用户 1280 →
> 本级进度 `1280 / 2000`，「距离 Lv.4 还差 720」

## 两个刻意的口径

**1. 进度的分子是「累计 XP」，分母是「下一级门槛」。**
不是 `(xp − 本级门槛) / 本级区间`。原因：只有这个口径下「还差 720」
才等于 `2000 − 1280`。用区间口径会算出 `(1280−1200)/800 = 10%`，
和原型那句「距离 Lv.4 还差 720 XP」自相矛盾。

> 原型自身有一处数字打架：上方进度条写 `1280 / 2000`，同屏三宫格却写
> 「累计 XP 1840」。**裁决**：统一按进度条口径，三宫格也显示 1280。

**2. 等级封顶。**
曲线是发散的，不封顶的话一个异常大的 `xp_total`（导入数据、算错累加）
会让等级涨到几百，头衔表与进度条分母都失去意义。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 等级上限。99 级对应门槛 78 800 XP，远超本项目任何真实可达范围，
#: 因此它只是一个「防止越界」的护栏，不是玩法上的天花板。
MAX_LEVEL = 99

#: 头衔阶梯：(上限等级, 头衔)。按顺序匹配第一个 `level <= 上限` 的项。
#: 原型只出现过「见习冒险者」，其余四档为自拟（方案 §8.2）。
_TITLE_BANDS: tuple[tuple[int, str], ...] = (
    (2, "见习冒险者"),
    (4, "初级冒险者"),
    (6, "资深冒险者"),
    (8, "史诗冒险者"),
    (MAX_LEVEL, "传说冒险者"),
)

_BASE_THRESHOLD = 400
_STEP = 800


@dataclass(frozen=True, slots=True)
class LevelProgress:
    """一次等级换算的全部结果，供界面直接取用。"""

    level: int
    title: str
    #: 累计经验（进度条分子）
    xp_total: int
    #: 下一级门槛（进度条分母）
    next_threshold: int
    #: 距下一级还差多少
    xp_to_next: int
    #: 进度百分比（0–100 整数，直接当 CSS 宽度用）
    percent: int


def level_threshold(level: int) -> int:
    """升到 `level` 所需的累计 XP。`level <= 1` 恒为 0（起点）。

    不抛异常是刻意的：调用方经常需要 `threshold(level + 1)`，
    在 `level` 可能为 0 的边界上多做一次判断没有价值。
    """
    n = int(level)
    if n <= 1:
        return 0
    return _BASE_THRESHOLD + _STEP * (n - 2)


def level_for_xp(xp: int) -> int:
    """累计 XP 对应的等级（满足 `threshold(level) <= xp` 的最大 level）。"""
    value = max(0, int(xp))
    if value < _BASE_THRESHOLD:
        return 1
    # 闭式解：threshold(n) = 400 + 800(n−2) ≤ xp  →  n ≤ 2 + (xp−400)/800
    return min(MAX_LEVEL, 2 + (value - _BASE_THRESHOLD) // _STEP)


def level_title(level: int) -> str:
    """等级对应的头衔。"""
    n = max(1, int(level))
    for upper, title in _TITLE_BANDS:
        if n <= upper:
            return title
    return _TITLE_BANDS[-1][1]  # pragma: no cover - n 已被 MAX_LEVEL 覆盖


def level_progress(xp: int) -> LevelProgress:
    """一次算出等级、头衔、进度与差额。"""
    value = max(0, int(xp))
    level = level_for_xp(value)

    if level >= MAX_LEVEL:
        # 封顶后分母取自身：进度恒 100%，不出现「还差多少」的悬空文案
        return LevelProgress(
            level=level,
            title=level_title(level),
            xp_total=value,
            next_threshold=value,
            xp_to_next=0,
            percent=100,
        )

    next_threshold = level_threshold(level + 1)
    return LevelProgress(
        level=level,
        title=level_title(level),
        xp_total=value,
        next_threshold=next_threshold,
        xp_to_next=max(0, next_threshold - value),
        percent=min(100, round(value * 100 / next_threshold)) if next_threshold > 0 else 100,
    )
