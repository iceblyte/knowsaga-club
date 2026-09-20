"""历史卷轴（原型 04 的第 5 / 6 屏）：列表、详情、删除。

## 一条记录 = 一次挑战

`attempts` 的一行就是列表的一项。同一份卷轴重做三次 → 三条记录，
`attempt_no` 依次为 1 / 2 / 3（`quiz_repository.next_attempt_no` 在交卷时写下的）。
这不是「一份卷轴一条」—— 原型 04·5 每条写「正确率 80% · 5 题」，
而详情页带「重做」按钮，两者合起来只有「一局」这个粒度说得通
（方案 §5.5 的口径裁决）。

## 删除是软删除，且**只**影响列表与详情

需求 FR-B5 的验收标准是逐字的：「删除后该记录从列表消失，但累计 XP、
正确率、等级**不变**」。正确率（看板 `archive_service._aggregate`）与答题量
是从 `attempts` / `answers` 实时聚合出来的，硬删一行 `attempts` 会连带
`ON DELETE CASCADE` 删掉它的 `answers` 与 `reports` —— 用户看到的是
「删掉一条旧记录，我的正确率被改写了」。

所以这一列（`attempts.deleted_at`）的语义是「从我的记录里挪开」，
**不是**「这次挑战没发生过」：

| 查询 | 认不认 `deleted_at` |
|---|---|
| 本文件的列表 / 详情 / 删除 | 认（过滤掉） |
| 看板的正确率与柱状图 | 不认 |
| `build_profile` 的 `avg_accuracy` | 不认 |
| 勋章判定（`badge_service` 的事实表） | 不认（解锁了就不该被撤销） |
| `build_profile` 的 `attempt_count` / `scroll_count` | **认** —— 见下 |

最后一条是刻意的、也是唯一一处「看起来像统计但不该保持不变」的地方：
原型 04·1 的「历史卷轴」那一行直接写着「共 N 份冒险日志」，
右侧 pill 也是这个 N。它不跟着减，用户就会看到「共 2 份」的入口
点进去只有 1 条。它与 `attempts` 的行数是一回事，不是「成绩」。

## 时间说法由后端派生

`finished_label`（「今天 14:20」「昨天 21:05」「9 月 11 日」）按**业务时区**的
自然日算。理由与 `archive_service.due_label` 相同：客户端时区不同的人
也会看到同样的说法，换到前端算就会各算各的。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import SCROLL_PAGE_SIZE
from app.core.exceptions import resource_not_found
from app.db.tables import Answer, Attempt, QuestionRecord, QuizRecord, User
from app.models.archive import (
    ScrollDeleteResponse,
    ScrollDetailResponse,
    ScrollItem,
    ScrollListResponse,
    ScrollQuestionItem,
)
from app.models.quiz import Option
from app.utils.timeutil import as_aware_utc, business_date, business_tz, utcnow

logger = logging.getLogger(__name__)


def _visible_attempts(user_id: int) -> list:
    """「我的、且没被删掉的、已完成的挑战」的公共过滤条件。

    三处（列表 / 详情 / 删除）必须用同一套条件，否则会出现
    「列表里没有、但详情能打开」这种能绕过删除的缝。
    """
    return [
        Attempt.user_id == user_id,
        Attempt.deleted_at.is_(None),
        # `attempts` 只在交卷时写入，且恒为 finished；显式写出来是为了
        # 将来真出现「进行中」的行时，列表不会先把半局列出来
        Attempt.status == "finished",
    ]


def _domain_condition(domain: str):
    """「这一局**涉及过**某知识点」。

    用 `IN (子查询)` 而不是 join `answers` + `questions`：join 会让一局里
    有两道属于该领域的题时产生两行，`total` 与分页都会跟着翻倍。
    判据是「涉及过」，不是「整局都属于它」—— 一局混合卷轴在「甲」和「乙」
    两个筛选下都该出现。
    """
    return Attempt.id.in_(
        select(Answer.attempt_id)
        .join(QuestionRecord, Answer.question_id == QuestionRecord.id)
        .where(QuestionRecord.knowledge_point == domain)
    )


def list_scrolls(
    session: Session,
    user: User,
    *,
    domain: str | None = None,
    page: int = 1,
    size: int = SCROLL_PAGE_SIZE,
) -> ScrollListResponse:
    """历史卷轴列表（04·5）。

    Args:
        domain: 领域筛选；`None` / 空串表示不筛。
        page: 从 1 开始。
        size: 每页条数；上限由路由层的 `Query(le=...)` 挡在 4000。
    """
    user_id = int(user.id)
    page = max(1, int(page))
    size = max(1, int(size))

    conditions = _visible_attempts(user_id)
    if domain:
        conditions.append(_domain_condition(domain))

    total = int(
        session.scalar(
            select(func.count()).select_from(Attempt).where(*conditions)
        )
        or 0
    )

    rows = session.execute(
        select(Attempt, QuizRecord.title)
        .join(QuizRecord, Attempt.quiz_id == QuizRecord.id)
        .where(*conditions)
        .order_by(Attempt.finished_at.desc(), Attempt.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    today = business_date()
    items = [
        ScrollItem(
            attempt_id=str(attempt.id),
            quiz_id=str(attempt.quiz_id),
            title=str(title),
            finished_at=attempt.finished_at,
            finished_label=finished_label(attempt.finished_at, today=today),
            accuracy=int(attempt.accuracy),
            correct_count=int(attempt.correct_count),
            total_count=int(attempt.total_count),
            duration_ms=int(attempt.duration_ms),
            attempt_no=int(attempt.attempt_no),
        )
        for attempt, title in rows
    ]

    return ScrollListResponse(
        total=total,
        page=page,
        size=size,
        has_more=(page - 1) * size + len(items) < total,
        domains=_domains(session, user_id),
        items=items,
    )


def _domains(session: Session, user_id: int) -> list[str]:
    """可用的领域筛选项（不含「全部」）。

    **恒按未删除的全量记录统计，与当前筛选无关** —— 若跟着筛选变，
    用户切到一个空结果之后 chips 也一起消失，就再也切不回去了。

    排序按出现次数降序、同频按名称：次数多的领域更可能是用户想找的那个，
    而固定次序保证翻页 / 刷新时 chips 不会跳动。
    """
    rows = session.execute(
        select(QuestionRecord.knowledge_point, func.count().label("n"))
        .join(Answer, Answer.question_id == QuestionRecord.id)
        .join(Attempt, Attempt.id == Answer.attempt_id)
        .where(*_visible_attempts(user_id))
        .group_by(QuestionRecord.knowledge_point)
        .order_by(func.count().desc(), QuestionRecord.knowledge_point.asc())
    ).all()
    return [str(row[0]) for row in rows]


def scroll_detail(session: Session, user: User, attempt_id: int) -> ScrollDetailResponse:
    """卷轴详情（04·6）：这一局的汇总 + 逐题作答记录。

    Raises:
        AppError: 4005。**不存在与不属于当前用户走同一个分支** ——
            若为越权单独设码，攻击者就能靠错误码差异探测「这条记录存在吗」。
    """
    attempt = session.scalar(
        select(Attempt).where(Attempt.id == int(attempt_id), *_visible_attempts(int(user.id)))
    )
    if attempt is None:
        raise resource_not_found(detail=f"attempt_id={attempt_id} user_id={user.id}")

    title = session.scalar(select(QuizRecord.title).where(QuizRecord.id == attempt.quiz_id))

    rows = session.execute(
        select(QuestionRecord, Answer)
        .join(Answer, Answer.question_id == QuestionRecord.id)
        .where(Answer.attempt_id == int(attempt.id))
        .order_by(QuestionRecord.seq.asc())
    ).all()

    questions = [
        ScrollQuestionItem(
            seq=int(question.seq),
            type=question.type,
            stem=str(question.stem),
            options=[Option.model_validate(option) for option in (question.options or [])],
            answer=[str(key) for key in (question.answer or [])],
            selected=[str(key) for key in (answer.selected or [])],
            outcome=answer.outcome,
            explanation=str(question.explanation or ""),
            earned_xp=int(answer.earned_xp),
            max_xp=int(answer.max_xp),
        )
        for question, answer in rows
    ]

    if len(questions) != int(attempt.total_count):
        # 静默返回会让详情页少几题而看起来「就是这样」，所以留一条日志。
        # 外键是 CASCADE，正常不该发生。
        logger.error(
            "卷轴 %s 的作答记录数 %s 与 total_count %s 不一致",
            attempt.id, len(questions), attempt.total_count,
        )

    return ScrollDetailResponse(
        attempt_id=str(attempt.id),
        quiz_id=str(attempt.quiz_id),
        title=str(title or ""),
        source_type=_source_type(session, attempt),
        finished_at=attempt.finished_at,
        finished_label=finished_label(attempt.finished_at, today=business_date()),
        duration_ms=int(attempt.duration_ms),
        accuracy=int(attempt.accuracy),
        correct_count=int(attempt.correct_count),
        partial_count=int(attempt.partial_count),
        wrong_count=int(attempt.wrong_count),
        total_count=int(attempt.total_count),
        xp_gained=int(attempt.xp_gained),
        max_xp=int(attempt.max_xp),
        percentile=int(attempt.percentile),
        attempt_no=int(attempt.attempt_no),
        questions=questions,
    )


def _source_type(session: Session, attempt: Attempt) -> str:
    """卷轴来源（`text` / `pdf` / … / `review`）。

    复习关卡的 `quiz` 与普通卷轴同表，`source_type` 是它们唯一的区分 ——
    详情页据此可以给复习局换一个标题说法。
    """
    value = session.scalar(select(QuizRecord.source_type).where(QuizRecord.id == attempt.quiz_id))
    return str(value or "text")


def delete_scroll(session: Session, user: User, attempt_id: int) -> ScrollDeleteResponse:
    """软删除一条历史记录（04·5 的长按删除）。

    只写 `deleted_at`，**不碰任何聚合**。重复删除报 4005 而不是假装成功：
    幂等交给客户端忽略这个错误，服务端谎报成功会让「删错了」无法被发现。

    Raises:
        AppError: 4005（不存在 / 不属于当前用户 / 已经删过）。
    """
    attempt = session.scalar(
        select(Attempt).where(Attempt.id == int(attempt_id), *_visible_attempts(int(user.id)))
    )
    if attempt is None:
        raise resource_not_found(detail=f"attempt_id={attempt_id} user_id={user.id}")

    attempt.deleted_at = utcnow()
    session.commit()
    return ScrollDeleteResponse(attempt_id=str(attempt.id))


def finished_label(moment, *, today) -> str:
    """面向用户的时间说法（「今天 14:20」「昨天 21:05」「9 月 11 日」）。

    按**业务时区**的自然日之差算。跨年才带年份 —— 给今年的每一局都写上年份，
    只会把一行里最有信息量的那两个数字挤掉。

    Args:
        moment: 库里的 naive UTC 时刻。
        today: 业务时区的「今天」（调用方一次算好传进来，避免逐行取时区）。
    """
    day = business_date(moment)
    clock = as_aware_utc(moment).astimezone(business_tz()).strftime("%H:%M")

    delta = (today - day).days
    if delta == 0:
        return f"今天 {clock}"
    if delta == 1:
        return f"昨天 {clock}"
    if day.year == today.year:
        return f"{day.month} 月 {day.day} 日"
    return f"{day.year} 年 {day.month} 月 {day.day} 日"
