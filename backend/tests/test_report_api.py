"""冒险日志接口（Phase C）。

覆盖：

- 一次挑战 → 建报告任务 → 轮询拿报告，字段齐全
- **统计数字与结算页逐位相同**（报告不重算，直接搬 `attempts`）
- 服务端权威：请求里塞 `answers` / `questions` 等额外字段统统被忽略
- 幂等：重复请求复用已有报告、不再调模型；`force=true` 才重新生成
- AI 全失败 → **降级为模板报告**（`degraded=true`），而不是报错
- 动作按真实事实挂：有错题才有「立即重做」；全对时不给重做按钮
- 越权：读别人的挑战 / 轮询别人的任务 → 与「不存在」同形
- `reports` 行落库正确，且**不落统计数字、不落动作**

## 为什么这套测试要同时挂 `db_client`、`db_scope`、`inline_report_submit`

报告是异步生成的，落库发生在**后台线程**里：
- `db_client` 覆盖 `get_db`（请求级会话）→ 管不到后台路径
- `db_scope` 把 `report_service._open_session` 换成测试库 → 否则会往业务库写
- `inline_report_submit` 把后台执行换成同步 → 否则轮询时刻不确定

三个缺一不可，缺任一个的症状分别是「读不到刚写的行」「业务库多脏数据」
「用例时好时坏」，都不是「看起来像报告逻辑有问题」的报错。
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ErrorCode
from app.db.tables import Report as ReportRow
from app.models.quiz import Quiz
from app.models.report import ReportDraft
from app.services import quiz_repository
from app.utils.timeutil import utcnow

REPORT_URL = "/api/v1/report/generate"


# -----------------------------------------------------------------------------
# 夹具
# -----------------------------------------------------------------------------
@pytest.fixture
def submitted_quiz(db_session, current_user_id, sample_quiz_payload: dict):  # noqa: ANN201
    """落库一份卷轴（归**当前登录用户**），返回 `(Quiz 契约, 卷轴行 id)`。

    与 `test_attempt_api.py` 的同名夹具一致：绕开出题链直接落库，
    但用到的落库代码与线上完全相同（含把题目 id 回写成数据库主键）。
    """

    def _make() -> tuple[Quiz, int]:
        quiz = Quiz.model_validate(sample_quiz_payload)
        stored = quiz_repository.persist_quiz(db_session, user_id=current_user_id, quiz=quiz)
        return stored, int(stored.quiz_id)

    return _make


@pytest.fixture
def current_user_id(db_client, auth_headers) -> int:  # noqa: ANN001
    """默认登录用户的数据库 id（从 `/users/me` 拿，不猜「第一个用户」）。"""
    resp = db_client.get("/api/v1/users/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["user"]["id"])


@pytest.fixture
def other_user_id(db_client, other_auth_headers) -> int:  # noqa: ANN001
    resp = db_client.get("/api/v1/users/me", headers=other_auth_headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["user"]["id"])


def _answer(question_id: str, selected: list[str], spent_ms: int = 1000) -> dict:
    return {"question_id": question_id, "selected": selected, "time_spent_ms": spent_ms}


def _submit_body(quiz: Quiz, answers: list[dict], **overrides) -> dict:
    now_ms = int(utcnow().timestamp() * 1000)
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
    return [_answer(question.id, list(question.answer)) for question in quiz.questions]


def _one_wrong(quiz: Quiz) -> list[dict]:
    """第一题答错，其余全对 —— 用来验证「有错题才有重做动作」。"""
    answers = _all_correct(quiz)
    answers[0] = _answer(quiz.questions[0].id, ["Z"])
    return answers


@pytest.fixture
def foreign_attempt(
    db_client, other_auth_headers, other_user_id, db_session, sample_quiz_payload: dict
) -> dict:
    """**另一个用户**自己的一局挑战。

    必须另落一份归属该用户的卷轴：`quizzes.user_id` 与 `attempts.user_id`
    都有外键约束，拿别人的卷轴交卷会先被结算接口挡下来，测不到报告接口。
    """
    quiz = Quiz.model_validate(sample_quiz_payload)
    stored = quiz_repository.persist_quiz(db_session, user_id=other_user_id, quiz=quiz)
    return _submit_attempt(db_client, other_auth_headers, stored, _all_correct(stored))


def _draft(**overrides) -> ReportDraft:
    """一份合法的 AI 草稿（默认文案带「AI」字样，便于与模板兜底区分）。"""
    payload = {
        "mastered_points": ["RAG 基本定义"],
        "weak_points": [],
        "three_line_summary": ["AI 第一句", "AI 第二句", "AI 第三句"],
        "advice": [
            {"title": "AI 建议一", "body": "AI 说明一"},
            {"title": "AI 建议二", "body": "AI 说明二"},
            {"title": "AI 建议三", "body": "AI 说明三"},
        ],
    }
    payload.update(overrides)
    return ReportDraft.model_validate(payload)


def _submit_attempt(client, headers, quiz: Quiz, answers: list[dict]) -> dict:
    resp = client.post("/api/v1/attempts", json=_submit_body(quiz, answers), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _generate_report(client, headers, attempt_id: str, **overrides) -> dict:
    body = {"attempt_id": str(attempt_id)}
    body.update(overrides)
    resp = client.post(REPORT_URL, json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _poll_report(client, headers, task_id: str) -> dict:
    resp = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


@pytest.fixture
def ai_report(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """替换报告链，返回可控草稿，并记录调用次数与入参。

    用 `monkeypatch.setattr(report_chain, ...)` 而不是替换 `report_service` 上的名字：
    `run_report_generation` 走的是 `report_chain.generate_report_draft`（模块属性），
    两者指向同一个模块对象，所以替换模块属性即可生效。
    """
    from app.llm import report_chain

    calls: list[dict] = []

    def install(draft: ReportDraft | None = None, *, degraded: bool = False) -> None:
        def _fake(*, topic, quiz_json, answer_records, score_summary, facts, settings=None, llm_factory=None):  # noqa: ANN001, ANN202, E501
            calls.append(
                {
                    "topic": topic,
                    "quiz_json": quiz_json,
                    "answer_records": answer_records,
                    "score_summary": score_summary,
                    "facts": facts,
                }
            )
            if draft is not None:
                return draft, degraded
            # 默认路径也走一遍字段兜底，与真实链保持一致 —— 否则「全错仍有掌握点」
            # 这种在真实链里会被纠正的情况，在测试里会以校验错误的形式炸出来
            return report_chain.complete_draft(_draft(), facts), degraded

        monkeypatch.setattr(report_chain, "generate_report_draft", _fake)

    install.calls = calls  # type: ignore[attr-defined]
    return install


# -----------------------------------------------------------------------------
# 正常路径
# -----------------------------------------------------------------------------
def test_report_task_succeeds_and_returns_full_contract(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    assert created["task_id"]
    assert created["poll_interval_ms"] > 0

    payload = _poll_report(db_client, auth_headers, created["task_id"])
    assert payload["status"] == "succeeded"
    assert payload["task_type"] == "report"
    # 两种任务共用轮询端点：report 任务里 quiz 必须为空，反之亦然
    assert payload["quiz"] is None

    report = payload["report"]
    assert report["attempt_id"] == attempt["attempt_id"]
    assert report["quiz_id"] == attempt["quiz_id"]
    assert report["quiz_title"] == quiz.title
    assert len(report["three_line_summary"]) == 3
    assert len(report["advice"]) == 3
    for item in report["advice"]:
        assert item["title"] and item["body"]
    assert report["degraded"] is False


def test_report_stats_match_settlement_bit_for_bit(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """报告页与结算页的数字必须逐位相同 —— 这是本模块最不能退让的一条。

    用一个「多选部分正确」的混合结果来测：正确率 80、答对 4、部分 1、答错 0、
    XP 170、百分位 72 → 「中上」。只要服务层哪天改成「重新算一遍」，
    这里就会因为两套口径的细微差异而失败。
    """
    quiz, _ = submitted_quiz()
    multiple = next(q for q in quiz.questions if q.type == "multiple")
    answers = [
        _answer(q.id, list(q.answer)[:1] if q.id == multiple.id else list(q.answer))
        for q in quiz.questions
    ]
    attempt = _submit_attempt(db_client, auth_headers, quiz, answers)
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    report = _poll_report(db_client, auth_headers, created["task_id"])["report"]
    summary = attempt["summary"]

    assert report["accuracy"] == summary["accuracy"] == 80
    assert report["total_count"] == summary["total_count"] == 5
    assert report["correct_count"] == summary["correct_count"] == 4
    assert report["partial_count"] == summary["partial_count"] == 1
    assert report["wrong_count"] == summary["wrong_count"] == 0
    assert report["xp_gained"] == summary["xp_gained"] == 170
    assert report["max_xp"] == summary["max_xp"] == 200
    assert report["coins_gained"] == summary["coins_gained"] == 30
    assert report["duration_ms"] == summary["duration_ms"]
    assert report["avg_seconds_per_question"] == summary["avg_seconds_per_question"]
    # 原型 03 第 1 屏：72% → 「中上」
    assert report["percentile"] == summary["percentile"] == 72
    assert report["percentile_label"] == "中上"


def test_finished_at_carries_utc_offset(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """`finished_at` 必须带时区偏移。

    库里存的是 naive UTC，原样序列化出去是 `2026-09-14T06:20:00`（无偏移），
    前端 `new Date(...)` 会把它当**本地时间**解析 —— 于是北京时间的用户
    在报告页头部看到的日期可能差一天。这类错误完全没有报错，只是日子不对。
    """
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    finished_at = _poll_report(db_client, auth_headers, created["task_id"])["report"]["finished_at"]

    assert finished_at.endswith(("Z", "+00:00")), f"缺少时区偏移：{finished_at}"


def test_report_narrative_comes_from_ai_not_template(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """AI 成功时，叙述内容应当是模型给的原文。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report(_draft(three_line_summary=["一", "二", "三"]))

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    report = _poll_report(db_client, auth_headers, created["task_id"])["report"]

    assert report["three_line_summary"] == ["一", "二", "三"]
    assert report["advice"][0]["title"] == "AI 建议一"
    assert report["degraded"] is False


