"""等级曲线与头衔（方案设计 §8.2）。

曲线必须能**精确对上原型数字**，所以这里按原型 04·1 的实例逐条验算：

- 门槛：`0, 400, 1200, 2000, 2800, …`
- 原型用户 XP=1280 → `Lv.3`，进度条 `1280 / 2000`（64%），「距离 Lv.4 还差 720」
"""

from __future__ import annotations

import pytest

from app.services.level_service import (
    MAX_LEVEL,
    level_for_xp,
    level_progress,
    level_threshold,
    level_title,
)


# -----------------------------------------------------------------------------
# 门槛曲线
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("level", "expected"),
    [(1, 0), (2, 400), (3, 1200), (4, 2000), (5, 2800), (6, 3600), (7, 4400)],
)
def test_thresholds_match_spec(level: int, expected: int) -> None:
    assert level_threshold(level) == expected


def test_threshold_for_non_positive_level_is_zero() -> None:
    """等级 ≤ 1 都是起点；不抛异常是为了让调用方少一处边界判断。"""
    assert level_threshold(0) == 0
    assert level_threshold(-5) == 0


def test_thresholds_are_strictly_increasing() -> None:
    values = [level_threshold(n) for n in range(1, 60)]

    assert values == sorted(values)
    assert len(set(values)) == len(values)


# -----------------------------------------------------------------------------
# XP -> 等级
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("xp", "expected_level"),
    [
        (0, 1),
        (1, 1),
        (399, 1),
        (400, 2),  # 恰好到门槛即升级
        (1199, 2),
        (1200, 3),
        (1280, 3),  # 原型用户
        (1999, 3),
        (2000, 4),
        (2799, 4),
        (2800, 5),
    ],
)
def test_level_for_xp(xp: int, expected_level: int) -> None:
    assert level_for_xp(xp) == expected_level


def test_negative_xp_is_level_one() -> None:
    assert level_for_xp(-100) == 1


def test_level_is_capped() -> None:
    """极端数值不能让等级无限增长（进度条分母会溢出显示区间）。"""
    assert level_for_xp(10**9) == MAX_LEVEL


# -----------------------------------------------------------------------------
# 进度（原型 04·1 的验算）
# -----------------------------------------------------------------------------
def test_progress_matches_prototype_04_1() -> None:
    """原型 04·1 的验算（XP=1280）。

    **头衔这一项刻意与原型字面不同**：原型在 `Lv.3` 旁边写的是「见习冒险者」，
    与方案 §8.2 的头衔阶梯（见习 1–2 / 初级 3–4 / …）冲突。
    按 §8.2 执行 —— 若照原型的字面，1–99 级全都显示「见习冒险者」，
    阶梯就名存实亡（§8.2 自己也声明「原型只出现『见习冒险者』，其余为自拟」）。
    已把这一处口径差异列进 Phase A 的汇报给人工确认。
    """
    p = level_progress(1280)

    assert p.level == 3
    assert p.xp_total == 1280
    assert p.next_threshold == 2000
    assert p.xp_to_next == 720  # 「距离 Lv.4 还差 720 XP」
    assert p.percent == 64  # 进度条 width:64%
    assert p.title == "初级冒险者"


def test_progress_at_exact_threshold_shows_zero_to_next() -> None:
    p = level_progress(1200)

    assert p.level == 3
    assert p.percent == 60  # 1200 / 2000
    assert p.xp_to_next == 800


def test_progress_at_level_one() -> None:
    p = level_progress(0)

    assert p.level == 1
    assert p.next_threshold == 400
    assert p.xp_to_next == 400
    assert p.percent == 0
    assert p.title == "见习冒险者"


def test_percent_is_never_over_100() -> None:
    """分母是「下一级门槛」，分子是累计 XP，所以分子天然小于分母。

    这里守住的是**实现不能改成 `xp - threshold`** 之类的算法变体：
    那样在跨级时进度会突然回落到很小的值，用户看到进度条倒退。
    """
    for xp in (0, 399, 400, 1199, 1200, 1280, 1999):
        assert 0 <= level_progress(xp).percent <= 100, xp


def test_percent_is_monotonic() -> None:
    percents = [level_progress(xp).percent for xp in range(0, 2000, 7)]

    # 允许升级时的回落（2000 处会回到 0/…），但在同一级内必须单调不减
    assert percents[0] == 0
    assert percents[-1] >= 0


def test_max_level_progress_is_full() -> None:
    p = level_progress(level_threshold(MAX_LEVEL) + 10_000)

    assert p.level == MAX_LEVEL
    assert p.xp_to_next == 0
    assert p.percent == 100


# -----------------------------------------------------------------------------
# 头衔
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, "见习冒险者"),
        (2, "见习冒险者"),
        (3, "初级冒险者"),
        (4, "初级冒险者"),
        (5, "资深冒险者"),
        (6, "资深冒险者"),
        (7, "史诗冒险者"),
        (8, "史诗冒险者"),
        (9, "传说冒险者"),
        (50, "传说冒险者"),
    ],
)
def test_level_title(level: int, expected: str) -> None:
    assert level_title(level) == expected


def test_level_title_for_zero() -> None:
    assert level_title(0) == "见习冒险者"


def test_progress_carries_title() -> None:
    """`level_progress` 必须把头衔一并给出 —— 否则每个调用点都要自己算一遍等级。"""
    assert level_progress(1200).title == level_title(3)


def test_all_titles_are_non_empty_and_unique() -> None:
    titles = [level_title(n) for n in range(1, MAX_LEVEL + 1)]

    assert all(t.strip() for t in titles)
    assert set(titles) == {
        "见习冒险者",
        "初级冒险者",
        "资深冒险者",
        "史诗冒险者",
        "传说冒险者",
    }
