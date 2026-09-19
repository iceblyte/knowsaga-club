"""复习关卡（旧识重温）的组卷。

## 为什么是「复制一份卷轴」而不是「直接用原题」

`questions` 有 `UNIQUE(quiz_id, seq)`，题目不能跨卷轴共享。复习关卡自己是一份
卷轴（`source_type='review'`），所以要为每一道到期错题建一个**副本**，
副本通过 `origin_question_id` 指回原题。

副本方案还带来两个好处：原卷轴与它的历史成绩一行都不动（复习不会「改写」
那次挑战），而复习局本身也能正常结算、正常出现在历史卷轴里。

## 副本题的身份重定向是本模块存在的核心理由

题号（`questions.id`）是 `answers` 与 `wrong_questions` 的公共键，所以
**成长体系必须按 `origin_question_id or id` 认身份**（见 `attempt_service`）。

不做这件事的后果不是报错，而是两份数据都悄悄不对：

- 复习答对推进的是副本那条错题记录 → 原错题的阶段永远停在原地，
  用户复习三次也不会移出队列；
- 复习答错为副本**再建一条**错题记录 → 错题本里凭空多出一份重复，
  而且它永远不会因为复习副本被删而消失。

## 取哪些题、按什么顺序

到期的、未攻克的错题，按 `next_review_at` 升序（最紧急的先复习），
最多 `MAX_QUESTIONS`（5）道 —— 上限来自 `Quiz` 契约，超出的留在队列里，
下次还能复习。

**一道都没有时不建空局**：抛 4005。空卷轴会一路走到结算，在那里得到一个
「0 题 0 分」的挑战记录，把「平均正确率」和「连续天数」都算进去。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.tables import QuestionRecord, User, WrongQuestion
from app.models.archive import ReviewStartResponse
from app.models.quiz import MAX_QUESTIONS, Question, Quiz
from app.services import quiz_repository
from app.utils.timeutil import utcnow

logger = get_logger(__name__)

#: 复习卷轴的标题。**固定值**，不带题数 —— 带题数会让每一局都算一个
#: 「不同标题的卷轴」，把「卷轴收藏家（10 张不同标题）」刷满。
REVIEW_TITLE = "旧识重温"

#: `quizzes.source_type` 的取值，与 `models/quiz.SourceType` 一致
REVIEW_SOURCE_TYPE = "review"


def start_review(
    session: Session, user: User, *, now: datetime | None = None
) -> ReviewStartResponse:
    """用到期错题组一局复习关卡。

    Args:
        session: 直连会话。
        user: 已加载的用户行。
        now: 判定「到期」用的时刻；不传取 `utcnow()`。测试用它固定时间。

    Raises:
        AppError: 4005 —— 没有到期的错题（含「全都还没到期」）。
    """
    user_id = int(user.id)
    moment = now or utcnow()

    due = list(
        session.scalars(
            select(WrongQuestion)
            .where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.mastered.is_(False),
                WrongQuestion.next_review_at <= moment,
            )
            .order_by(WrongQuestion.next_review_at.asc(), WrongQuestion.id.asc())
            .limit(MAX_QUESTIONS)
        ).all()
    )
    if not due:
        # 码用 4005（与「不存在」同形），但**提示语要换**：默认的
        # 「内容不存在或已删除」在这里是错的，用户会以为自己的错题被删了。
        # 这里说的是自己的队列状态，不涉及任何别人的数据，改文案不泄漏信息。
        raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "现在没有到期的错题")

    questions, origins = _build_copies(session, [int(row.question_id) for row in due])

    quiz = quiz_repository.persist_quiz(
        session,
        user_id=user_id,
        quiz=Quiz(
            quiz_id="review",  # 占位；落库后会回填成数据库 id
            title=REVIEW_TITLE,
            summary=f"从错题本里挑出 {len(questions)} 道到期的旧识",
            source_type=REVIEW_SOURCE_TYPE,
            user_input="",  # 复习局没有「输入资料」，别编一个出来
            knowledge_points=None,  # 从题目派生
            questions=questions,
        ),
        origins=origins,
    )

    logger.info("用户 %s 组了一局复习关卡：%s 道到期错题", user_id, len(questions))

    return ReviewStartResponse(quiz=quiz, question_count=len(quiz.questions))


def _build_copies(
    session: Session, question_ids: list[int]
) -> tuple[list[Question], list[int | None]]:
    """按给定顺序把原题复制成副本题。

    原题理论上一定存在（`wrong_questions.question_id` 是指向 `questions` 的外键，
    `ON DELETE CASCADE`），但真缺失时不能静默少一道 —— 那样用户会拿到一份
    题数对不上的复习局，而日志里什么都没有。这里保留错误日志并跳过。
    """
    rows = {
        int(row.id): row
        for row in session.scalars(
            select(QuestionRecord).where(QuestionRecord.id.in_(question_ids))
        ).all()
    }

    questions: list[Question] = []
    origins: list[int | None] = []
    for question_id in question_ids:
        row = rows.get(question_id)
        if row is None:  # pragma: no cover - 外键约束下不应发生
            logger.error("错题指向的题目 %s 不存在，已从复习关卡中剔除", question_id)
            continue
        questions.append(_copy_of(row))
        origins.append(int(row.id))

    return questions, origins


def _copy_of(row: QuestionRecord) -> Question:
    """原题行 → 副本题契约。

    `id` 先给一个卷轴内唯一、且与任何数据库 id 都不会撞的占位值
    （`r1`/`r2`…）—— 落库时 `persist_quiz` 会把它回填成新的数据库 id。
    用 `q1` 之类的值不行：万一将来有人把副本 id 直接当原题 id 用，
    看不出区别；`r` 前缀让「这是副本」在日志里一眼可辨。
    """
    return Question(
        id=f"r{row.seq}",
        type=row.type,
        stem=row.stem,
        options=list(row.options or []),
        answer=list(row.answer or []),
        explanation=row.explanation,
        knowledge_point=row.knowledge_point,
        difficulty=row.difficulty,
    )
