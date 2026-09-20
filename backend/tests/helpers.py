"""测试用的造数辅助（档案 / 复习 / 勋章几组用例共用）。

## 为什么抽出来而不是各文件各写一份

「造一局挑战」这件事在几个文件里都要用，而它**不是随意可变的**：
它必须走真实的 `POST /attempts`，否则写出来的库状态与线上不同形，
读接口的测试就会在一个人造的形状上通过。这类辅助一旦复制两份，
迟早有一份忘了跟着接口改，于是「测试通过但线上不对」。

## 两条必须遵守的约定

1. **卷轴要先 `commit`**：接口走另一个连接，不提交就看不见。
2. **HTTP 写完之后再用 `db_session` 读，必须先 `rollback()`**：
   MySQL 默认 REPEATABLE READ，会话的第一次读就定下了快照，
   接口写进去的行不会出现在同一个会话的后续查询里。
   `expire_all()` 救不了（它只让对象过期，不换快照）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from app.db.tables import QuestionRecord, QuizRecord, WrongQuestion
from app.utils.timeutil import business_date, business_day_bounds, to_timestamp_ms

#: 看板柱下的星期标签（`date.weekday()` 0 起，周一是 0）
WEEKDAY_LABELS = "一二三四五六日"


# -----------------------------------------------------------------------------
# 时间
# -----------------------------------------------------------------------------
def at(day_offset: int, hour: int = 10) -> datetime:
    """「业务时区今天 + `day_offset` 天」的某个时刻（返回 naive UTC）。

    `hour` 默认 10 点：既不在业务日边界附近，也不在「深夜 / 早起」勋章窗口里，
    这样时间类断言不会因为造数据时的巧合而意外通过或失败。
    """
    day = business_date() + timedelta(days=day_offset)
    start, _ = business_day_bounds(day)
    return start + timedelta(hours=hour)


# -----------------------------------------------------------------------------
# 用户与卷轴
# -----------------------------------------------------------------------------
def current_user_id(client, headers: dict[str, str]) -> int:
    """从 `/users/me` 取当前登录用户 —— **不猜**「第一个用户」。

    开发通道按 `device_id` 建档，id 是自增的；写死 `user_id=1` 在只有一条用例
    时会通过，一旦别的用例先建了用户就变成随机失败。
    """
    resp = client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["user"]["id"])


def make_quiz(
    session,
    user_id: int,
    *,
    title: str = "RAG 入门闯关",
    kps: tuple[str, ...] = ("RAG 基本定义",),
    types: tuple[str, ...] | None = None,
) -> QuizRecord:
    """建一份卷轴（含题目）并提交，**不发挑战**。

    Args:
        kps: 每道题的知识点（同时决定题量）。
        types: 每道题的题型；不传则全是单选。判断题的选项是 T/F，
            其余是 A/B（A 为正确答案）。
    """
    kinds = types or ("single",) * len(kps)
    assert len(kinds) == len(kps), "types 必须与 kps 一一对应"

    quiz = QuizRecord(
        user_id=user_id,
        title=title,
        summary="测试用卷轴",
        source_type="text",
        source_name="测试输入",
        question_count=len(kps),
        difficulty="mixed",
        status="ready",
    )
    session.add(quiz)
    session.flush()

    for seq, (kp, kind) in enumerate(zip(kps, kinds), start=1):
        if kind == "judge":
            options = [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]
            answer = ["T"]
        elif kind == "multiple":
            # 多选题：4 个选项、2 个正确答案（`Question` 要求答案是真子集）
            options = [
                {"key": "A", "text": "对"},
                {"key": "B", "text": "错"},
                {"key": "C", "text": "也对"},
                {"key": "D", "text": "也错"},
            ]
            answer = ["A", "C"]
        else:
            # 单选题必须是 3–5 个选项 —— 只给 A/B 会被 `Question` 判非法
            options = [
                {"key": "A", "text": "对"},
                {"key": "B", "text": "错"},
                {"key": "C", "text": "也许"},
                {"key": "D", "text": "都不是"},
            ]
            answer = ["A"]
        session.add(
            QuestionRecord(
                quiz_id=int(quiz.id),
                seq=seq,
                type=kind,
                stem=f"{kp}：第 {seq} 题",
                options=options,
                answer=answer,
                explanation="测试用解析",
                knowledge_point=kp,
                difficulty="easy",
            )
        )
    # 接口走另一个连接，必须提交后才看得见这份卷轴
    session.commit()
    return quiz


def quiz_id_of(quiz: QuizRecord | int) -> int:
    """`QuizRecord` 或裸 id 都能传 —— 复习关卡是接口现造的，手里只有 id。"""
    return int(quiz) if isinstance(quiz, int) else int(quiz.id)


def fresh_snapshot(session) -> None:
    """结束当前事务，让下一次查询拿到**新快照**。

    MySQL 默认 REPEATABLE READ：会话的第一次读就定下了整个事务的快照。
    接口（另一个连接）写进去的行，在同一个会话里怎么读都看不见 ——
    `expire_all()` 也救不了（它只让对象过期，不换快照）。

    ⚠️ 它会丢弃**未提交**的改动。这些辅助函数假定调用方在布置数据时
    已经 `commit` 过（`make_quiz` / `set_due` 都会提交）。
    """
    session.rollback()


def questions_of(session, quiz: QuizRecord | int) -> list[QuestionRecord]:
    # 换快照：题目可能是接口刚（在另一个连接里）造出来的（复习关卡就是）
    fresh_snapshot(session)
    return list(
        session.query(QuestionRecord)
        .filter(QuestionRecord.quiz_id == quiz_id_of(quiz))
        .order_by(QuestionRecord.seq)
        .all()
    )


# -----------------------------------------------------------------------------
# 结算
# -----------------------------------------------------------------------------
def settle(
    client,
    headers: dict[str, str],
    session,
    quiz: QuizRecord | int,
    *,
    outcomes: tuple[str, ...],
    finished_at: datetime,
    duration_ms: int = 60_000,
    client_token: str | None = None,
) -> dict:
    """走真实的 `POST /attempts` 结算一局，返回响应体的 `data`。

    「答对」= 选中全部正确答案（多选题是**全部**，否则只算部分正确）；
    「答错」= 选中一个**不在**答案里的选项（多选题就构成错选 → 0 分）。
    这样三种题型共用同一条构造规则，不需要在用例里区分题型。

    `quiz` 可以是 `QuizRecord`，也可以是裸 id（复习关卡由接口现场造出来，
    手里只有响应里的 `quiz_id` 字符串）。
    """
    rows = questions_of(session, quiz)
    assert len(rows) == len(outcomes), "outcomes 必须与题目一一对应"

    def selection(row, outcome: str) -> list[str]:
        answer = [str(key) for key in (row.answer or [])]
        if outcome == "correct":
            return answer
        wrong_key = next(
            (str(option["key"]) for option in row.options or [] if str(option["key"]) not in answer),
            None,
        )
        assert wrong_key is not None, "这道题没有可选的错误选项"
        return [wrong_key]

    resp = client.post(
        "/api/v1/attempts",
        headers=headers,
        json={
            "quiz_id": str(quiz_id_of(quiz)),
            "client_token": client_token or str(uuid4()),
            "started_at": to_timestamp_ms(finished_at - timedelta(milliseconds=duration_ms)),
            "finished_at": to_timestamp_ms(finished_at),
            "answers": [
                {
                    "question_id": str(row.id),
                    "selected": selection(row, outcome),
                    "time_spent_ms": 1000,
                }
                for row, outcome in zip(rows, outcomes)
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def answer_n(
    client,
    headers,
    session,
    quiz: QuizRecord | int,
    *,
    times: int,
    day: int,
    outcomes: tuple[str, ...],
) -> None:
    """在同一个业务日重复结算若干次（造趋势用）。"""
    for _ in range(times):
        settle(client, headers, session, quiz, outcomes=outcomes, finished_at=at(day))


# -----------------------------------------------------------------------------
# 错题队列
# -----------------------------------------------------------------------------
def wrong_rows(session, user_id: int) -> list[WrongQuestion]:
    """读错题行（自带换快照，见 `fresh_snapshot`）。"""
    fresh_snapshot(session)
    return list(
        session.query(WrongQuestion)
        .filter(WrongQuestion.user_id == user_id)
        .order_by(WrongQuestion.question_id)
        .all()
    )


def set_due(session, row: WrongQuestion, *, days: int) -> None:
    """把一道错题的到期时间挪到「今天 + days 天」（负数为已过期）并提交。"""
    row.next_review_at = at(days)
    session.commit()


def set_last_wrong(session, row: WrongQuestion, *, days: int, hour: int = 10) -> None:
    """把「上次答错」挪到「今天 - days 天的 hour 点」并提交。

    04·8 的「N 天前你在「X」上失手」用它造数。**不能**只靠
    `settle(..., finished_at=at(-3))` 得到老日期：错题行的
    `last_wrong_at` 取的是**写入时刻**（`growth_service` 的 `now`），
    与请求里补交的 `finished_at` 无关 —— 那是有意的，补交一局旧记录
    不该把错题排期一并改回上周。

    `hour` 用业务时区的钟点（`at` 的语义）。它在这里不是装饰：
    「昨天 23:00」与现在的**小时**之差只有 21 小时，而**自然日**之差
    是 1 天 —— 用例靠它把「按天算」和「按小时算」区分开。
    """
    row.last_wrong_at = at(-days, hour=hour)
    session.commit()
