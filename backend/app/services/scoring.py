"""服务端判题与计分 —— **权威口径**。

## 为什么服务端要重判一遍

答题时前端已经判过一次（为了「答对后立刻变绿」不被网络延迟绑架，这条决策保留）。
但结算必须由服务端重判：前端上报的只是**逐题选择**，不是分数。
否则档案里的等级、累计 XP、正确率全部可被篡改，看板画出来的图也就没有权威来源
（方案 §6.5）。

于是同一套规则有两份实现：

| 实现 | 位置 | 用途 |
|---|---|---|
| TS | `frontend/src/utils/scoring.ts` | 答题时的即时反馈 |
| Python | 本文件 | 交卷后的权威结算 |

两处必须逐条一致，契约在 `shared/scoring-cases.json`，两边各有测试断言它。

## 三个容易写错的点

**1. `.5` 的进位方向。**
JS 的 `Math.round` 遇 `.5` 向 +∞ 进位，Python 内置 `round` 是银行家舍入。
`1/8 = 12.5`、`5 × 0.9 = 4.5` 都会踩到，于是必须用 `js_round`。

**2. 多选的判定顺序。**
必须**先判「有没有错选」**。若先判「是不是答案的子集」，那么
「从 4 个选项里蒙 1 个正确项」也会落进「非空真子集」拿到 30 分。

**3. 数值必须是整数。**
金额与分数一律整数，不引入浮点误差（方案 §5.0）。因此金币是 `floor`，
`earned_xp` 是 `floor(max_xp × 0.5)`，都不是浮点运算的结果直接外泄。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

QuestionType = Literal["single", "multiple", "judge"]
Outcome = Literal["correct", "partial", "wrong"]

#: 各题型满分（方案 §8.1）
MAX_XP: dict[str, int] = {
    "single": 40,
    "multiple": 60,
    "judge": 20,
}

#: 多选题部分正确的固定比例。**不按选对项数比例** —— 口径已定，别顺手改。
MULTIPLE_PARTIAL_RATIO = 0.5

#: 金币换算率：`coins = floor(XP × 0.18)`
COIN_RATE = 0.18

#: 演示用百分位的天花板与地板（方案 §9.4）
PERCENTILE_FLOOR = 5
PERCENTILE_CEIL = 95


@dataclass(frozen=True, slots=True)
class GradedAnswer:
    """一道题的判定结果。

    `selected` 与 `answer` 都是**归一化后**的（去重 + 排序）：
    原样落库会把 `["A","A"]` 这种脏数据写进 `answers.selected`，
    于是报告链和卷轴详情页都要各自再洗一遍。
    """

    outcome: Outcome
    earned_xp: int
    max_xp: int
    selected: tuple[str, ...]
    answer: tuple[str, ...]


def js_round(value: float) -> int:
    """与 JavaScript `Math.round` 同语义的取整。

    为什么不用内置 `round`：它是银行家舍入（`round(12.5) == 12`），
    而前端是 `Math.round(12.5) === 13`。同一个正确率在两个地方差 1 个百分点，
    用户只会认为结算页算错了。`floor(x + 0.5)` 就是 `Math.round` 在正数上的定义。
    """
    return math.floor(value + 0.5)


def max_xp_of(question_type: str) -> int:
    """题型满分。

    Raises:
        KeyError: 未知题型。**刻意抛错而不返回 0** —— 给 0 分会让一道 40 分的题
            在结算里凭空消失，用户看到「我明明答对了」而库里多了一条错账。
    """
    return MAX_XP[question_type]


def _normalize(keys: Iterable[str]) -> tuple[str, ...]:
    """去重并排序（`sorted` 与 JS `Array.prototype.sort()` 对 ASCII 选项键结果一致）。"""
    return tuple(sorted({str(key) for key in keys}))


def grade_answer(
    question_type: str,
    answer: Sequence[str],
    selected: Sequence[str],
) -> GradedAnswer:
    """判定一道题。

    与 `frontend/src/utils/scoring.ts` 的 `gradeQuestion` 逐条对齐：

    ```
    多选：1. 含错选          → 0
          2. 与答案完全一致   → 满分
          3. 非空真子集       → floor(满分 × 0.5)
          4. 空               → 0
    单选/判断：去重后恰好 1 项且该键是正确答案 → 满分，否则 0
    ```

    单选/判断的「去重后恰好 1 项」这条不能省：`["A","A"]` 去重后是 1 项（算对），
    而 `["A","B"]` 是 2 项（算错）—— 用户在单选里误点了两次不同选项，
    后端必须与前端一样判错。
    """
    max_xp = max_xp_of(question_type)
    correct = _normalize(answer)
    picked = _normalize(selected)
    answer_set = set(correct)

    if question_type == "multiple":
        has_wrong_pick = any(key not in answer_set for key in picked)
        if has_wrong_pick:
            outcome: Outcome = "wrong"
            earned = 0
        elif len(picked) == len(correct) and answer_set.issubset(set(picked)):
            # 走到这里蕴含 picked ⊆ answer（上面已排除含错选），故为完全一致
            outcome = "correct"
            earned = max_xp
        elif picked:
            outcome = "partial"
            earned = math.floor(max_xp * MULTIPLE_PARTIAL_RATIO)
        else:
            outcome = "wrong"
            earned = 0
    else:
        is_correct = len(picked) == 1 and picked[0] in answer_set
        outcome = "correct" if is_correct else "wrong"
        earned = max_xp if is_correct else 0

    return GradedAnswer(
        outcome=outcome,
        earned_xp=int(earned),
        max_xp=int(max_xp),
        selected=picked,
        answer=correct,
    )


def accuracy_of(correct_count: int, total_count: int) -> int:
    """正确率（0–100 整数）。题量为 0 时给 0，不做除法。

    分母是**题量**而不是已作答题数：中途退出的一局里，没作答的题就是没拿分，
    正确率不该因为「少答了几题」而变好看。
    """
    if total_count <= 0:
        return 0
    return js_round(correct_count * 100 / total_count)


def coins_for(xp: int) -> int:
    """`coins = floor(XP × 0.18)`。**向下取整，不四舍五入** —— 25 XP 给 4 不是 5。"""
    return math.floor(max(0, int(xp)) * COIN_RATE)


def percentile_for(accuracy: int) -> int:
    """演示用百分位：`clamp(round(accuracy × 0.9), 5, 95)`。

    没有真实用户池，这是正确率的单调映射（方案 §9.4），**界面必须标注是演示值**。
    上限 95 在 `accuracy ∈ [0, 100]` 下不可达（最大 90），保留它是为了让这条
    公式与方案原文逐字一致、将来接入真实分位时替换实现即可。
    """
    value = js_round(max(0, min(100, int(accuracy))) * 0.9)
    return max(PERCENTILE_FLOOR, min(PERCENTILE_CEIL, value))


#: 百分位的文字档位。区间取「左闭右开」并在最低档兜底，所以任意 0–100 都有归属，
#: 不存在「算出 72 却不知道该显示什么」的缝隙。
#:
#: 原型 03 第 1 屏固定了 `72% → 「中上」` 这一种情况，其余档位是按设计系统的
#: 语义色梯度补的（与 `AccuracyRing` 的绿 / 金 / 红三档同源）。
#:
#: ⚠️ 这套档位与 `percentile_for` 是**同一件事的两半**：都建立在「没有真实用户池」
#: 这个前提上。将来接入真实分位时，两者必须一起替换 —— 只换数值不换文案，
#: 会出现「超过了 3% 的人 · 优秀」这种自相矛盾的组合。
_PERCENTILE_BANDS: tuple[tuple[int, str], ...] = (
    (90, "顶尖"),
    (75, "优秀"),
    (50, "中上"),
    (25, "中游"),
)


def percentile_label_for(percentile: int) -> str:
    """把百分位映射成界面上的档位文字（原型 03 第 1 屏的胶囊）。

    放在服务端而不是前端：这个胶囊与百分位是同一个演示口径的产物，
    分开两处实现迟早会出现「数字说领先、文案说落后」。
    """
    value = max(0, min(100, int(percentile)))
    for threshold, label in _PERCENTILE_BANDS:
        if value >= threshold:
            return label
    return "起步"
