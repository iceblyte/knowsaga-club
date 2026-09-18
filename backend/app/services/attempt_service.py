"""交卷结算：把「逐题选择」变成「权威分数 + 档案更新」。

## 这一层为什么必须存在（方案 §6.5）

答题过程仍在前端即时判题（保证「答对后立刻变绿」不被网络延迟绑架），
但**分数由服务端算**。前端上报的只是选择，不是分数 —— 否则档案里的等级、
累计 XP、正确率全部可被篡改，看板画出来的图也就没有权威来源。

## 结算的原子性

一次交卷要写五张表：`attempts`、`answers`、`users`、`wrong_questions`、
`user_knowledge_stats`。它们**必须在同一个事务里**提交。
半截状态的后果是档案自相矛盾 —— 比如「XP 加了但错题没入队」，
用户下次复习时发现那道错题不在队列里，而他的经验值已经涨了。

`session.commit()` 由本模块负责（路由层不做事务），这是刻意的：
「一次交卷 = 一个事务」这条规则属于业务，写在这里比写在路由里更难被绕过。

## 幂等：`client_token`

交卷是客户端重试概率最高的请求（用户点了提交、网络抖动、重新进入页面）。
同一个令牌重复提交必须**返回与第一次完全相同的结果**，而不是写第二条挑战记录 ——
否则统计里会多出一局，连续天数与平均正确率都被污染。

并发双提交的处理与建档一致（见 `auth_service`）：靠唯一键兜底，
捕获 `IntegrityError` 后回滚并回查第一次写入的那一行。
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import MAX_SESSION_MS, MIN_CLIENT_TIMESTAMP_MS
from app.core.exceptions import invalid_param, resource_not_found
from app.core.logging import get_logger
from app.db.tables import Answer, Attempt, QuestionRecord, User
from app.models.attempt import (
    AttemptAnswerRequest,
    AttemptAnswerResult,
    AttemptSubmitRequest,
    AttemptSubmitResponse,
    AttemptSummary,
)
from app.services import growth_service, quiz_repository, scoring, user_service
from app.utils.timeutil import from_timestamp_ms, utcnow

logger = get_logger(__name__)

#: `attempts.avg_seconds_per_question` 是 DECIMAL(6,2)
_SECONDS_SCALE = Decimal("0.01")


# -----------------------------------------------------------------------------
# 交卷
# -----------------------------------------------------------------------------
def submit_attempt(
    session: Session,
    user: User,
    payload: AttemptSubmitRequest,
) -> AttemptSubmitResponse:
    """结算一局并更新档案。

    Raises:
        AppError: 4000 参数不合理（时间戳越界、题目不属于该卷轴）；
            4005 卷轴不存在或不属于当前用户。
    """
    # ---- 幂等：同一个令牌已经交过就原样回放 ----
    existing = _find_by_token(session, payload.client_token)
    if existing is not None:
        if int(existing.user_id) != int(user.id):
            # 令牌撞到了别人的记录。正常客户端不会发生 ——
            # 这要么是极低概率的碰撞，要么是伪造。不能回放（那会泄漏别人的成绩），
            # 也不能当作新交卷（会撞唯一键），只能拒绝。
            logger.warning(
                "交卷令牌 %s 已属于用户 %s，却被用户 %s 使用", payload.client_token, existing.user_id, user.id
            )
            raise invalid_param("交卷令牌无效，请重新提交")
        return _replay(session, user, existing)

    # ---- 卷轴归属 ----
    quiz_row = quiz_repository.get_quiz_row(session, int(payload.quiz_id), user_id=int(user.id))
    if quiz_row is None:
        # 「不存在」与「不是你的」返回同一个结果，不泄漏存在性（方案 §4.3）
        raise resource_not_found(f"卷轴 {payload.quiz_id} 不存在或不属于当前用户")

    questions = quiz_repository.load_questions(session, int(quiz_row.id))
    if not questions:
        # 数据不一致（卷轴在、题目没了）。按「不存在」处理，不暴露内部状态。
        logger.error("卷轴 %s 没有任何题目，无法结算", quiz_row.id)
        raise resource_not_found(f"卷轴 {payload.quiz_id} 不存在或不属于当前用户")

    _reject_foreign_questions(questions, payload.answers)

    # ---- 时间与用时 ----
    started_at, finished_at, duration_ms = _resolve_timing(payload)

    # ---- 判题 ----
    graded = _grade_all(questions, payload.answers)
    summary = _summarize(graded, duration_ms=duration_ms)

    # ---- 落库（一个事务） ----
    attempt = _write_attempt(
        session,
        user=user,
        quiz_id=int(quiz_row.id),
        client_token=payload.client_token,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        summary=summary,
    )
    _write_answers(session, attempt_id=int(attempt.id), graded=graded, answers=payload.answers)

    git = growth_service.apply_attempt(
        session,
        user,
        items=[
            growth_service.GradedItem(
                question_id=item.question.id,
                outcome=item.result.outcome,
                knowledge_point=item.question.knowledge_point,
            )
            for item in graded
        ],
        xp_gained=summary.xp_gained,
        coins_gained=summary.coins_gained,
        finished_at=finished_at,
    )

    try:
        session.commit()
    except IntegrityError:
        # 并发双提交：另一个请求已经用同一个令牌写成功了。
        # 回滚本次的全部写入（含 XP 与错题），回放第一次的结果。
        session.rollback()
        winner = _find_by_token(session, payload.client_token)
        if winner is None:  # pragma: no cover - 冲突却查不到，说明冲突来自别的约束
            raise
        logger.info("交卷令牌 %s 并发重复提交，回滚本次并回放已存在的结果", payload.client_token)
        return _replay(session, user, winner)

    return AttemptSubmitResponse(
        attempt_id=str(attempt.id),
        attempt_no=int(attempt.attempt_no),
        quiz_id=str(quiz_row.id),
        quiz_title=quiz_row.title,
        results=[item.to_wire() for item in graded],
        summary=summary,
        user=user_service.to_user_public(user),
        new_badges=[],  # Phase D 接入勋章规则引擎
        wrong_queued_count=git.wrong_queued_count,
        duplicate=False,
    )


# -----------------------------------------------------------------------------
# 重做同一卷轴
# -----------------------------------------------------------------------------
def retry_attempt(session: Session, user: User, attempt_id: int) -> dict:
    """取回某一局所用卷轴的题库快照，供「重做」使用。

    Raises:
        AppError: 4005 —— 这一局不存在或不属于当前用户。
    """
    attempt = session.scalar(
        select(Attempt).where(
            Attempt.id == int(attempt_id),
            Attempt.user_id == int(user.id),
        )
    )
    if attempt is None:
        raise resource_not_found(f"挑战记录 {attempt_id} 不存在或不属于当前用户")

    quiz = quiz_repository.load_quiz(session, int(attempt.quiz_id), user_id=int(user.id))
    if quiz is None:  # pragma: no cover - 有 attempt 却读不到卷轴，属于数据不一致
        logger.error("挑战记录 %s 指向的卷轴 %s 不存在", attempt.id, attempt.quiz_id)
        raise resource_not_found(f"挑战记录 {attempt_id} 不存在或不属于当前用户")

    return {
        "attempt_id": str(attempt.id),
        "attempt_no": quiz_repository.next_attempt_no(session, int(attempt.quiz_id)),
        "quiz": quiz.model_dump(mode="json"),
    }


# -----------------------------------------------------------------------------
# 判题与汇总
# -----------------------------------------------------------------------------
class _GradedQuestion:
    """一道题的「题目快照 + 判定 + 客户端原始作答」三元组。"""

    __slots__ = ("question", "result", "request")

    def __init__(
        self,
        question: QuestionRecord,
        result: scoring.GradedAnswer,
        request: AttemptAnswerRequest | None,
    ) -> None:
        self.question = question
        self.result = result
        self.request = request

    def to_wire(self) -> AttemptAnswerResult:
        return AttemptAnswerResult(
            question_id=str(self.question.id),
            seq=int(self.question.seq),
            type=self.question.type,
            stem=self.question.stem,
            selected=list(self.result.selected),
            answer=list(self.result.answer),
            outcome=self.result.outcome,
            earned_xp=self.result.earned_xp,
            max_xp=self.result.max_xp,
            explanation=self.question.explanation,
            knowledge_point=self.question.knowledge_point,
        )


def _reject_foreign_questions(
    questions: list[QuestionRecord], answers: list[AttemptAnswerRequest]
) -> None:
    """提交里出现不属于该卷轴的题号时直接拒绝。

    静默忽略是有害的：那样「少答一题」和「题号写错」在服务端看起来一模一样，
    而前者是正常行为、后者是前端 bug。拒绝能让 bug 在联调阶段就暴露。
    """
    known = {str(question.id) for question in questions}
    unknown = [answer.question_id for answer in answers if answer.question_id not in known]
    if unknown:
        raise invalid_param(f"这些题号不属于该卷轴：{unknown[:3]}")


def _grade_all(
    questions: list[QuestionRecord], answers: list[AttemptAnswerRequest]
) -> list[_GradedQuestion]:
    """按**题序**判定全部题目。

    顺序很重要：结算页与卷轴详情页都按 `quiz.questions` 的顺序展示，
    而交卷请求里的顺序由客户端决定。以题库（seq）为准，
    缺失的作答按「未作答」补一道 0 分结果。
    """
    by_id = {str(answer.question_id): answer for answer in answers}

    graded: list[_GradedQuestion] = []
    for question in questions:
        request = by_id.get(str(question.id))
        result = scoring.grade_answer(
            question.type,
            list(question.answer or []),
            list(request.selected) if request else [],
        )
        graded.append(_GradedQuestion(question=question, result=result, request=request))
    return graded


def _summarize(graded: list[_GradedQuestion], *, duration_ms: int) -> AttemptSummary:
    """汇总一局。分母是**题量**，未作答的题按 0 分占位。"""
    total_count = len(graded)
    correct_count = sum(1 for item in graded if item.result.outcome == "correct")
    partial_count = sum(1 for item in graded if item.result.outcome == "partial")
    wrong_count = total_count - correct_count - partial_count

    xp_gained = sum(item.result.earned_xp for item in graded)
    max_xp = sum(item.result.max_xp for item in graded)
    accuracy = scoring.accuracy_of(correct_count, total_count)

    return AttemptSummary(
        correct_count=correct_count,
        wrong_count=wrong_count,
        partial_count=partial_count,
        total_count=total_count,
        accuracy=accuracy,
        xp_gained=xp_gained,
        max_xp=max_xp,
        coins_gained=scoring.coins_for(xp_gained),
        percentile=scoring.percentile_for(accuracy),
        duration_ms=duration_ms,
        avg_seconds_per_question=_avg_seconds(duration_ms, total_count),
    )


def _avg_seconds(duration_ms: int, total_count: int) -> float:
    """平均单题用时（秒，两位小数）。

    用 `Decimal` 而不是浮点：这个值要写进 `DECIMAL(6,2)`，
    浮点尾数（如 `24.690000000000001`）会让「写进去=读出来」的断言不稳定。
    `ROUND_HALF_UP` 与界面直觉一致（`0.005 → 0.01`）。
    """
    if total_count <= 0:
        return 0.0
    seconds = Decimal(duration_ms) / Decimal(1000) / Decimal(total_count)
    return float(seconds.quantize(_SECONDS_SCALE, rounding=ROUND_HALF_UP))


def _resolve_timing(payload: AttemptSubmitRequest) -> tuple[datetime, datetime, int]:
    """把客户端时间戳换算成入库值，并夹取明显不合理的用时。

    规则（都不拒绝交卷 —— 答题记录比这几个数字重要得多）：

    - 时间戳早于 2020 年 → 4000。这几乎一定是「秒当毫秒传」的写法错误，
      放进去会在看板上多出一根 1970 年的柱子。
    - `finished_at` 晚于服务端当前时间 → 夹到当前时间。
      请求已经到达了，所以「现在」是结束时刻的天然上界。
    - 用时超过 `MAX_SESSION_MS` → 夹到上限并记警告。

    Raises:
        AppError: 4000 时间戳小于合理下界，或夹取后结束早于开始。
    """
    for label, value in (("started_at", payload.started_at), ("finished_at", payload.finished_at)):
        if value < MIN_CLIENT_TIMESTAMP_MS:
            raise invalid_param(f"{label} 不是合法的毫秒时间戳")

    now = utcnow()
    started_at = min(from_timestamp_ms(payload.started_at), now)
    finished_at = min(from_timestamp_ms(payload.finished_at), now)

    if finished_at < started_at:
        # 结束时刻被夹到 now 之后反而早于开始时刻：说明开始时刻本身在未来
        raise invalid_param("开始时刻晚于当前时间，无法结算")

    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    if duration_ms > MAX_SESSION_MS:
        logger.warning("交卷用时 %s ms 超过上限，已夹到 %s ms", duration_ms, MAX_SESSION_MS)
        duration_ms = MAX_SESSION_MS

    return started_at, finished_at, max(0, duration_ms)


# -----------------------------------------------------------------------------
# 写库
# -----------------------------------------------------------------------------
def _write_attempt(
    session: Session,
    *,
    user: User,
    quiz_id: int,
    client_token: str,
    started_at: datetime,
    finished_at: datetime,
    duration_ms: int,
    summary: AttemptSummary,
) -> Attempt:
    """插入 `attempts` 行并 flush 出自增 id。"""
    attempt = Attempt(
        user_id=int(user.id),
        quiz_id=quiz_id,
        attempt_no=quiz_repository.next_attempt_no(session, quiz_id),
        client_token=client_token,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        correct_count=summary.correct_count,
        wrong_count=summary.wrong_count,
        partial_count=summary.partial_count,
        total_count=summary.total_count,
        accuracy=summary.accuracy,
        max_xp=summary.max_xp,
        xp_gained=summary.xp_gained,
        coins_gained=summary.coins_gained,
        percentile=summary.percentile,
        avg_seconds_per_question=Decimal(str(summary.avg_seconds_per_question)),
        status="finished",
    )
    session.add(attempt)
    session.flush()
    return attempt


def _write_answers(
    session: Session,
    *,
    attempt_id: int,
    graded: list[_GradedQuestion],
    answers: list[AttemptAnswerRequest],
) -> None:
    """插入 `answers` 行（每题一行，含未作答的 0 分行）。

    未作答也落一行：卷轴详情页（04·6）要逐题展示「你选了什么」，
    缺行会让那一页变成「有的题有、有的题没有」。
    """
    answered_at = {answer.question_id: answer for answer in answers}
    for item in graded:
        request = answered_at.get(str(item.question.id))
        session.add(
            Answer(
                attempt_id=attempt_id,
                question_id=int(item.question.id),
                selected=list(item.result.selected),
                outcome=item.result.outcome,
                earned_xp=item.result.earned_xp,
                max_xp=item.result.max_xp,
                time_spent_ms=int(request.time_spent_ms) if request else 0,
                answered_at=utcnow(),
            )
        )
    session.flush()


# -----------------------------------------------------------------------------
# 幂等回放
# -----------------------------------------------------------------------------
def _find_by_token(session: Session, client_token: str) -> Attempt | None:
    return session.scalar(select(Attempt).where(Attempt.client_token == client_token))


def _replay(session: Session, user: User, attempt: Attempt) -> AttemptSubmitResponse:
    """用库里已有的那一局重建响应。

    刻意**重新从 `answers` + `questions` 组装**，而不是把首次的响应缓存起来：
    缓存要多一份存储与失效逻辑，而这里的重建成本只是一次查询。
    重建还顺带保证了「重复提交返回的结果」与「第一次返回的结果」在结构上
    必然一致 —— 它们走的是同一段组装代码。
    """
    rows = list(
        session.scalars(
            select(Answer).where(Answer.attempt_id == int(attempt.id))
        ).all()
    )
    questions = {
        int(question.id): question
        for question in quiz_repository.load_questions(session, int(attempt.quiz_id))
    }
    quiz_row = quiz_repository.get_quiz_row(session, int(attempt.quiz_id))

    ordered = sorted(rows, key=lambda row: int(questions[int(row.question_id)].seq))
    results: list[AttemptAnswerResult] = []
    for row in ordered:
        question = questions[int(row.question_id)]
        results.append(
            AttemptAnswerResult(
                question_id=str(question.id),
                seq=int(question.seq),
                type=question.type,
                stem=question.stem,
                selected=list(row.selected or []),
                answer=list(question.answer or []),
                outcome=row.outcome,
                earned_xp=int(row.earned_xp),
                max_xp=int(row.max_xp),
                explanation=question.explanation,
                knowledge_point=question.knowledge_point,
            )
        )

    return AttemptSubmitResponse(
        attempt_id=str(attempt.id),
        attempt_no=int(attempt.attempt_no),
        quiz_id=str(attempt.quiz_id),
        quiz_title=quiz_row.title if quiz_row else "",
        results=results,
        summary=AttemptSummary(
            correct_count=int(attempt.correct_count),
            wrong_count=int(attempt.wrong_count),
            partial_count=int(attempt.partial_count),
            total_count=int(attempt.total_count),
            accuracy=int(attempt.accuracy),
            xp_gained=int(attempt.xp_gained),
            max_xp=int(attempt.max_xp),
            coins_gained=int(attempt.coins_gained),
            percentile=int(attempt.percentile),
            duration_ms=int(attempt.duration_ms),
            avg_seconds_per_question=float(attempt.avg_seconds_per_question),
        ),
        user=user_service.to_user_public(user),
        new_badges=[],
        # 重复提交没有新入队任何错题 —— 这个 0 是准确的，不是占位
        wrong_queued_count=0,
        duplicate=True,
    )
