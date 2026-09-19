"""卷轴与题目的落库 / 取回。

## 为什么单独一层

`quiz_service` 负责的是**异步出题的流程**（建任务、推进度、收尾），
本文件负责的是**卷轴这份数据怎么存、怎么读**。两者混在一起后，
任何一个改动都要在「进度条文案」和「表列长度」之间来回切换，很容易改错。

## 生成完成后的那次「id 回填」是本文件最关键的约定

AI 生成的题目 id 是 `q1`/`q2` 这种**字符串**，而 `answers.question_id`
是指向 `questions.id`（BIGINT）的**外键**。两者之间必须有一次映射。

做法：落库拿到自增 id 之后，**把题库里的题目 id 改写成数据库 id 的字符串形式**
（`q1` → `"41"`），并把 `quiz_id` 改写成 `quizzes.id` 的字符串形式。

这样带来三个好处：

1. 前端**一行都不用改** —— 它拿到的还是一个字符串 id，照样当 React key 用。
2. 交卷时前端回传的就是数据库主键，服务端不需要任何反查表或模糊匹配。
3. 不需要给 `questions` 表加一列来存「AI 原始题号」—— 本轮没有任何 schema 变更。

代价是题库里的题号不再是「第几题」的语义。这不影响任何界面：
界面上的「第 3 / 5 题」是按数组下标算的，从来没有依赖过 `id` 的字面值。

## 列长截断

`quizzes.title` 128 / `summary` 512 / `source_name` 128、
`questions.knowledge_point` 64 都是硬上限。模型偶尔会吐超长字符串，
不截断的话 MySQL 严格模式会直接报错，整次出题白跑。
截断在这里做，并且**只截断用于存储的副本**，返回给前端的题库保持原样。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import QuestionRecord, QuizRecord
from app.models.quiz import Question, Quiz

#: 与 `backend/sql/01_schema.sql` 一致
TITLE_MAX = 128
SUMMARY_MAX = 512
SOURCE_NAME_MAX = 128
SOURCE_TYPE_MAX = 16
DIFFICULTY_MAX = 16
HASH_LEN = 64
KNOWLEDGE_POINT_MAX = 64

#: 摘要为空时的占位。`summary` 列 NOT NULL DEFAULT ''，而 `Quiz.summary`
#: 是 NonEmptyStr —— 读回来必须补一个非空值，否则模型校验直接炸。
_EMPTY_SUMMARY = "（无摘要）"


def source_fingerprint(user_input: str) -> str:
    """输入资料的指纹（`quizzes.source_hash`，CHAR(64)）。

    存它是为了将来能做「同一份资料不重复建卷轴」。本轮**不做**去重 ——
    去重会改变「再生成一次」的语义（用户有时就是想重新抽一局题），
    要做得先有明确的产品规则。这里先把指纹记下来，将来加规则时不必补数据。
    """
    return hashlib.sha256(user_input.strip().encode("utf-8")).hexdigest()


def _clip(value: str, limit: int) -> str:
    return (value or "")[:limit]


def persist_quiz(
    session: Session,
    *,
    user_id: int,
    quiz: Quiz,
    difficulty: str = "mixed",
    origins: Sequence[int | None] | None = None,
) -> Quiz:
    """落库一份题库，返回**id 已回填**的新 `Quiz`。

    调用方必须用返回值替换掉手里那份 —— 原对象里的 `quiz_id` 还是
    LLM 编的字符串，拿它去 `POST /attempts` 会因为查不到卷轴而失败。

    Args:
        session: 直连会话。**由调用方负责事务边界**（这里是 flush + commit）。
        user_id: 卷轴归属。
        difficulty: 出题时的难度偏好（`easy`/`medium`/`hard`/`mixed`）。
        origins: 逐题的原题 id，用于**复习关卡的副本题**。
            `questions` 在同一卷轴内 `seq` 唯一，所以复习时只能复制题目；
            副本靠这一列指回原错题，成长体系才认得出「复习的是哪一道」。
            不传则为全 `None`（普通出题）。
    """
    if origins is not None and len(origins) != len(quiz.questions):
        raise ValueError("origins 必须与题目一一对应")
    row = QuizRecord(
        user_id=int(user_id),
        title=_clip(quiz.title, TITLE_MAX),
        summary=_clip(quiz.summary, SUMMARY_MAX),
        source_type=_clip(quiz.source_type, SOURCE_TYPE_MAX),
        # 用户输入本身就是这次卷轴的「来源」。存下来后历史卷轴与卷轴详情
        # 才有东西可展示，报告链也不必再去别处找主题。
        source_name=_clip(quiz.user_input, SOURCE_NAME_MAX),
        source_hash=source_fingerprint(quiz.user_input) if quiz.user_input else None,
        question_count=len(quiz.questions),
        difficulty=_clip(difficulty, DIFFICULTY_MAX),
        status="ready",
    )
    session.add(row)
    session.flush()

    stored: list[Question] = []
    for seq, question in enumerate(quiz.questions, start=1):
        question_row = QuestionRecord(
            quiz_id=int(row.id),
            seq=seq,
            type=question.type,
            stem=question.stem,
            options=[option.model_dump() for option in question.options],
            answer=list(question.answer),
            explanation=question.explanation,
            knowledge_point=_clip(question.knowledge_point, KNOWLEDGE_POINT_MAX),
            difficulty=question.difficulty,
            origin_question_id=origins[seq - 1] if origins is not None else None,
        )
        session.add(question_row)
        session.flush()

        # 回填数据库主键（见模块开头）。只改 id 与 knowledge_point，
        # 其余字段原样保留，避免 model_copy 之外的字段被静默丢掉。
        stored.append(
            question.model_copy(
                update={
                    "id": str(question_row.id),
                    "knowledge_point": _clip(question.knowledge_point, KNOWLEDGE_POINT_MAX),
                }
            )
        )

    session.commit()

    return Quiz(
        quiz_id=str(row.id),
        title=row.title,
        summary=row.summary or _EMPTY_SUMMARY,
        source_type=row.source_type,
        user_input=row.source_name,
        knowledge_points=None,  # 交给 Quiz 从题目派生
        questions=stored,
    )


def get_quiz_row(session: Session, quiz_id: int, *, user_id: int | None = None) -> QuizRecord | None:
    """按 id 取卷轴行；传 `user_id` 时同时校验归属（不属于则返回 `None`）。

    返回 `None` 而不是抛错的理由见 `attempt_service`：调用方对「不存在」和
    「不是你的」必须给出**同一个**结果，把两者合并成 `None` 最不容易写漏。
    """
    row = session.get(QuizRecord, int(quiz_id))
    if row is None:
        return None
    if user_id is not None and int(row.user_id) != int(user_id):
        return None
    return row


def load_questions(session: Session, quiz_id: int) -> list[QuestionRecord]:
    """按题序取回一份卷轴的全部题目。"""
    return list(
        session.scalars(
            select(QuestionRecord)
            .where(QuestionRecord.quiz_id == int(quiz_id))
            .order_by(QuestionRecord.seq)
        ).all()
    )


def build_quiz(row: QuizRecord, questions: Sequence[QuestionRecord]) -> Quiz:
    """把库里的卷轴 + 题目还原成对外的 `Quiz` 契约。

    `quiz_id` 与题目 id 都是**数据库 id 的字符串形式**，与落库时回填的一致 ——
    所以前端拿着轮询/重做接口返回的题库可以直接去交卷，不需要任何转换。
    """
    return Quiz(
        quiz_id=str(row.id),
        title=row.title,
        summary=row.summary or _EMPTY_SUMMARY,
        source_type=row.source_type,
        user_input=row.source_name,
        knowledge_points=None,  # 从题目派生；questions.knowledge_point 保证非空
        questions=[
            Question(
                id=str(item.id),
                type=item.type,
                stem=item.stem,
                options=list(item.options or []),
                answer=list(item.answer or []),
                explanation=item.explanation,
                knowledge_point=item.knowledge_point,
                difficulty=item.difficulty,
            )
            for item in questions
        ],
    )


def load_quiz(session: Session, quiz_id: int, *, user_id: int | None = None) -> Quiz | None:
    """取回一份完整题库；不存在 / 不属于该用户时返回 `None`。"""
    row = get_quiz_row(session, quiz_id, user_id=user_id)
    if row is None:
        return None
    return build_quiz(row, load_questions(session, int(row.id)))


def next_attempt_no(session: Session, quiz_id: int) -> int:
    """该卷轴的下一次尝试序号（首次 = 1）。

    没有唯一约束守着 `(quiz_id, attempt_no)`，所以并发交卷理论上可能撞号。
    实际撞不上：交卷有 `client_token` 幂等兜底，同一次交卷只会落一行。
    真出现同位次时它也只影响「第 N 次」这个展示数字，不影响任何计分。
    """
    from sqlalchemy import func

    from app.db.tables import Attempt

    current = session.scalar(
        select(func.max(Attempt.attempt_no)).where(Attempt.quiz_id == int(quiz_id))
    )
    return int(current or 0) + 1
