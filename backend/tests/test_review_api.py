"""复习关卡（旧识重温）的组卷与结算接入。

## 这个链路的核心不是「生成一份卷轴」，而是**身份的重定向**

题号是 `questions.id`，而 `answers.question_id`、`wrong_questions.question_id`
都指向它。复习关卡里的题必须是**副本**（同一个 `quiz_id` 下 `seq` 唯一，
题目不能跨卷轴共享），于是副本有自己的新 id。

如果不做任何处理，复习答对推进的会是**副本**那条错题记录：
原错题的阶段永远停在原地，用户复习了三次也不会移出队列；
更糟的是答错会为副本**再建一条**错题记录，错题本里凭空多出一份重复。
所以副本用 `origin_question_id` 指回原题，成长体系按
`origin_question_id or id` 认身份。

下面几条用例就是钉住这件事，而不只是钉住「接口返回了 200」。
"""

from __future__ import annotations

import pytest

from sqlalchemy import distinct, func, select

from app.db.tables import QuestionRecord, QuizRecord, UserKnowledgeStat
from tests.helpers import (
    at,
    current_user_id,
    make_quiz,
    questions_of,
    set_due,
    settle,
    wrong_rows,
)

REVIEW_START = "/api/v1/review/start"


# -----------------------------------------------------------------------------
# 造数据：一份两题卷轴 + 全部答错 → 两道到期的错题
# -----------------------------------------------------------------------------
def due_wrong_questions(client, headers, session, *, kps: tuple[str, ...] = ("甲", "乙")):
    """造出「kps 每道都答错一次、且已到期」的状态，返回原卷轴。"""
    user_id = current_user_id(client, headers)
    quiz = make_quiz(session, user_id, title="原始卷轴", kps=kps)
    settle(
        client, headers, session, quiz,
        outcomes=("wrong",) * len(kps), finished_at=at(-2),
    )

    # HTTP 写过之后要换快照才看得到新行
    session.rollback()
    for row in wrong_rows(session, user_id):
        set_due(session, row, days=-1)
    return quiz


def start_review(client, headers) -> dict:
    resp = client.post(REVIEW_START, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def review_once(client, headers, session, *, outcomes: tuple[str, ...]) -> int:
    """组一局复习关卡并结算，返回卷轴 id。"""
    review_id = int(start_review(client, headers)["quiz"]["quiz_id"])
    settle(client, headers, session, review_id, outcomes=outcomes, finished_at=at(0))
    return review_id


def push_the_clock(client, headers, session) -> None:
    """把队列里所有未攻克的错题重新标成「已到期」—— **模拟时间流逝**。

    这不是绕开规则，而是规则本身：复习答对后阶段 +1，下次到期在 2 天后
    （间隔表 1/2/4/7/15/30）。真实世界里是时间把它推到期的；
    测试里若不做这一步，第二次 `start_review` 会因为「没有到期的错题」而 4005 ——
    那正是排期生效的证明，所以必须显式模拟，而不是把间隔改成 0。
    """
    user_id = current_user_id(client, headers)
    for row in wrong_rows(session, user_id):
        if not row.mastered:
            set_due(session, row, days=-1)


# -----------------------------------------------------------------------------
# 鉴权与前置条件
# -----------------------------------------------------------------------------
def test_review_start_requires_auth(db_client) -> None:
    resp = db_client.post(REVIEW_START)

    assert resp.status_code == 401
    assert resp.json()["code"] == 4010


def test_review_start_without_due_questions_is_4005(db_client, auth_headers) -> None:
    """一道到期的都没有时不能凭空造一局 —— 「不存在」与「没有」都给 4005。"""
    resp = db_client.post(REVIEW_START, headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == 4005
    assert "没有到期的错题" in resp.json()["message"]


def test_review_start_ignores_not_yet_due_questions(
    db_client, db_session, auth_headers
) -> None:
    """没到期的题不参与组卷 —— 否则「排期」这件事就形同虚设。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, title="原始卷轴", kps=("甲",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(0))

    # 刚答错的题 1 天后才到期 → 现在没有可复习的
    resp = db_client.post(REVIEW_START, headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == 4005


# -----------------------------------------------------------------------------
# 组卷
# -----------------------------------------------------------------------------
def test_review_quiz_is_built_from_due_wrong_questions(
    db_client, db_session, auth_headers
) -> None:
    due_wrong_questions(db_client, auth_headers, db_session)

    data = start_review(db_client, auth_headers)
    quiz = data["quiz"]

    assert quiz["source_type"] == "review"
    assert data["question_count"] == 2
    assert len(quiz["questions"]) == 2
    assert quiz["title"] == "旧识重温", "标题固定，不随题数变化（见下方用例）"
    assert quiz["knowledge_points"] == ["甲", "乙"]


def test_review_questions_are_copies_that_point_back(
    db_client, db_session, auth_headers
) -> None:
    """副本题有**新的** id，并通过 `origin_question_id` 指回原题。"""
    original = due_wrong_questions(db_client, auth_headers, db_session)
    origin_ids = [int(row.id) for row in questions_of(db_session, original)]

    data = start_review(db_client, auth_headers)
    review_id = int(data["quiz"]["quiz_id"])

    db_session.rollback()
    copies = questions_of(db_session, review_id)

    assert len(copies) == 2
    assert [int(row.id) for row in copies] != origin_ids, "必须是副本，不能复用原题 id"
    assert [int(row.origin_question_id) for row in copies] == origin_ids

    # 原题一行都没被动过，也仍然属于原来那份卷轴
    assert [int(row.id) for row in questions_of(db_session, original)] == origin_ids
    for row in questions_of(db_session, original):
        assert row.origin_question_id is None


def test_review_copy_keeps_everything_needed_to_grade(
    db_client, db_session, auth_headers
) -> None:
    """副本要能独立判题与讲解 —— 少了 answer / explanation 这局就没法结算。"""
    due_wrong_questions(db_client, auth_headers, db_session)

    data = start_review(db_client, auth_headers)
    question = data["quiz"]["questions"][0]

    assert question["answer"] == ["A"]
    assert [option["key"] for option in question["options"]] == ["A", "B", "C", "D"]
    assert question["explanation"] == "测试用解析"
    assert question["knowledge_point"] == "甲"


def test_review_quiz_caps_at_five_questions(db_client, db_session, auth_headers) -> None:
    """到期 6 道时只取 5 道 —— `Quiz.questions` 的上限是 5，多出来的留在队列里。"""
    due_wrong_questions(db_client, auth_headers, db_session, kps=("甲", "乙", "丙", "丁", "戊", "己"))

    data = start_review(db_client, auth_headers)

    assert data["question_count"] == 5
    assert len(data["quiz"]["questions"]) == 5


def test_review_picks_the_most_urgent_first(db_client, db_session, auth_headers) -> None:
    """组卷顺序与错题本一致：到期最久的排前面。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, title="原始卷轴", kps=("甲", "乙", "丙"))
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("wrong",) * 3, finished_at=at(-2),
    )

    db_session.rollback()
    rows = wrong_rows(db_session, user_id)
    set_due(db_session, rows[0], days=1)  # 甲
    set_due(db_session, rows[1], days=-5)  # 乙 → 最紧急
    set_due(db_session, rows[2], days=-1)  # 丙

    data = start_review(db_client, auth_headers)

    # 甲 1 天后才到期，不参与这一局
    assert [q["knowledge_point"] for q in data["quiz"]["questions"]] == ["乙", "丙"]


