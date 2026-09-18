"""服务端判题与计分（方案 §8.1）。

## 这些用例为什么从共享文件里读

判题**有两份实现**：前端 `utils/scoring.ts`（答题时的即时反馈）与服务端
`services/scoring.py`（交卷后的权威结算）。两处必须是同一套规则，否则会出现
「答题时显示答对、结算页少给 40 XP」这种最难解释、也最伤信任的 bug。

所以规则放在 `shared/scoring-cases.json`，前后端各自断言同一份数据：

| 消费者 | 命令 |
|---|---|
| 本文件 | `pytest tests/test_scoring.py` |
| `frontend/scripts/check_scoring_parity.mjs` | `node frontend/scripts/check_scoring_parity.mjs` |

任何一边改了实现而没同步，另一边的检查就会红。

## 最要命的那个差异：`.5` 怎么进位

`Math.round(12.5) === 13`（向 +∞），而 Python 内置 `round(12.5) === 12`（银行家舍入）。
`accuracy = 1/8 → 12.5`、`percentile = 5 × 0.9 → 4.5` 都会踩到。
因此 `scoring.js_round` 刻意手写 `floor(x + 0.5)`，共享用例里也专门放了这几条边界。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services import scoring

#: 仓库根目录：tests/ -> backend/ -> 仓库根
CASES_PATH = Path(__file__).resolve().parents[2] / "shared" / "scoring-cases.json"


def _load() -> dict[str, Any]:
    if not CASES_PATH.is_file():  # pragma: no cover - 文件缺失属于配置错误
        pytest.fail(f"共享用例文件不存在：{CASES_PATH}")
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


CASES = _load()


def _cases(group: str) -> list[dict[str, Any]]:
    items = CASES.get(group) or []
    assert items, f"共享用例 {group} 是空的"
    return items


def _ids(group: str) -> list[str]:
    return [item["name"] for item in _cases(group)]


# -----------------------------------------------------------------------------
# 判题
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("case", _cases("grade_cases"), ids=_ids("grade_cases"))
def test_grade_cases_match_shared_contract(case: dict[str, Any]) -> None:
    result = scoring.grade_answer(case["type"], case["answer"], case["selected"])

    assert result.outcome == case["expected"]["outcome"], case["name"]
    assert result.earned_xp == case["expected"]["earned_xp"], case["name"]
    assert result.max_xp == case["expected"]["max_xp"], case["name"]


def test_grade_case_count() -> None:
    """条数本身也是契约的一部分：有人删掉边界用例时这条会红。

    16 = 单选 6 + 多选 7 + 判断 3。
    """
    single = [c for c in _cases("grade_cases") if c["type"] == "single"]
    multiple = [c for c in _cases("grade_cases") if c["type"] == "multiple"]
    judge = [c for c in _cases("grade_cases") if c["type"] == "judge"]

    assert (len(single), len(multiple), len(judge)) == (6, 7, 3)
    assert len(_cases("grade_cases")) == 16


# -----------------------------------------------------------------------------
# 汇总口径
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("case", _cases("accuracy_cases"), ids=_ids("accuracy_cases"))
def test_accuracy_cases(case: dict[str, Any]) -> None:
    assert scoring.accuracy_of(case["correct_count"], case["total_count"]) == case["expected"]


@pytest.mark.parametrize("case", _cases("coins_cases"), ids=_ids("coins_cases"))
def test_coins_cases(case: dict[str, Any]) -> None:
    assert scoring.coins_for(case["xp"]) == case["expected"]


@pytest.mark.parametrize("case", _cases("percentile_cases"), ids=_ids("percentile_cases"))
def test_percentile_cases(case: dict[str, Any]) -> None:
    assert scoring.percentile_for(case["accuracy"]) == case["expected"]


# -----------------------------------------------------------------------------
# 不放进共享文件的部分：Python 侧的类型与边界细节
# -----------------------------------------------------------------------------
def test_max_xp_table() -> None:
    assert scoring.max_xp_of("single") == 40
    assert scoring.max_xp_of("multiple") == 60
    assert scoring.max_xp_of("judge") == 20


def test_unknown_question_type_is_rejected() -> None:
    """未知题型必须炸掉，而不是悄悄给 0 分。

    给 0 分会让一道 40 分的题在结算里凭空消失 —— 用户看到的是「我明明答对了」，
    而库里多了一条错误的账。宁可 500。
    """
    with pytest.raises(KeyError):
        scoring.max_xp_of("essay")


def test_js_round_matches_javascript() -> None:
    """锁定 `.5` 的进位方向，避免有人「顺手」改回内置 round。"""
    assert scoring.js_round(12.5) == 13
    assert scoring.js_round(4.5) == 5
    assert scoring.js_round(13.5) == 14
    assert scoring.js_round(80.0) == 80
    assert scoring.js_round(0.0) == 0
    # 内置 round 在这里给 12 —— 正是要避免的那个结果
    assert round(12.5) == 12


def test_selected_is_deduplicated_and_sorted() -> None:
    """判题结果里的 selected 要**归一化**后再落库。

    原样存客户端传来的数组会把 `["A","A"]` 写进 answers.selected，
    报告链与卷轴详情页都要各自再洗一遍数据。
    """
    result = scoring.grade_answer("multiple", ["A", "C"], ["C", "A", "C"])

    assert list(result.selected) == ["A", "C"]
    assert list(result.answer) == ["A", "C"]


def test_selected_accepts_empty_and_unknown_values() -> None:
    empty = scoring.grade_answer("single", ["A"], [])
    assert empty.outcome == "wrong"
    # 未知键留在 selected 里（便于「你选了什么」的回放），但不影响判定
    unknown = scoring.grade_answer("single", ["A"], ["Z"])
    assert list(unknown.selected) == ["Z"]
    assert unknown.outcome == "wrong"


def test_partial_xp_is_floor_of_half() -> None:
    """部分正确的 30 分是 `floor(60 × 0.5)`，不是「按选对项数比例」。

    口径已定（方案 §8.1）：只在多选题、非空真子集时给固定 50%，
    与选对了几项无关。这条锁住「不要顺手改成按比例」。
    """
    one_of_two = scoring.grade_answer("multiple", ["A", "C"], ["A"])
    one_of_three = scoring.grade_answer("multiple", ["A", "C", "D"], ["A"])

    assert one_of_two.earned_xp == one_of_three.earned_xp == 30
