"""冒险者档案的只读聚合（原型 04 的 3 / 4 / 7 / 9 屏）。

## 这一层只读，但「算错」不会报错

它不改任何数据，所以坏掉的方式不是抛异常，而是**数字不对** ——
柱子的窗口差一天、上一周期的数据漏进本周、知识树的「未开始」被算成「0% 掌握」。
界面上全都看不出来，只是用户看到的「我进步了」是假的。
所以每个数字的口径都在这里写清楚，测试逐项钉住。

## 全部按**业务日**切窗口，不按 UTC

「近 7 天」指的是业务时区（`Asia/Shanghai`）的 7 个自然日。
按 UTC 切会让北京时间 0–8 点的学习落到前一根柱子上 —— 而且只在那个时段跑测试时
才看得出来。窗口一律用 `business_day_bounds()` 换成 naive UTC 再与库里的列比较。

## 三处刻意的口径选择

1. **看板的领域条只列答过题的领域**（`total_count > 0`），知识树则列出**全部**
   遇到过的领域（含未开始的）。原型就是这么画的：04·3 的三条进度条都有数字，
   04·4 明确有「评测 0% · 未开始」。0% 的进度条在看板上不传达信息，
   而知识树的意义正是「还有什么没点亮」。

2. **正确率按题量加权**（`sum(答对) / sum(总题数)`），不是「每局正确率的算术平均」。
   一局 4/4 与一局 1/2：加权是 83%，算术平均会算成 75% ——
   而「我做对了多少题」这个说法对应的显然是前者。

3. **拿不到对比就返回 `None`**。上一个周期一题都没有时不编「+100%」，
   也不给 0 —— 前端据此显示「暂无对比」而不是一个假的箭头。

## 建议文案为什么只点领域名

原型 04·4 的原文是「RAG 已经点亮了 80%，再闯一次「向量检索」就能整片亮起来」，
同时点了领域与子知识点。契约里 `next_target` 是**领域名**（前端据此高亮那个节点），
所以这里让文案与 `next_target` 严格同指 —— 文案里出现领域名、`next_target` 就是它。
点一个不存在的目标比少点一个更糟。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.constants import MASTERY_LIT_THRESHOLD
from app.core.logging import get_logger
from app.db.tables import (
    Answer,
    Attempt,
    QuestionRecord,
    QuizRecord,
    User,
    UserKnowledgeStat,
    WrongQuestion,
)
from app.models.archive import (
    DashboardBar,
    DashboardRange,
    DashboardResponse,
    DomainMastery,
    KnowledgeNode,
    KnowledgeState,
    KnowledgeTreeResponse,
    WrongQuestionItem,
    WrongQuestionsResponse,
)
from app.utils.timeutil import business_date, business_day_bounds, utcnow

logger = get_logger(__name__)

#: `range` 参数 → 统计窗口的自然日数
RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30}

#: 柱状图恒为 7 根，与 `range` 无关（原型图注：柱子过密不可读）
BAR_DAYS = 7

#: 柱下的星期标签（`date.weekday()` 周一是 0）
WEEKDAY_LABELS = "一二三四五六日"


# -----------------------------------------------------------------------------
# 04·3 数据看板
# -----------------------------------------------------------------------------
def dashboard(
    session: Session,
    user: User,
    *,
    range_: DashboardRange = "7d",
    now: datetime | None = None,
) -> DashboardResponse:
    """看板的全部数字。

    Args:
        session: 直连会话。
        user: 已加载的用户行。
        range_: `7d` / `30d`，只影响正确率与平均用时的窗口。
        now: 判定「今天」用的时刻；测试用它固定时间。
    """
    user_id = int(user.id)
    today = business_date(now)

    # ---- 柱状图：最近 7 个业务日 ----
    #
    # 逐日一次 `COUNT`（走 `idx_attempts_user_finished`）。刻意不在 SQL 里按
    # 业务日 GROUP BY：那需要 CONVERT_TZ 或按 UTC 分组再搬移边界，
    # 两种写法都比这里更容易在跨零点的边界上出错，而 7 次索引区间计数很便宜。
    bar_days = [today - timedelta(days=BAR_DAYS - 1 - index) for index in range(BAR_DAYS)]
    bars = [
        DashboardBar(
            label=WEEKDAY_LABELS[day.weekday()],
            date=day.isoformat(),
            count=_answer_count(session, user_id=user_id, day=day),
        )
        for day in bar_days
    ]
    week_answers = sum(bar.count for bar in bars)

    # ---- 与上一个等长的 7 天相比 ----
    previous_week_answers = sum(
        _answer_count(session, user_id=user_id, day=day)
        for day in (day - timedelta(days=BAR_DAYS) for day in bar_days)
    )
    week_delta = _delta_percent(week_answers, previous_week_answers)

    # ---- 正确率与用时：窗口由 `range` 决定 ----
    days = RANGE_DAYS[range_]
    current = _aggregate(session, user_id=user_id, end_day=today, days=days)
    previous = _aggregate(session, user_id=user_id, end_day=today - timedelta(days=days), days=days)

    return DashboardResponse(
        range=range_,
        has_data=_has_any_attempt(session, user_id=user_id),
        range_has_data=current.attempt_count > 0,
        bars=bars,
        week_answers=week_answers,
        week_delta_percent=week_delta,
        accuracy=current.accuracy,
        accuracy_delta=(
            None if previous.total_count == 0 else current.accuracy - previous.accuracy
        ),
        avg_duration_ms=current.avg_duration_ms,
        duration_delta_ms=(
            None
            if previous.attempt_count == 0
            else current.avg_duration_ms - previous.avg_duration_ms
        ),
        domains=_domains(session, user_id=user_id),
    )


@dataclass(frozen=True, slots=True)
class _Aggregate:
    """一个窗口内的挑战聚合。空窗口时 `accuracy` / `avg_duration_ms` 都是 0。"""

    attempt_count: int = 0
    total_count: int = 0
    accuracy: int = 0
    avg_duration_ms: int = 0


def _aggregate(session: Session, *, user_id: int, end_day: date, days: int) -> _Aggregate:
    """统计 `[end_day - days + 1, end_day]` 这个业务日窗口内的挑战。"""
    start, _ = business_day_bounds(end_day - timedelta(days=days - 1))
    _, end = business_day_bounds(end_day)

    row = session.execute(
        select(
            func.count(Attempt.id),
            func.coalesce(func.sum(Attempt.correct_count), 0),
            func.coalesce(func.sum(Attempt.total_count), 0),
            func.avg(Attempt.duration_ms),
        ).where(
            Attempt.user_id == user_id,
            Attempt.finished_at >= start,
            Attempt.finished_at < end,
        )
    ).one()

    attempt_count = int(row[0] or 0)
    total_count = int(row[2] or 0)
    accuracy = round(100 * int(row[1] or 0) / total_count) if total_count else 0
    avg_duration = int(round(float(row[3]))) if row[3] is not None else 0

    return _Aggregate(
        attempt_count=attempt_count,
        total_count=total_count,
        accuracy=accuracy,
        avg_duration_ms=avg_duration,
    )


def _answer_count(session: Session, *, user_id: int, day: date) -> int:
    """某个**业务日**的答题数。

    数 `answers` 行而不是 `attempts.total_count` 求和：两者在正常路径上相等，
    但「答题量」指的是用户真的做了多少道题，数行更贴近它的本意
    （与 `badge_service` 的口径一致）。
    """
    start, end = business_day_bounds(day)
    return int(
        session.scalar(
            select(func.count())
            .select_from(Answer)
            .join(Attempt, Answer.attempt_id == Attempt.id)
            .where(
                Attempt.user_id == user_id,
                Attempt.finished_at >= start,
                Attempt.finished_at < end,
            )
        )
        or 0
    )


def _delta_percent(current: int, previous: int) -> int | None:
    """变化的百分比；上一周期为 0 时返回 `None`（不编造对比）。"""
    if previous <= 0:
        return None
    return round(100 * (current - previous) / previous)


def _has_any_attempt(session: Session, *, user_id: int) -> bool:
    """这个用户是否**曾经**挑战过。

    用它而不是「本窗口内有没有数据」来驱动空态：一个打了两周、恰好这周没来的
    用户不该看到「还没有开始冒险」，而该看到一张平的图和「本周暂无记录」。
    """
    return bool(
        session.scalar(
            select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id)
        )
    )


def _domains(session: Session, *, user_id: int) -> list[DomainMastery]:
    """各知识领域掌握度（只含答过题的领域），按掌握度降序。

    次序在 SQL 里定死（`mastery DESC, kp_name`），不在 Python 再排一次 ——
    两处排序就是两套顺序，将来必有一处被忘掉。
    """
    rows = session.scalars(
        select(UserKnowledgeStat)
        .where(UserKnowledgeStat.user_id == user_id, UserKnowledgeStat.total_count > 0)
        .order_by(UserKnowledgeStat.mastery.desc(), UserKnowledgeStat.kp_name.asc())
    ).all()

    return [
        DomainMastery(
            name=row.kp_name,
            mastery=int(row.mastery),
            total_count=int(row.total_count),
            correct_count=int(row.correct_count),
        )
        for row in rows
    ]


# -----------------------------------------------------------------------------
# 04·4 知识树
# -----------------------------------------------------------------------------
def knowledge_tree(session: Session, user: User) -> KnowledgeTreeResponse:
    """知识树的全部节点 + 一句按事实生成的建议。

    节点集合是**两个来源的并集**：

    - `user_knowledge_stats` 里已有行（答过题的领域，有掌握度）
    - 用户名下卷轴里出现过的知识点（含**一次都没答过**的，掌握度 0）

    第二个来源不可省：只取第一个的话「未开始」这个状态永远不会出现，
    §8.3 里那句「必须先判空」就成了死代码 —— 而原型 04·4 明确画着
    「评测 0% · 未开始」。
    """
    user_id = int(user.id)

    stats = {
        row.kp_name: (int(row.total_count), int(row.correct_count))
        for row in session.scalars(
            select(UserKnowledgeStat).where(UserKnowledgeStat.user_id == user_id)
        ).all()
    }

    encountered = {
        str(name)
        for name in session.scalars(
            select(distinct(QuestionRecord.knowledge_point))
            .join(QuizRecord, QuestionRecord.quiz_id == QuizRecord.id)
            .where(
                QuizRecord.user_id == user_id,
                QuestionRecord.knowledge_point != "",
            )
        ).all()
    }

    nodes = [
        _node(name, total=stats.get(name, (0, 0))[0], correct=stats.get(name, (0, 0))[1])
        for name in stats.keys() | encountered
    ]
    # 次序：掌握度降序、同名次按名称（与看板同一口径，且一次排好便于前端直接用）
    nodes.sort(key=lambda node: (-node.mastery, node.name))

    suggestion, next_target = _suggest(nodes)

    return KnowledgeTreeResponse(
        nodes=nodes,
        lit_count=sum(1 for node in nodes if node.state == "lit"),
        growing_count=sum(1 for node in nodes if node.state == "growing"),
        not_started_count=sum(1 for node in nodes if node.state == "not_started"),
        suggestion=suggestion,
        next_target=next_target,
    )


def _node(name: str, *, total: int, correct: int) -> KnowledgeNode:
    """一个节点。**先判空**：没有作答记录时是「未开始」，不是「0% 掌握」。"""
    mastery = round(100 * correct / total) if total > 0 else 0

    if total <= 0:
        state: KnowledgeState = "not_started"
    elif mastery >= MASTERY_LIT_THRESHOLD:
        state = "lit"
    else:
        state = "growing"

    return KnowledgeNode(
        name=name,
        mastery=mastery,
        total_count=total,
        correct_count=correct,
        state=state,
    )


def _suggest(nodes: list[KnowledgeNode]) -> tuple[str, str | None]:
    """给一句**按事实**生成的建议；没有可说的就返回空。

    优先挑「最接近点亮」的进行中领域（掌握度最高的那个）——
    那是投入产出比最高的一步。没有进行中的，就指向一个还没开始的领域。
    全部点亮（或根本没有领域）时返回空串，而不是一句放之四海而皆准的
    「继续加油」：那种话在界面上和占位符没有区别。
    """
    growing = [node for node in nodes if node.state == "growing"]
    if growing:
        target = growing[0]  # 已按掌握度降序排好
        return (
            f"「{target.name}」已经点亮了 {target.mastery}%，再闯一次就能整片亮起来。",
            target.name,
        )

    not_started = [node for node in nodes if node.state == "not_started"]
    if not_started:
        target = not_started[0]
        return (
            f"「{target.name}」还是一片空白，召唤一个新副本就能开始点亮它。",
            target.name,
        )

    return "", None


# -----------------------------------------------------------------------------
# 04·7 旧识重温（错题本）
# -----------------------------------------------------------------------------
def wrong_questions(
    session: Session,
    user: User,
    *,
    due_only: bool = False,
    now: datetime | None = None,
) -> WrongQuestionsResponse:
    """错题队列。

    `due_count` 与 `total_count` **恒按整个队列统计**，与 `due_only` 无关 ——
    原型 04·7 的胶囊写「3 题到期」而列表里同时列着未到期的题，
    两个数字说的是队列的不同侧面。若随筛选变化，切一次筛选就会看到数字跳。
    """
    user_id = int(user.id)
    moment = now or utcnow()

    queue = list(
        session.scalars(
            select(WrongQuestion)
            .where(WrongQuestion.user_id == user_id, WrongQuestion.mastered.is_(False))
            .order_by(WrongQuestion.next_review_at.asc(), WrongQuestion.id.asc())
        ).all()
    )
    due_rows = [row for row in queue if row.next_review_at <= moment]
    selected = due_rows if due_only else queue

    questions = _load_question_context(session, [int(row.question_id) for row in selected])
    today = business_date(moment)

    items: list[WrongQuestionItem] = []
    for row in selected:
        context = questions.get(int(row.question_id))
        if context is None:  # pragma: no cover - 外键 CASCADE 下不应发生
            # 静默跳过会让 `items` 比队列短而不自知，所以这里留一条错误日志
            logger.error("错题 %s 指向的题目 %s 不存在，已跳过", row.id, row.question_id)
            continue

        stem, knowledge_point, quiz_title = context
        items.append(
            WrongQuestionItem(
                question_id=str(row.question_id),
                stem=stem,
                knowledge_point=knowledge_point,
                quiz_title=quiz_title,
                wrong_count=int(row.wrong_count),
                stage=int(row.stage),
                due=row.next_review_at <= moment,
                next_review_at=row.next_review_at,
                next_review_label=due_label(row.next_review_at, today=today),
            )
        )

    return WrongQuestionsResponse(
        due_count=len(due_rows),
        total_count=len(queue),
        items=items,
    )


def _load_question_context(
    session: Session, question_ids: list[int]
) -> dict[int, tuple[str, str, str]]:
    """一次取回题目文本与它所属卷轴的标题（避免逐题查询）。"""
    if not question_ids:
        return {}

    rows = session.execute(
        select(
            QuestionRecord.id,
            QuestionRecord.stem,
            QuestionRecord.knowledge_point,
            QuizRecord.title,
        )
        .join(QuizRecord, QuestionRecord.quiz_id == QuizRecord.id)
        .where(QuestionRecord.id.in_(question_ids))
    ).all()

    return {
        int(row[0]): (str(row[1]), str(row[2]), str(row[3]))
        for row in rows
    }


def due_label(next_review_at: datetime, *, today: date) -> str:
    """面向用户的到期说法。

    按**业务时区**的自然日之差算，而不是按小时数：错题的排期单位是「天」，
    说「3 天后」指的是那一天的零点，不是 72 小时以后。
    由此也保证了客户端时区与业务时区不一致的用户看到同样的天数 ——
    换到前端算就会各算各的。
    """
    delta = (business_date(next_review_at) - today).days
    if delta < 0:
        return "已经到期"
    if delta == 0:
        return "今天"
    if delta == 1:
        return "明天"
    return f"{delta} 天后"


# -----------------------------------------------------------------------------
# 04·9 勋章墙
# -----------------------------------------------------------------------------
# 实现放在 `badge_service.list_badges` —— 勋章的定义（18 枚注册表）在那里，
# 分成两处会让「注册表顺序驱动勋章墙排布」这件事变得不显然。
