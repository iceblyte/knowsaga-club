"""结算接口与档案更新（方案 §6.3 / §8）。

覆盖：
- 服务端权威重判：全对 / 全错 / 多选四种分支 / 未作答
- 汇总口径与前端共享用例一致（`shared/scoring-cases.json`）
- 自我比较进度：六种状态、`attempt_count`、同用户隔离、幂等回放逐位一致
- 幂等：同一个 `client_token` 重复提交只产生一条挑战记录
- 越权：用别人的卷轴交卷 → 4005，且两次响应完全同形
- 归属：读/取消别人的任务 → 4004
- 档案：XP 累加、金币、连续天数三种边界、错题入队与阶段推进、知识领域统计

## 一局题库怎么进到测试里

出题接口会真的调用模型，测试里一律 mock（见 conftest 的约定）。
所以这里统一走一个夹具 `submitted_quiz`：**直接调 `quiz_repository.persist_quiz`**
造出一份落库的卷轴，再拿它的 id 去交卷。这条路避开了出题链，
但用到的落库代码与线上完全一致 —— 包括把题目 id 回写成数据库主键这一步。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.constants import MAX_SESSION_MS
from app.core.exceptions import ErrorCode
from app.db.tables import Attempt, Answer, User, UserKnowledgeStat, WrongQuestion
from app.models.quiz import Quiz
from app.services import quiz_repository
from app.utils.timeutil import business_date, to_timestamp_ms, utcnow

ATTEMPT_URL = "/api/v1/attempts"


# -----------------------------------------------------------------------------
# 夹具
# -----------------------------------------------------------------------------
@pytest.fixture
def submitted_quiz(db_session, current_user_id, sample_quiz_payload: dict):  # noqa: ANN201
    """落库一份卷轴（归**当前登录用户**），返回 `(Quiz 契约, 卷轴行 id)`。

    归属取 `current_user_id` 而不是写死 `1`：`quizzes.user_id` 是指向
    `users.id` 的外键，写死的 id 在「不需要登录」的用例里根本不存在，
    报出来的是一个和用例意图毫不相干的 FK 错误（实测踩过）。
    """

    def _make() -> tuple[Quiz, int]:
        quiz = Quiz.model_validate(sample_quiz_payload)
        stored = quiz_repository.persist_quiz(db_session, user_id=current_user_id, quiz=quiz)
        return stored, int(stored.quiz_id)

    return _make


@pytest.fixture
def current_user_id(db_client, auth_headers) -> int:  # noqa: ANN001
    """默认登录用户的数据库 id。

    从 `GET /users/me` 拿而不是猜「第一个用户」—— 猜出来的 id
    在夹具顺序变化时会指向另一个用户，而那种失败极难定位。
    """
    resp = db_client.get("/api/v1/users/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["user"]["id"])


@pytest.fixture
def other_submitted_quiz(db_session, other_user_id, sample_quiz_payload: dict):  # noqa: ANN201
    """落库一份**归第二个用户**的卷轴（口径与 `submitted_quiz` 相同）。

    专供「真实社团分位」用例：分位要跟**其他冒险者**比，就得真有第二个人的
    成绩；而交卷接口不允许拿别人的卷轴答题（4005），所以必须另造一份。
    """

    def _make() -> tuple[Quiz, int]:
        quiz = Quiz.model_validate(sample_quiz_payload)
        stored = quiz_repository.persist_quiz(db_session, user_id=other_user_id, quiz=quiz)
        return stored, int(stored.quiz_id)

    return _make


@pytest.fixture
def other_user_id(db_client, other_auth_headers) -> int:  # noqa: ANN001
    """第二个登录用户的数据库 id，供越权用例使用。"""
    resp = db_client.get("/api/v1/users/me", headers=other_auth_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["user"]["id"])


def _answer(question_id: str, selected: list[str], spent_ms: int = 1000) -> dict:
    return {"question_id": question_id, "selected": selected, "time_spent_ms": spent_ms}


def _submit_body(quiz: Quiz, answers: list[dict], **overrides) -> dict:
    """组一份合法的交卷请求体。默认整局用时 100 秒。

    ⚠️ 时间戳必须走 `to_timestamp_ms()`，**不要**写回 `utcnow().timestamp()`：
    `utcnow()` 是 naive datetime，Python 的 `.timestamp()` 会把 naive **当本地时间**
    解释，于是一整串时间戳早了 8 小时（UTC+8 偏移）。在**本地 00:00–08:00** 这段，
    这个偏移会把 `finished_at` 压回**前一天** ⇒ 服务端算出的 `business_date()`
    比用例里的 `business_date()` 小一天。症状很隐蔽：`test_streak_boundaries` 的
    「昨天 / 前天」两条断言刚好**互换**（前者期望 2 得 1、后者期望 1 得 2），
    而白天跑全绿 —— 2026-09-26 凌晨实测暴露。
    """
    now_ms = to_timestamp_ms(utcnow())
    body = {
        "quiz_id": quiz.quiz_id,
        "client_token": str(uuid.uuid4()),
        "started_at": now_ms - 100_000,
        "finished_at": now_ms,
        "answers": answers,
    }
    body.update(overrides)
    return body


def _all_correct(quiz: Quiz) -> list[dict]:
    """全对的作答：每题选它的正确答案。

    答案取自题库里的 `Question.answer` —— 也顺便验证了「服务端用的是快照，
    不是客户端上报的分数」这件事：这里根本不传分数。
    """
    return [_answer(question.id, list(question.answer)) for question in quiz.questions]


# -----------------------------------------------------------------------------
# 正常结算
# -----------------------------------------------------------------------------
def test_full_marks_matches_prototype(db_client, auth_headers, submitted_quiz) -> None:
    """5 题全对 = 200 XP / 36 金币 / 正确率 100%（原型通关结算的数字）。"""
    quiz, _ = submitted_quiz()

    resp = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["summary"]["xp_gained"] == 200
    assert data["summary"]["max_xp"] == 200
    assert data["summary"]["coins_gained"] == 36
    assert data["summary"]["accuracy"] == 100
    assert data["summary"]["correct_count"] == 5
    assert data["summary"]["wrong_count"] == 0
    assert data["attempt_no"] == 1
    assert data["duplicate"] is False


def test_grading_is_authoritative_not_client_reported(
    db_client, auth_headers, submitted_quiz
) -> None:
    """客户端只报选择，分数由服务端算 —— 提交里根本没有分数字段可篡改。"""
    quiz, _ = submitted_quiz()
    body = _submit_body(quiz, _all_correct(quiz))

    data = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]

    for item in data["results"]:
        assert item["earned_xp"] == item["max_xp"]
        assert item["outcome"] == "correct"
        # 回传答案与解析，供报告页与卷轴详情回放
        assert item["answer"]
        assert item["explanation"]
        assert item["knowledge_point"]


def test_all_wrong_gives_zero(db_client, auth_headers, submitted_quiz) -> None:
    """全错：0 XP / 0 金币 / 正确率 0，且状态是 `first`（本用户此前没有记录）。"""
    quiz, _ = submitted_quiz()
    wrong = [_answer(q.id, ["Z"]) for q in quiz.questions]

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, wrong), headers=auth_headers
    ).json()["data"]

    assert data["summary"]["xp_gained"] == 0
    assert data["summary"]["coins_gained"] == 0
    assert data["summary"]["accuracy"] == 0
    assert data["summary"]["wrong_count"] == 5
    assert data["summary"]["progress"]["state"] == "first"
    assert data["summary"]["progress"]["best"] is None
    assert data["summary"]["progress"]["previous"] is None


# -----------------------------------------------------------------------------
# 自我比较进度（2026-09-23 起，替换掉「与他人比百分位」）
# -----------------------------------------------------------------------------
def _answers_with_n_correct(quiz: Quiz, correct_count: int) -> list[dict]:
    """前 `correct_count` 题答对、其余答错。

    题序不影响结果 —— 判定只看**答对题数**（`scoring.grade_answer` 按题算），
    所以不必关心哪几题对。答错的题故意选一个**不在选项里**的键（`Z`），
    这样多选题也不会落进「部分正确」那一档。
    """
    return [
        _answer(question.id, list(question.answer))
        if index < correct_count
        else _answer(question.id, ["Z"])
        for index, question in enumerate(quiz.questions)
    ]


def _summary_of(db_client, auth_headers, quiz: Quiz, correct_count: int) -> dict:
    data = db_client.post(
        ATTEMPT_URL,
        json=_submit_body(quiz, _answers_with_n_correct(quiz, correct_count)),
        headers=auth_headers,
    ).json()["data"]
    return data["summary"]


def test_summary_carries_no_percentile_field(db_client, auth_headers, submitted_quiz) -> None:
    """结算响应里**不存在**任何百分位字段。

    横向比较在本期是硬边界（见 spec 的第一条需求），不是「暂时不显示」——
    留一个恒为 `null` 的字段，前端就会残留一个永远走不到的分支，
    下一个人读代码时会以为功能坏了。
    """
    quiz, _ = submitted_quiz()

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _answers_with_n_correct(quiz, 3)), headers=auth_headers
    ).json()["data"]

    assert "percentile" not in data["summary"]
    assert "percentile_pool" not in data["summary"]
    assert "percentile" not in data
    # 替换它的东西在
    assert data["summary"]["progress"]["state"] == "first"


def test_progress_first_attempt_has_exact_shape(
    db_client, auth_headers, submitted_quiz
) -> None:
    """首局：整个 `progress` 对象逐字段锁死。

    首局是唯一「三个字段全空」的形态，也是最容易被写歪的一种 ——
    从空基准里推出一句比较（「和上一局一样」）就是从这里开始的。
    """
    quiz, _ = submitted_quiz()

    progress = _summary_of(db_client, auth_headers, quiz, 3)["progress"]

    assert progress == {
        "state": "first",
        "attempt_count": 1,
        "delta_vs_prev": 0,
        "delta_vs_best": 0,
        "best": None,
        "previous": None,
    }


def test_progress_walks_all_six_states(db_client, auth_headers, submitted_quiz) -> None:
    """连续交 6 局，把六种状态真实走一遍。

    | 局 | 答对 | 此前最好 | 上一局 | 期望状态 |
    |---|---|---|---|---|
    | 1 | 2 | — | — | `first` |
    | 2 | 3 | 2 | 2 | `record` |
    | 3 | 1 | 3 | 3 | `worse` |
    | 4 | 2 | 3 | 1 | `better` |
    | 5 | 2 | 3 | 2 | `same` |
    | 6 | 3 | 3 | 2 | `tie_best`（追平不是刷新） |

    走真实接口而不是直接写库：`attempt_count`、`best`、`previous` 三者
    必须与「这一局真的被写进去之后」的状态对得上 —— 尤其第 2 局，
    它同时验了「基准不含本局」（先落库再算的话永远是 `first`）。
    """
    quiz, _ = submitted_quiz()

    summaries = [_summary_of(db_client, auth_headers, quiz, n) for n in (2, 3, 1, 2, 2, 3)]

    assert [s["progress"]["state"] for s in summaries] == [
        "first",
        "record",
        "worse",
        "better",
        "same",
        "tie_best",
    ]
    assert [s["progress"]["attempt_count"] for s in summaries] == [1, 2, 3, 4, 5, 6]

    # 最好成绩一路跟到最后仍是第 2 局那个 3；上一局始终是紧邻的那一局
    record = summaries[-1]["progress"]
    assert record["best"] == {"correct": 3, "total": 5}
    assert record["previous"] == {"correct": 2, "total": 5}
    assert record["delta_vs_best"] == 0  # 追平 → 差值 0（也正因如此文案不说「多答对 0 题」）
    assert record["delta_vs_prev"] == 1

    # 第 2 局：刷新纪录时差值指的是「比此前最好多几题」，不是「比上一局多几题」
    assert summaries[1]["progress"]["delta_vs_best"] == 1
    assert summaries[1]["progress"]["delta_vs_prev"] == 1


def test_progress_is_per_user_not_global(
    db_client, auth_headers, other_auth_headers, submitted_quiz, other_submitted_quiz
) -> None:
    """别人刷了多少局都与我的 `progress` 无关 —— 这正是本次要撤掉的那种比较。

    旧行为下这里比的是「社团里其他人的最佳正确率」，所以第二个人一交卷，
    第一个人的成绩单就变了；现在第二个人的成绩对第一个人完全不可见。
    """
    mine, _ = submitted_quiz()
    theirs, _ = other_submitted_quiz()

    # 另一位冒险者连着交 3 局（0 / 5 / 3 对）
    for correct in (0, 5, 3):
        db_client.post(
            ATTEMPT_URL,
            json=_submit_body(theirs, _answers_with_n_correct(theirs, correct)),
            headers=other_auth_headers,
        )

    progress = _summary_of(db_client, auth_headers, mine, 4)["progress"]

    assert progress["state"] == "first"  # 我的历史仍是空的
    assert progress["attempt_count"] == 1
    assert progress["best"] is None


def test_idempotent_replay_keeps_progress_bit_for_bit(
    db_client, auth_headers, submitted_quiz
) -> None:
    """重复提交（同一个 `client_token`）与首次**逐位一致**，`progress` 也是。

    回放走的基准是「`id` 小于该局的记录」，首次走的是「全量」——
    两者看起来不同，实质是同一个集合（这一局之前存在的记录）。
    这条用例专门破坏那个等价：先交第 1 局，再交两局（含一局满分），
    然后回放第 1 局 —— 它必须仍然是「这是你的第一局」，
    而不是被后来的成绩改写成别的状态。
    """
    quiz, _ = submitted_quiz()
    body = _submit_body(quiz, _answers_with_n_correct(quiz, 4))

    first = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]
    assert first["summary"]["progress"]["state"] == "first"

    for correct in (5, 1):
        db_client.post(
            ATTEMPT_URL,
            json=_submit_body(quiz, _answers_with_n_correct(quiz, correct)),
            headers=auth_headers,
        )

    again = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]

    assert again["duplicate"] is True
    assert again["summary"] == first["summary"]
    assert again["summary"]["progress"]["state"] == "first"


def test_multiple_choice_partial_is_counted_as_partial_not_correct(
    db_client, auth_headers, submitted_quiz
) -> None:
    """多选题少选 → partial / 30 XP，且**不计入** correct_count（「4 / 5」口径）。"""
    quiz, _ = submitted_quiz()
    multiple = next(q for q in quiz.questions if q.type == "multiple")

    answers = [
        _answer(q.id, list(q.answer)[:1] if q.id == multiple.id else list(q.answer))
        for q in quiz.questions
    ]
    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, answers), headers=auth_headers
    ).json()["data"]

    assert data["summary"]["partial_count"] == 1
    assert data["summary"]["correct_count"] == 4
    assert data["summary"]["wrong_count"] == 0
    assert data["summary"]["accuracy"] == 80
    # 40×3 + 30 + 20 = 170
    assert data["summary"]["xp_gained"] == 170
    assert data["summary"]["coins_gained"] == 30


def test_multiple_choice_wrong_pick_zeroes_the_question(
    db_client, auth_headers, submitted_quiz
) -> None:
    """多选题含错选一票否决：即使也选对了部分，仍是 0 分。"""
    quiz, _ = submitted_quiz()
    multiple = next(q for q in quiz.questions if q.type == "multiple")
    keys = [option.key for option in multiple.options]
    bad = next(key for key in keys if key not in multiple.answer)

    answers = [
        _answer(q.id, list(multiple.answer)[:1] + [bad] if q.id == multiple.id else list(q.answer))
        for q in quiz.questions
    ]
    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, answers), headers=auth_headers
    ).json()["data"]

    assert data["summary"]["partial_count"] == 0
    assert data["summary"]["wrong_count"] == 1
    # 单选 120 + 多选 0（错选一票否决）+ 判断 20 = 140
    assert data["summary"]["xp_gained"] == 140


def test_unanswered_questions_are_graded_as_wrong(db_client, auth_headers, submitted_quiz) -> None:
    """缺题按未作答计 0 分，分母仍是题量 —— 中途退出不会让正确率变好看。"""
    quiz, _ = submitted_quiz()
    only_first = _all_correct(quiz)[:1]

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, only_first), headers=auth_headers
    ).json()["data"]

    assert data["summary"]["total_count"] == 5
    assert data["summary"]["correct_count"] == 1
    assert data["summary"]["wrong_count"] == 4
    assert data["summary"]["accuracy"] == 20
    # 每一题都有结果行，包括没作答的那四道
    assert [item["selected"] for item in data["results"][1:]] == [[], [], [], []]


def test_results_follow_quiz_order_not_request_order(
    db_client, auth_headers, submitted_quiz
) -> None:
    """结果按题库题序返回，而不是按请求里的顺序 —— 界面按题序展示。"""
    quiz, _ = submitted_quiz()

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, list(reversed(_all_correct(quiz)))), headers=auth_headers
    ).json()["data"]

    assert [item["seq"] for item in data["results"]] == [1, 2, 3, 4, 5]
    assert [item["question_id"] for item in data["results"]] == [q.id for q in quiz.questions]


def test_duration_and_average_are_recorded(db_client, auth_headers, submitted_quiz) -> None:
    quiz, _ = submitted_quiz()
    now_ms = to_timestamp_ms(utcnow())
    body = _submit_body(
        quiz, _all_correct(quiz), started_at=now_ms - 120_000, finished_at=now_ms
    )

    data = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]

    assert 119_000 <= data["summary"]["duration_ms"] <= 121_000
    # 120 秒 / 5 题 = 24 秒
    assert data["summary"]["avg_seconds_per_question"] == pytest.approx(24.0, abs=0.01)


def test_absurd_duration_is_clamped_not_rejected(db_client, auth_headers, submitted_quiz) -> None:
    """用时超上限只夹取、不拒绝 —— 答题记录比这个数字重要。"""
    quiz, _ = submitted_quiz()
    now_ms = to_timestamp_ms(utcnow())
    # 开始时刻远早于结束时刻（37 天），但仍晚于 2020 年
    body = _submit_body(
        quiz, _all_correct(quiz), started_at=now_ms - 37 * 24 * 3600_000, finished_at=now_ms
    )

    resp = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["summary"]["duration_ms"] == MAX_SESSION_MS


def test_second_attempt_increments_attempt_no(db_client, auth_headers, submitted_quiz) -> None:
    quiz, _ = submitted_quiz()

    first = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]
    second = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    assert (first["attempt_no"], second["attempt_no"]) == (1, 2)


# -----------------------------------------------------------------------------
# 幂等
# -----------------------------------------------------------------------------
def test_same_client_token_is_idempotent(db_client, auth_headers, submitted_quiz, db_session) -> None:
    """网络重试复用同一个令牌：只落一条挑战记录，返回同一份结果。"""
    quiz, quiz_id = submitted_quiz()
    body = _submit_body(quiz, _all_correct(quiz))

    first = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]
    second = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]

    assert first["attempt_id"] == second["attempt_id"]
    assert first["summary"] == second["summary"]
    assert second["duplicate"] is True

    total = db_session.query(Attempt).filter(Attempt.quiz_id == quiz_id).count()
    assert total == 1


def test_idempotent_replay_does_not_double_count_xp(
    db_client, auth_headers, submitted_quiz
) -> None:
    """重复提交绝不能把 XP 加两次 —— 那会让刷分变成可能。"""
    quiz, _ = submitted_quiz()
    body = _submit_body(quiz, _all_correct(quiz))

    first = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]
    second = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]

    assert first["user"]["xp_total"] == second["user"]["xp_total"] == 200
    assert first["user"]["coins"] == second["user"]["coins"] == 36


def test_client_token_is_case_insensitive(db_client, auth_headers, submitted_quiz) -> None:
    """同一个令牌的大小写写法必须视为同一个，否则重试就能绕过去重。"""
    quiz, _ = submitted_quiz()
    token = str(uuid.uuid4())
    body = _submit_body(quiz, _all_correct(quiz), client_token=token)

    first = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]
    body["client_token"] = token.upper()
    second = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers).json()["data"]

    assert first["attempt_id"] == second["attempt_id"]
    assert second["duplicate"] is True


def test_token_belonging_to_another_user_is_rejected(
    db_client, auth_headers, other_auth_headers, submitted_quiz
) -> None:
    """令牌撞到别人的记录时既不能回放（会泄漏别人的成绩）也不能新写（会撞唯一键）。"""
    quiz, _ = submitted_quiz()
    token = str(uuid.uuid4())
    body = _submit_body(quiz, _all_correct(quiz), client_token=token)

    db_client.post(ATTEMPT_URL, json=body, headers=auth_headers)

    resp = db_client.post(ATTEMPT_URL, json=body, headers=other_auth_headers)

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


# -----------------------------------------------------------------------------
# 参数校验
# -----------------------------------------------------------------------------
def test_unknown_question_id_returns_4000(db_client, auth_headers, submitted_quiz) -> None:
    """题号不属于该卷轴 → 拒绝，而不是静默忽略（静默会掩盖前端 bug）。"""
    quiz, _ = submitted_quiz()
    answers = _all_correct(quiz) + [_answer("999999999", ["A"])]

    resp = db_client.post(ATTEMPT_URL, json=_submit_body(quiz, answers), headers=auth_headers)

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_duplicate_question_in_payload_returns_4000(
    db_client, auth_headers, submitted_quiz
) -> None:
    quiz, _ = submitted_quiz()
    answers = _all_correct(quiz)
    answers.append(dict(answers[0]))

    resp = db_client.post(ATTEMPT_URL, json=_submit_body(quiz, answers), headers=auth_headers)

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_finished_before_started_returns_4000(db_client, auth_headers, submitted_quiz) -> None:
    quiz, _ = submitted_quiz()
    now_ms = to_timestamp_ms(utcnow())

    resp = db_client.post(
        ATTEMPT_URL,
        json=_submit_body(quiz, _all_correct(quiz), started_at=now_ms, finished_at=now_ms - 1000),
        headers=auth_headers,
    )

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_seconds_used_as_milliseconds_returns_4000(
    db_client, auth_headers, submitted_quiz
) -> None:
    """「秒当毫秒传」是最容易犯的错，必须在入口挡住，否则看板会多一根 1970 的柱子。"""
    quiz, _ = submitted_quiz()
    now_ms = to_timestamp_ms(utcnow())

    resp = db_client.post(
        ATTEMPT_URL,
        json=_submit_body(quiz, _all_correct(quiz), started_at=1700000000, finished_at=now_ms),
        headers=auth_headers,
    )

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_bad_client_token_shape_returns_4000(db_client, auth_headers, submitted_quiz) -> None:
    quiz, _ = submitted_quiz()

    resp = db_client.post(
        ATTEMPT_URL,
        json=_submit_body(quiz, _all_correct(quiz), client_token="!!!not-a-token!!!"),
        headers=auth_headers,
    )

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_non_numeric_quiz_id_returns_4000(db_client, auth_headers) -> None:
    resp = db_client.post(
        ATTEMPT_URL,
        json={
            "quiz_id": "quiz_test",
            "client_token": str(uuid.uuid4()),
            "started_at": to_timestamp_ms(utcnow()) - 1000,
            "finished_at": to_timestamp_ms(utcnow()),
            "answers": [],
        },
        headers=auth_headers,
    )

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_missing_token_returns_401(db_client, submitted_quiz) -> None:
    """未登录一律 4010，与「没带令牌」共用同一个码（不区分原因）。"""
    quiz, _ = submitted_quiz()

    resp = db_client.post(ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)))

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


# -----------------------------------------------------------------------------
# 越权
# -----------------------------------------------------------------------------
def test_another_users_quiz_returns_4005_same_shape_as_missing(
    db_client, auth_headers, other_user_id, db_session
) -> None:
    """越权与「卷轴不存在」必须**完全同形**，否则错误码差异会泄漏存在性。"""
    from app.models.quiz import Quiz as QuizModel

    quiz = QuizModel.model_validate(
        {
            "quiz_id": "x",
            "title": "别人的卷轴",
            "summary": "他生成的学习资料",
            "questions": [
                {
                    "id": "q1",
                    "type": "single",
                    "stem": "题干",
                    "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}, {"key": "C", "text": "c"}],
                    "answer": ["A"],
                    "explanation": "解析",
                    "knowledge_point": "知识点",
                    "difficulty": "easy",
                },
                {
                    "id": "q2",
                    "type": "judge",
                    "stem": "题干",
                    "options": [{"key": "T", "text": "对"}, {"key": "F", "text": "错"}],
                    "answer": ["T"],
                    "explanation": "解析",
                    "knowledge_point": "知识点",
                    "difficulty": "easy",
                },
                {
                    "id": "q3",
                    "type": "judge",
                    "stem": "题干",
                    "options": [{"key": "T", "text": "对"}, {"key": "F", "text": "错"}],
                    "answer": ["F"],
                    "explanation": "解析",
                    "knowledge_point": "知识点",
                    "difficulty": "easy",
                },
            ],
        }
    )
    # 用**另一个用户**的 id 落库（模拟「别人的卷轴」）
    # 注意走 `db_session` 而不是 `get_session_factory()`：后者是**业务库**的
    # 会话工厂，测试里用它会把数据写进真实库，而且查不到任何测试用户。
    stored = quiz_repository.persist_quiz(db_session, user_id=other_user_id, quiz=quiz)

    body = _submit_body(stored, [])

    foreign = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers)
    body["quiz_id"] = "999999999"
    missing = db_client.post(ATTEMPT_URL, json=body, headers=auth_headers)

    assert foreign.status_code == 404
    assert foreign.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert foreign.json() == missing.json(), "越权与不存在的响应必须逐字节相同"


def test_retry_of_another_users_attempt_returns_4005(
    db_client, auth_headers, other_auth_headers
) -> None:
    resp = db_client.post("/api/v1/attempts/1/retry", headers=other_auth_headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


# -----------------------------------------------------------------------------
# 重做
# -----------------------------------------------------------------------------
def test_retry_returns_reusable_quiz(db_client, auth_headers, submitted_quiz) -> None:
    """重做返回的题库可以直接再交一次卷 —— 题目 id 与首次一致。"""
    quiz, _ = submitted_quiz()
    first = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    retry = db_client.post(
        f"/api/v1/attempts/{first['attempt_id']}/retry", headers=auth_headers
    ).json()["data"]

    assert retry["quiz"]["quiz_id"] == quiz.quiz_id
    assert [q["id"] for q in retry["quiz"]["questions"]] == [q.id for q in quiz.questions]
    assert retry["attempt_no"] == 2

    again = db_client.post(
        ATTEMPT_URL, json=_submit_body(Quiz.model_validate(retry["quiz"]), _all_correct(quiz)),
        headers=auth_headers,
    )
    assert again.json()["code"] == 0
    assert again.json()["data"]["attempt_no"] == 2


# -----------------------------------------------------------------------------
# 档案更新
# -----------------------------------------------------------------------------
def test_xp_and_coins_accumulate_across_attempts(
    db_client, auth_headers, submitted_quiz
) -> None:
    quiz, _ = submitted_quiz()

    first = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]
    second = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    assert first["user"]["xp_total"] == 200
    assert second["user"]["xp_total"] == 400
    assert second["user"]["coins"] == 72


def test_first_attempt_starts_streak_at_one(db_client, auth_headers, submitted_quiz) -> None:
    quiz, _ = submitted_quiz()

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    assert data["user"]["streak_days"] == 1
    assert data["user"]["longest_streak"] == 1


def test_same_day_second_attempt_keeps_streak(db_client, auth_headers, submitted_quiz) -> None:
    """同一天打两局，连续天数不变（否则一天打十局就能刷出「十日不辍」）。"""
    quiz, _ = submitted_quiz()

    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers)
    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    assert data["user"]["streak_days"] == 1


@pytest.mark.parametrize(
    ("finished_offset_days", "expected"),
    [
        (0, 1),  # 今天（已由上一个用例覆盖，这里保证边界齐全）
        (-1, 2),  # 昨天 → +1
        (-2, 1),  # 前天 → 断连，重置为 1
    ],
)
def test_streak_boundaries(
    db_client, auth_headers, submitted_quiz, db_session, finished_offset_days: int, expected: int
) -> None:
    """连续天数三种边界：同日 / 昨日 / 更早。

    直接改库里的 `last_active_date` 来构造「上一次活动」，
    而不是伪造客户端时间戳 —— 后者会被「不能晚于当前时间」的夹取影响，
    测的就不再是连续天数这条规则了。
    """
    quiz, _ = submitted_quiz()
    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]
    user_id = int(data["user"]["id"])
    assert data["user"]["streak_days"] == 1

    # 把上次活动日期挪到指定天数前，再打一局。
    # 用 `db_session`（测试库）而不是 `get_session_factory()`（业务库）——
    # 在业务库里 `get(User, user_id)` 只会返回 None，报出的是一句
    # 「NoneType 没有 last_active_date」，与用例意图完全无关。
    user = db_session.get(User, user_id)
    assert user is not None, "当前用户必须已落在测试库里"
    user.last_active_date = business_date() + timedelta(days=finished_offset_days)
    db_session.commit()

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    assert data["user"]["streak_days"] == expected


def test_wrong_answers_are_queued(db_client, auth_headers, submitted_quiz, db_session) -> None:
    quiz, _ = submitted_quiz()
    wrong = [_answer(q.id, ["Z"]) for q in quiz.questions]

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, wrong), headers=auth_headers
    ).json()["data"]

    assert data["wrong_queued_count"] == 5
    rows = db_session.query(WrongQuestion).all()
    assert len(rows) == 5
    assert all(int(row.stage) == 0 for row in rows)
    assert all(row.mastered is False for row in rows)
    # 首次答错 → 1 天后到期
    for row in rows:
        delta = row.next_review_at - utcnow()
        assert timedelta(hours=23) < delta <= timedelta(days=1, minutes=1)


def test_review_correct_twice_masters_the_question(
    db_client, auth_headers, submitted_quiz, db_session
) -> None:
    """连续两次复习答对 → 移出队列。中间只要答错一次，阶段就回到 0。"""
    quiz, _ = submitted_quiz()
    question_id = quiz.questions[0].id
    wrong = [_answer(q.id, ["Z"]) for q in quiz.questions]
    correct = _all_correct(quiz)

    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, wrong), headers=auth_headers)

    # 第一次复习答对：阶段 0 → 1，未移出
    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, correct), headers=auth_headers)
    row = db_session.query(WrongQuestion).filter(WrongQuestion.question_id == int(question_id)).one()
    assert int(row.stage) == 1
    assert row.mastered is False

    # 第二次复习答对：阶段 1 → 2，移出
    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, correct), headers=auth_headers)
    # `rollback()` 而不是 `expire_all()`：MySQL 默认 REPEATABLE READ，
    # 同一个事务里的第二次读看到的仍是第一次读的快照 —— `expire_all()`
    # 只让对象过期、不换快照，于是这里会读回 stage=1 而误判成实现有问题。
    # 结束事务才会拿到新快照。（实测踩过，见 conftest 的 `db_session` 说明。）
    db_session.rollback()
    row = db_session.query(WrongQuestion).filter(WrongQuestion.question_id == int(question_id)).one()
    assert int(row.stage) == 2
    assert row.mastered is True


def test_wrong_again_resets_stage(db_client, auth_headers, submitted_quiz, db_session) -> None:
    """答错一次就把复习阶段打回 0 —— 这是「连续两次」这条规则的实现方式。"""
    quiz, _ = submitted_quiz()
    question_id = quiz.questions[0].id
    wrong = [_answer(q.id, ["Z"]) for q in quiz.questions]
    correct = _all_correct(quiz)

    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, wrong), headers=auth_headers)
    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, correct), headers=auth_headers)

    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, wrong), headers=auth_headers)
    row = db_session.query(WrongQuestion).filter(WrongQuestion.question_id == int(question_id)).one()

    assert int(row.stage) == 0
    assert row.mastered is False
    assert int(row.wrong_count) == 2


def test_correct_answer_does_not_create_wrong_question_row(
    db_client, auth_headers, submitted_quiz, db_session
) -> None:
    """答对一道从没做错过的题，不该在错题本里凭空出现一行。"""
    quiz, _ = submitted_quiz()

    db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    )

    assert db_session.query(WrongQuestion).count() == 0


def test_knowledge_stats_accumulate_and_light_up(
    db_client, auth_headers, submitted_quiz, db_session
) -> None:
    """知识领域按题累加；掌握度 ≥ 90 点亮。

    样例题库的知识点是：RAG 基本定义 ×2、向量检索 ×1、与搜索引擎的边界 ×1、应用场景 ×1。
    全对一局后前四个字段都应该是 100%。
    """
    quiz, _ = submitted_quiz()

    db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    )

    rows = {row.kp_name: row for row in db_session.query(UserKnowledgeStat).all()}
    assert rows["RAG 基本定义"].total_count == 2
    assert rows["RAG 基本定义"].correct_count == 2
    assert rows["RAG 基本定义"].mastery == 100
    assert rows["RAG 基本定义"].lit is True
    assert rows["向量检索"].mastery == 100


def test_knowledge_mastery_counts_partial_as_not_correct(
    db_client, auth_headers, submitted_quiz, db_session
) -> None:
    """多选题部分正确只算「答过」不算「答对」—— 与 correct_count 口径一致。"""
    quiz, _ = submitted_quiz()
    multiple = next(q for q in quiz.questions if q.type == "multiple")

    answers = [
        _answer(q.id, list(q.answer)[:1] if q.id == multiple.id else list(q.answer))
        for q in quiz.questions
    ]
    db_client.post(ATTEMPT_URL, json=_submit_body(quiz, answers), headers=auth_headers)

    row = db_session.query(UserKnowledgeStat).filter(UserKnowledgeStat.kp_name == "应用场景").one()
    assert row.total_count == 1
    assert row.correct_count == 0
    assert row.mastery == 0
    assert row.lit is False


def test_answers_are_persisted_per_question(
    db_client, auth_headers, submitted_quiz, db_session
) -> None:
    """每题落一行，含未作答的 0 分行 —— 卷轴详情要逐题回放。"""
    quiz, _ = submitted_quiz()

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)[:2]), headers=auth_headers
    ).json()["data"]

    rows = db_session.query(Answer).filter(Answer.attempt_id == int(data["attempt_id"])).all()
    assert len(rows) == 5
    assert sum(1 for row in rows if row.outcome == "wrong") == 3
    # 未作答的题也有行，selected 是空数组
    assert any(list(row.selected) == [] for row in rows)


def test_attempt_row_matches_summary(db_client, auth_headers, submitted_quiz, db_session) -> None:
    """落库的汇总与响应里的汇总必须一致 —— 否则看板与结算页会各说各话。

    `progress` 刻意**不在**被比的列里：它是读的时候重算的，不落库
    （落库会变成假话 —— 用户后来又刷新了纪录，旧那一局的报告仍旧宣称
    「这是你的最好成绩」）。见 `progress_service` 的模块说明。
    """
    quiz, _ = submitted_quiz()

    data = db_client.post(
        ATTEMPT_URL, json=_submit_body(quiz, _all_correct(quiz)), headers=auth_headers
    ).json()["data"]

    row = db_session.get(Attempt, int(data["attempt_id"]))
    summary = data["summary"]
    assert int(row.xp_gained) == summary["xp_gained"]
    assert int(row.coins_gained) == summary["coins_gained"]
    assert int(row.accuracy) == summary["accuracy"]
    assert int(row.correct_count) == summary["correct_count"]
    assert int(row.total_count) == summary["total_count"]
    assert row.status == "finished"
    # 这一局是这位用户的第一局 → progress 说的是 first（而不是从库里读出来的什么）
    assert summary["progress"]["state"] == "first"