def test_ai_receives_deterministic_score_summary_as_input(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """统计数字是**喂给**模型的输入，而不是让模型产出 —— 模型侧不该有能力改它。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    _poll_report(db_client, auth_headers, created["task_id"])

    assert len(ai_report.calls) == 1
    call = ai_report.calls[0]
    assert call["topic"] == quiz.title
    assert "正确率 100%" in call["score_summary"]
    assert "答对 5 题" in call["score_summary"]
    # 逐题作答的文本也要带上，否则模型只能对着数字空谈
    assert "第 1 题" in call["answer_records"]


# -----------------------------------------------------------------------------
# 服务端权威：请求里的额外字段被忽略
# -----------------------------------------------------------------------------
def test_client_supplied_answers_are_ignored(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """客户端塞一份「全对」的作答记录也没用 —— 报告只认 `attempts` 上的事实。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _one_wrong(quiz))
    ai_report()

    created = _generate_report(
        db_client,
        auth_headers,
        attempt["attempt_id"],
        answers=_all_correct(quiz),  # 伪造的「全对」
        questions=[],
        score_summary="正确率 100%",
    )
    report = _poll_report(db_client, auth_headers, created["task_id"])["report"]

    assert report["correct_count"] == 4
    assert report["wrong_count"] == 1
    assert report["accuracy"] == 80


