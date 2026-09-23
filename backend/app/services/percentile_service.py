"""百分位的**真实用户池**查询。

## 它存在的理由

`attempts.percentile` 原本是一个演示值（`clamp(round(accuracy × 0.9), 5, 95)`），
界面上必须挂一句「（演示数据）」才不算说假话 —— 而把「这是假数据」印在用户的
成绩单上，比对不给这个数字更糟。2026-09-23 起改为按**真实社团成员**算，
这个模块就是那个池子的唯一入口。

## 池子的定义（与 `scoring.pool_percentile` 是同一份口径的两端）

| 问题 | 答案 | 为什么 |
|---|---|---|
| 池子里是谁 | **其他**冒险者（不含本人） | 界面那句是「超过**社团里** X% 的冒险者」，比自己不算社团 |
| 每人几个样本 | 1 个：他的**最佳正确率** | 分母是人不是记录数，否则刷 100 局的用户能拖动整个分位 |
| 算不算已删除的记录 | **算** | FR-B5：删除「仅移除记录，不影响整体统计」。若这里过滤 `deleted_at`，删一条旧记录就会改掉分位数 —— 正是那条需求禁止的事（同 `03_attempts_deleted_at.sql` 的说明） |
| 算不算未完成的一局 | 不算（`status='finished'`） | 「最佳成绩」不该由一局中途退出产生 |
| 池子为空 | 返回 `None` | 见 `scoring.pool_percentile` 的说明：宁可说「还没有其他人」，不编数字 |

## 为什么单独一个模块，而不塞进 `scoring.py`

`scoring.py` 是**纯函数**：同一组输入永远同一组输出，两端（TS/Python）逐位对齐，
契约在 `shared/scoring-cases.json`。百分位现在依赖**库里的数据**，
放进那个文件会让「纯函数」这条边界立刻失效（也就没法再写共享用例）。
所以：**查库在这里，算数在 `scoring.pool_percentile`**。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import Attempt
from app.services import scoring


@dataclass(frozen=True, slots=True)
class PoolPercentile:
    """一次分位计算的结果。

    `percentile` 为 `None` = 池子里没有可比的人；`pool_size` 是那一刻**真实的**
    可比人数，界面上的说明文案直接用它（「按社团里 N 位冒险者的最佳正确率计算」）。
    把人数一起返回而不是让界面另查一次：两者必须是同一次快照，
    否则会出现「按 8 人计算」配一个按 7 人算出来的分位。
    """

    percentile: int | None
    pool_size: int


def others_best_accuracy(session: Session, *, exclude_user_id: int) -> list[int]:
    """除 `exclude_user_id` 外，每位冒险者的最佳正确率（每人一条）。

    没答过题的账号不会出现在结果里（`GROUP BY` 不会有空组），
    所以 `len(结果)` 就等于「有成绩的社团成员数」。
    """
    rows = session.execute(
        select(func.max(Attempt.accuracy))
        .where(
            Attempt.user_id != int(exclude_user_id),
            Attempt.status == "finished",
        )
        .group_by(Attempt.user_id)
    ).all()
    return [int(row[0]) for row in rows if row[0] is not None]


def for_accuracy(session: Session, *, user_id: int, accuracy: int) -> PoolPercentile:
    """算某位用户、某个正确率在真实池子里的分位。"""
    bests = others_best_accuracy(session, exclude_user_id=user_id)
    return PoolPercentile(
        percentile=scoring.pool_percentile(accuracy, bests),
        pool_size=len(bests),
    )