def test_review_is_not_available_to_another_user(
    db_client, db_session, auth_headers, other_auth_headers
) -> None:
    """别人的到期错题组不出我的复习关卡。"""
    due_wrong_questions(db_client, auth_headers, db_session)

    resp = db_client.post(REVIEW_START, headers=other_auth_headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == 4005


# -----------------------------------------------------------------------------
# 结算接入：复习答对推进的是**原错题**
# -----------------------------------------------------------------------------
def test_review_quiz_can_be_settled(db_client, db_session, auth_headers) -> None:
    """复习关卡就是一份普通题库，走既有的交卷链路，不需要第二条交卷路径。"""
    due_wrong_questions(db_client, auth_headers, db_session)

    review_id = int(start_review(db_client, auth_headers)["quiz"]["quiz_id"])
    result = settle(
        db_client, auth_headers, db_session, review_id,
        outcomes=("correct", "correct"), finished_at=at(0),
    )

    assert result["summary"]["correct_count"] == 2
    assert result["summary"]["total_count"] == 2
    assert result["quiz_id"] == str(review_id)


def test_correct_review_answer_advances_the_original_wrong_question(
    db_client, db_session, auth_headers
) -> None:
    """**核心行为**：复习答对推进的是原错题的阶段，而不是副本的。"""
    user_id = current_user_id(db_client, auth_headers)
    due_wrong_questions(db_client, auth_headers, db_session)
    review_id = int(start_review(db_client, auth_headers)["quiz"]["quiz_id"])

    settle(
        db_client, auth_headers, db_session, review_id,
        outcomes=("correct", "correct"), finished_at=at(0),
    )

    db_session.rollback()
    rows = wrong_rows(db_session, user_id)

    assert len(rows) == 2, "复习答对不该产生新的错题行"
    assert [int(row.stage) for row in rows] == [1, 1], "原错题的阶段应当推进"
    assert all(row.last_review_at is not None for row in rows)


def test_two_correct_reviews_master_the_original(db_client, db_session, auth_headers) -> None:
    """连续两次复习答对 → 原错题移出队列。这是「攻克」的定义。"""
    user_id = current_user_id(db_client, auth_headers)
    due_wrong_questions(db_client, auth_headers, db_session)

    for _ in range(2):
        review_once(db_client, auth_headers, db_session, outcomes=("correct", "correct"))
        # 第一次复习后阶段变成 1，下次要 2 天后 —— 模拟时间走过去
        push_the_clock(db_client, auth_headers, db_session)

    assert all(row.mastered for row in wrong_rows(db_session, user_id))

    body = db_client.get(
        "/api/v1/users/me/wrong-questions", headers=auth_headers
    ).json()["data"]
    assert body["total_count"] == 0


def test_wrong_review_answer_bumps_the_original_not_a_copy(
    db_client, db_session, auth_headers
) -> None:
    """复习答错：原错题的 `wrong_count` +1、阶段归零，**且不新增一条重复记录**。"""
    user_id = current_user_id(db_client, auth_headers)
    due_wrong_questions(db_client, auth_headers, db_session)

    before = {int(row.question_id): int(row.wrong_count) for row in wrong_rows(db_session, user_id)}

    review_id = int(start_review(db_client, auth_headers)["quiz"]["quiz_id"])
    settle(
        db_client, auth_headers, db_session, review_id,
        outcomes=("wrong", "wrong"), finished_at=at(0),
    )

    db_session.rollback()
    rows = wrong_rows(db_session, user_id)
    after = {int(row.question_id): int(row.wrong_count) for row in rows}

    assert set(after) == set(before), "错题本不能因为复习答错而多出重复行"
    assert all(after[qid] == before[qid] + 1 for qid in before)
    assert [int(row.stage) for row in rows] == [0, 0], "答错即阶段归零"


def test_review_quiz_title_is_stable_across_sessions(
    db_client, db_session, auth_headers
) -> None:
    """标题固定为「旧识重温」，不随题数变化。

    带题数的标题（「重温 2 道」）会让每一局都算一个**不同标题的卷轴**，
    于是「卷轴收藏家（10 张不同标题）」会被复习局刷满 —— 而那些不是新卷轴。
    """
    due_wrong_questions(db_client, auth_headers, db_session)

    first = start_review(db_client, auth_headers)["quiz"]["title"]
    review_once(db_client, auth_headers, db_session, outcomes=("wrong", "wrong"))
    push_the_clock(db_client, auth_headers, db_session)

    second = start_review(db_client, auth_headers)["quiz"]["title"]

    assert first == second == "旧识重温"


def test_review_quiz_does_not_count_as_a_distinct_scroll_title(
    db_client, db_session, auth_headers
) -> None:
    """重复复习不会把「不同标题的卷轴」数刷上去。"""
    due_wrong_questions(db_client, auth_headers, db_session)

    for _ in range(3):
        review_once(db_client, auth_headers, db_session, outcomes=("wrong", "wrong"))
        push_the_clock(db_client, auth_headers, db_session)

    titles = db_session.scalar(
        select(func.count(distinct(QuizRecord.title))).where(
            QuizRecord.user_id == current_user_id(db_client, auth_headers)
        )
    )
    assert int(titles) == 2, "原始卷轴 + 复习卷轴，各算一个标题"


def test_review_does_not_duplicate_knowledge_stats(
    db_client, db_session, auth_headers
) -> None:
    """复习也是真的答了题，所以知识统计要 +1（这是对的，不是重复计数）。

    这条用例的价值在于确认「副本不是隐身题」：如果统计只认原卷轴的题号，
    复习的作答就会被整批丢掉，用户会觉得「我明明复习了，掌握度没变」。
    """
    user_id = current_user_id(db_client, auth_headers)
    due_wrong_questions(db_client, auth_headers, db_session, kps=("甲",))
    review_id = int(start_review(db_client, auth_headers)["quiz"]["quiz_id"])

    settle(
        db_client, auth_headers, db_session, review_id,
        outcomes=("correct",), finished_at=at(0),
    )

    db_session.rollback()
    stat = db_session.query(UserKnowledgeStat).filter(
        UserKnowledgeStat.user_id == user_id
    ).one()

    assert int(stat.total_count) == 2, "原始一次 + 复习一次"
    assert int(stat.correct_count) == 1


def test_review_copies_are_marked_in_the_database(db_client, db_session, auth_headers) -> None:
    """副本的 `origin_question_id` 必须真的落库（成长体系靠它认身份）。"""
    due_wrong_questions(db_client, auth_headers, db_session)
    review_id = int(start_review(db_client, auth_headers)["quiz"]["quiz_id"])

    db_session.rollback()
    copies = db_session.query(QuestionRecord).filter(
        QuestionRecord.quiz_id == review_id
    ).all()

    assert copies, "复习卷轴应当有题目行"
    assert all(row.origin_question_id is not None for row in copies)