# -----------------------------------------------------------------------------
# 幂等
# -----------------------------------------------------------------------------
def test_repeat_request_reuses_existing_report_without_calling_ai(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """重复点「看报告」不该多花一次模型调用，也不该重写库里的报告。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    first = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    first_report = _poll_report(db_client, auth_headers, first["task_id"])["report"]

    second = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    # 复用路径下任务**建出来就是成功态**，前端不必再等
    assert second["status"] == "succeeded"
    second_report = _poll_report(db_client, auth_headers, second["task_id"])["report"]

    assert second_report == first_report
    assert len(ai_report.calls) == 1, "复用已有报告时不该再调模型"


def test_reuse_path_marks_steps_done(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """复用路径也必须把两步进度推到完成态。

    回归用例。这里曾经只把任务置成 `succeeded`、**没动 `steps`**，于是返回体里出现
    「`status=succeeded` 且 `steps[1].status=pending`」这种自相矛盾的状态：
    前端的三步进度卡照着 `steps` 渲染，就会在任务其实已经成功之后还显示
    「撰写复盘报告 · 待处理」。

    单测当时没抓到，是因为只断言了 `status` 与 `report` 两个字段 ——
    抓到它的是端到端抽验（`scripts/verify_report_chain.py` 第 13 节）。

    根因是两个复用入口（同步的 `submit_report_request` 与后台的
    `run_report_generation`）各自写了一遍收尾逻辑，其中一处漏了步骤推进；
    现在两处都走 `_complete_reuse`。本用例钉住同步这一个入口。
    """
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()
    _generate_report(db_client, auth_headers, attempt["attempt_id"])

    reused = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    task = _poll_report(db_client, auth_headers, reused["task_id"])

    assert task["status"] == "succeeded"
    assert [step["status"] for step in task["steps"]] == ["done", "done"]
    assert task["steps"][1]["detail"] == "已读取此前的复盘报告"


def test_force_true_regenerates(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """`force=true` 是「我不满意，重写一份」，必须真的再调一次模型。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    _generate_report(db_client, auth_headers, attempt["attempt_id"])
    forced = _generate_report(db_client, auth_headers, attempt["attempt_id"], force=True)

    assert forced["status"] != "succeeded"  # 重新生成时任务还在排队 / 运行
    _poll_report(db_client, auth_headers, forced["task_id"])
    assert len(ai_report.calls) == 2


def test_report_path_never_fetches_external_material(
    db_client,
    auth_headers,
    submitted_quiz,
    db_scope,
    inline_report_submit,
    ai_report,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """报告链只读已有题库，**从不重新取材**（`add-web-search-grounding` design D11）。

    取材只属于出题链：全仓 `SearchProvider.gather()` 只有 `quiz_service` 一个调用点。
    报告复用同一份依据，靠的是出题时落进 `quizzes.references` 的快照。

    做法：把取材 Provider 的工厂换成一个「一被调用就断言失败」的探针，
    再走完整条报告路径（首次生成 + `force=true` 重新生成）。
    将来若有人在报告链里顺手加一次「重新搜一下更准」的取材，这条用例会立刻红 ——
    而不是等到线上发现「报告里的说法和题目对不上」。
    """
    from app.services import quiz_service

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "报告链不该调用取材 Provider：报告只复述已有题库（design D11）"
        )

    monkeypatch.setattr(quiz_service, "get_search_provider", _boom)

    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    first = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    _poll_report(db_client, auth_headers, first["task_id"])

    forced = _generate_report(db_client, auth_headers, attempt["attempt_id"], force=True)
    _poll_report(db_client, auth_headers, forced["task_id"])

    # 走到这里即「探针一次都没被触发」；再确认两次都真的产出了报告
    assert len(ai_report.calls) == 2


def test_report_service_has_no_search_coupling() -> None:
    """静态兜底：`report_service` 里不该出现任何取材相关的符号。

    上一条是运行时的，只覆盖跑到的分支；这一条覆盖**没跑到的分支** ——
    将来在 `report_service` 里新加一条「补充资料」的路径，即使测试没走到，
    这里也会因为出现 `gather` / `get_search_provider` 而失败。
    """
    import inspect

    from app.services import report_service

    source = inspect.getsource(report_service)
    for symbol in ("get_search_provider", ".gather(", "SearchProvider", "SearchRequest"):
        assert symbol not in source, f"report_service 不该耦合取材：出现了 {symbol}"


# -----------------------------------------------------------------------------
# 降级：AI 全失败 → 模板报告，而不是报错
# -----------------------------------------------------------------------------
def test_ai_failure_degrades_to_template_instead_of_erroring(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """报告是「复述已知数据」，模型失败时模板仍然是一份真话 —— 所以降级而非报错。

    这里模拟的是真实链「全部尝试失败」的那个出口：用 `build_template_draft(facts)`
    拼一份模板、并标记 `degraded=True`。用真实的兜底函数而不是手写一份草稿，
    是为了让「兜底产物长什么样」这件事只有一处定义。
    """
    from app.llm import report_chain

    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))

    def _all_failed(
        *, topic, quiz_json, answer_records, score_summary, facts, settings=None, llm_factory=None
    ):  # noqa: ANN001, ANN202, E501
        return report_chain.build_template_draft(facts), True

    monkeypatch.setattr(report_chain, "generate_report_draft", _all_failed)

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    report = _poll_report(db_client, auth_headers, created["task_id"])["report"]

    assert report["degraded"] is True
    # 模板里仍是真话：全对一局应该如实说「全部答对」，而不是编造薄弱点
    assert report["weak_points"] == []
    assert report["three_line_summary"][0].startswith("这次一共 5 道题")
    assert report["accuracy"] == 100

    row = db_session.query(ReportRow).one()
    assert row.status == "ready"
    assert row.model.startswith("template")


