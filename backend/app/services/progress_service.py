"""一局结束后的**自我比较**判定。

## 它替换掉了什么

这一格原来讲的是「本局超过社团里 43% 的冒险者」。那句话有三层问题：
「社团」在产品里没有任何数据实体（库里没有 guild / club / 成员表）、
7 人池子上的 43% 是 1/7 粒度的假精度、而且拿**你这一局**比**别人的历史最佳**
（还是别人另一份副本的最好成绩）在语义上根本不成立。

现在它只回答一个问题：**比过去的自己怎么样。** 用「答对几题」说，不说百分比。

## 两层

| 层 | 函数 | 要不要库 |
|---|---|---|
| 判定 | `judge` | 不要 —— 纯函数，喂进三个数就能验六种状态与优先级 |
| 取数 | `for_attempt` | 要 —— 三条查询的筛选口径 |

业务规则全部收在 `judge` 里，`for_attempt` 只负责「取哪些行」。
这样「状态怎么判」可以用参数化用例钉死，也**只有一处**实现
（结算页与冒险日志页读同一份数据，两屏不可能说法不一致）。

## 比较量是**答对题数**，不是正确率

用正确率比会把百分比立刻从后门请回来，而这一格的全部意义就是不说百分比。
已知代价：5 题答对 5 与 10 题答对 6 之间，前者状态更好但正确率更低 ——
这是知情接受的取舍，对策是文案强制带分母（「答对 4 / 5 题」），
让题量差异对用户可见。见 design.md 的 Risks。

## 判定的优先级

`first` > `record` > `tie_best` > `better` / `same` / `worse`。

顺序本身就是规则，不是实现细节：先判「与最好比」再判「与上一局比」，
用户就会在**追平自己最好成绩**的那一局看到「比上一局少答对 1 题」——
一句真话，但完全说错了重点。反之，先把「与上一局比」判掉，刷新纪录时
若恰好与上一局答对一样多，就会显示「与上一局持平」，把好消息盖掉。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import Attempt
from app.models.attempt import AttemptProgress, AttemptScorePoint, ProgressState


def judge(
    *,
    correct_count: int,
    previous: AttemptScorePoint | None,
    best: AttemptScorePoint | None,
) -> ProgressState:
    """判定本局相对自己历史的状态。

    Args:
        correct_count: 本局答对题数（**含未作答按 0 分**之后的权威值）。
        previous: 紧邻的上一局；首局为 `None`。
        best: 此前最好的一局（同行并列时取更近的那一局）；首局为 `None`。

    首局（`best is None`）一律 `first`：没有基准就不从空基准里推一句比较出来。
    """
    if best is None:
        return "first"
    if correct_count > best.correct:
        return "record"
    if correct_count == best.correct:
        return "tie_best"
    if previous is None:  # pragma: no cover - 有 best 就必然有 previous，兜底不抛错
        return "same"
    if correct_count > previous.correct:
        return "better"
    if correct_count == previous.correct:
        return "same"
    return "worse"


# -----------------------------------------------------------------------------
# 取数
# -----------------------------------------------------------------------------
def for_attempt(
    session: Session,
    *,
    user_id: int,
    correct_count: int,
    before_attempt_id: int | None,
) -> AttemptProgress:
    """取本局该跟哪些历史比，并给出判定结果。

    一个函数、两个入口（见 design.md 的 D2）：

    | 入口 | `before_attempt_id` | 基准 |
    |---|---|---|
    | 结算（本局**还没落库**） | `None` | 全量历史 |
    | 回看历史报告 | 该局的 id | 只含 `id <` 该局的记录 |

    形式上是两个入口，实质上是同一条规则：**基准 = 发生在这一局之前的记录**。
    结算时本局尚未插入，所以「之前的全部」就等于全量 —— 也正因如此，
    ⚠️ **结算链路必须先调这个函数、再落库**。反过来写的话，本局自己就成了
    「历史最好」的候选，拿自己跟自己比，`record` 永远不可能成立；
    而那种 bug 表现为「刷新纪录这个状态压根不出现」，看起来像逻辑没生效。

    另外两个刻意的口径：

    - 已删除的记录（`deleted_at` 非空）**照样计入**：FR-B5 要求删除
      「仅移除记录，不影响整体统计」。过滤它会让用户删一条旧记录就改掉
      自己的「最好成绩」，甚至改掉历史报告上那句状态的断言。
    - 未完成的一局（`status != 'finished'`）**不算**：最好成绩不该由
      一局中途退出产生。与旧的百分位池子口径一致。

    三条查询：紧邻上一局、此前最好的一局、此前的记录数。
    """
    scope = _scope(user_id=user_id, before_attempt_id=before_attempt_id)

    previous = _score_point(
        session,
        scope=scope,
        order_by=(Attempt.id.desc(),),
    )
    best = _score_point(
        session,
        scope=scope,
        # 并列最高时取**更近**的那一局：它决定文案里那个分母
        # （「答对 4 / 5 题」还是「答对 4 / 8 题」）。不加这个次序键，
        # MySQL 在并列行里返回哪一行是不确定的 —— 用户两次刷新可能看到两个分母。
        order_by=(Attempt.correct_count.desc(), Attempt.id.desc()),
    )
    earlier = int(
        session.scalar(select(func.count()).select_from(Attempt).where(*scope)) or 0
    )

    return AttemptProgress(
        state=judge(correct_count=correct_count, previous=previous, best=best),
        attempt_count=earlier + 1,  # 含本局
        delta_vs_prev=0 if previous is None else correct_count - previous.correct,
        delta_vs_best=0 if best is None else correct_count - best.correct,
        best=best,
        previous=previous,
    )


def _scope(*, user_id: int, before_attempt_id: int | None) -> list:
    """「这一局之前的、这位用户的、已完成记录」这一组筛选条件。

    用 `id`（自增写入序）而不是 `finished_at` 划界：客户端上报的时间戳会被
    服务端夹取（见 `attempt_service._resolve_timing`），而写入序等价于
    用户实际答题的先后。
    """
    conditions = [Attempt.user_id == int(user_id), Attempt.status == "finished"]
    if before_attempt_id is not None:
        conditions.append(Attempt.id < int(before_attempt_id))
    return conditions


def _score_point(
    session: Session, *, scope: list, order_by: tuple
) -> AttemptScorePoint | None:
    """按给定次序取第一条成绩点；没有记录时返回 `None`。"""
    row = session.execute(
        select(Attempt.correct_count, Attempt.total_count)
        .where(*scope)
        .order_by(*order_by)
        .limit(1)
    ).first()
    if row is None:
        return None
    return AttemptScorePoint(correct=int(row[0]), total=int(row[1]))