# -----------------------------------------------------------------------------
# 动作按真实事实挂
# -----------------------------------------------------------------------------
def test_wrong_answer_attaches_retry_action_pointing_at_real_question(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """有错题时，第一条建议挂「立即重做」，且指向真正答错的那道题。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _one_wrong(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    report = _poll_report(db_client, auth_headers, created["task_id"])["report"]

    first = report["advice"][0]["action"]
    assert first["kind"] == "retry_question"
    assert first["label"] == "立即重做"
    assert first["question_id"] == quiz.questions[0].id
    # 第二条是「已加入复习计划」状态胶囊，第三条是「召唤新副本」
    assert report["advice"][1]["action"]["kind"] == "review_plan"
    assert report["advice"][2]["action"]["kind"] == "new_scroll"


def test_all_correct_does_not_offer_retry(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """全对时没有错题可重做 —— 挂一个「立即重做」就是在骗用户。

    此时唯一成立的动作是「召唤新副本」，它落在**第一条**建议上；
    后两条没有动作（`action=None`）—— 宁可不给按钮，也不给一个点了没反应的。
    """
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    report = _poll_report(db_client, auth_headers, created["task_id"])["report"]

    kinds = [item["action"]["kind"] if item["action"] else None for item in report["advice"]]
    assert kinds == ["new_scroll", None, None]


# -----------------------------------------------------------------------------
# 落库
# -----------------------------------------------------------------------------
def test_report_row_is_written_for_current_user(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report,
    db_session, current_user_id: int,
) -> None:
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    _poll_report(db_client, auth_headers, created["task_id"])

    row = db_session.query(ReportRow).one()
    assert int(row.attempt_id) == int(attempt["attempt_id"])
    assert int(row.user_id) == current_user_id
    assert row.status == "ready"
    assert len(row.summary_lines) == 3
    assert row.error_code is None


def test_report_row_stores_narrative_only(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report, db_session
) -> None:
    """`reports` 表只存叙述：不存统计数字（那是 `attempts` 的），也不存动作。

    动作每次读取时按事实重算 —— 存一份下来，等错题被复习掉之后就变成了假话。
    """
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _one_wrong(quiz))
    ai_report()

    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    _poll_report(db_client, auth_headers, created["task_id"])

    row = db_session.query(ReportRow).one()
    # 表里根本没有统计列（schema 层面保证），这里断言的是「没被塞进 JSON 列」
    for item in row.suggestions:
        assert set(item) == {"title", "body"}, "建议里只该存文案，动作不落库"
    assert not hasattr(row, "accuracy")
    assert not hasattr(row, "coins_gained")


def test_reused_report_recomputes_actions_from_current_facts(
    db_client, auth_headers, submitted_quiz, db_scope, inline_report_submit, ai_report
) -> None:
    """复用旧报告时动作仍按**当前**事实重算，而不是沿用落库时的判断。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()

    first = _generate_report(db_client, auth_headers, attempt["attempt_id"])
    report = _poll_report(db_client, auth_headers, first["task_id"])["report"]

    # 库里没有 action 字段，但读出来必须有 —— 说明它是现算的
    kinds = [item["action"]["kind"] if item["action"] else None for item in report["advice"]]
    assert kinds == ["new_scroll", None, None]


# -----------------------------------------------------------------------------
# 参数校验与鉴权
# -----------------------------------------------------------------------------
def test_missing_token_returns_401(db_client, submitted_quiz) -> None:
    quiz, _ = submitted_quiz()

    resp = db_client.post(REPORT_URL, json={"attempt_id": "1"})

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_non_numeric_attempt_id_returns_4000(db_client, auth_headers) -> None:
    resp = db_client.post(REPORT_URL, json={"attempt_id": "abc"}, headers=auth_headers)

    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_another_users_attempt_returns_4005_same_shape_as_missing(
    db_client, auth_headers, foreign_attempt
) -> None:
    """越权与「不存在」必须逐字节同形，否则错误码差异会泄漏存在性。

    `foreign_attempt` 是**另一个用户自己的**一局 —— 不能拿当前用户的卷轴
    去替另一个用户交卷（那会被 `POST /attempts` 的归属校验挡在 4005，
    于是这个用例就变成在测结算接口，测不到报告接口的归属校验）。
    """
    their = db_client.post(
        REPORT_URL, json={"attempt_id": foreign_attempt["attempt_id"]}, headers=auth_headers
    )
    missing = db_client.post(REPORT_URL, json={"attempt_id": "999999999"}, headers=auth_headers)

    assert their.status_code == 404
    assert their.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert their.json() == missing.json(), "越权与不存在的响应必须逐字节相同"


def test_missing_attempt_returns_4005(db_client, auth_headers) -> None:
    resp = db_client.post(REPORT_URL, json={"attempt_id": "999999999"}, headers=auth_headers)

    assert resp.status_code == 404
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_polling_another_users_report_task_returns_4004(
    db_client, auth_headers, other_auth_headers, submitted_quiz, db_scope, inline_report_submit,
    ai_report,
) -> None:
    """任务归属校验：拿到别人的 task_id 也读不出来，且与「任务不存在」同形。"""
    quiz, _ = submitted_quiz()
    attempt = _submit_attempt(db_client, auth_headers, quiz, _all_correct(quiz))
    ai_report()
    created = _generate_report(db_client, auth_headers, attempt["attempt_id"])

    foreign = db_client.get(f"/api/v1/tasks/{created['task_id']}", headers=other_auth_headers)
    missing = db_client.get("/api/v1/tasks/task_does_not_exist", headers=auth_headers)

    assert foreign.status_code == 404
    assert foreign.json()["code"] == ErrorCode.TASK_NOT_FOUND
    assert foreign.json()["code"] == missing.json()["code"]
