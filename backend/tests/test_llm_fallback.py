"""出题链兜底测试（对应 docs/MVP开发计划.md §10 的 `test_llm_fallback.py`）。

覆盖：空响应、schema 映射失败、字段缺失、重试后成功、彻底失败 → 5001、
以及「主通道重试 → 降级通道 → 时间预算兜底」这条完整阶梯。

## 为什么这里一个真实请求都不发

DeepSeek 的 JSON Output 是**偶发**返回空内容的（官方已知问题），
靠真实调用去复现这个概率事件，测试会变成掷骰子。
所以链路的 LLM 构造被抽成可注入的 `llm_factory`，
测试用假的 runnable 精确制造每一种失败，验证「第几次尝试用哪个方法」。
真实 API 的连续出题抽验放在 Phase 1.14 的独立脚本里（§10 的约定）。
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from langchain_core.messages import AIMessage

from app.core.exceptions import AppError, ErrorCode
from app.llm import quiz_chain as qc
from app.models.quiz import Quiz

USER_INPUT = "我想学习什么是 RAG，以及它和传统搜索有什么区别"


# -----------------------------------------------------------------------------
# 假 runnable：把「第几次调用返回什么」交给测试决定，并记录实际用了哪个 method
# -----------------------------------------------------------------------------
class _FakeRunnable:
    def __init__(self, responder: Callable[[int, str], dict], log: list[str], method: str) -> None:
        self._responder = responder
        self._log = log
        self._method = method
        self.payloads: list[Any] = []

    def invoke(self, payload: Any) -> dict:
        index = len(self._log)
        self._log.append(self._method)
        self.payloads.append(payload)
        return self._responder(index, self._method)


def _factory(
    responder: Callable[[int, str], dict], log: list[str]
) -> Callable[[str], _FakeRunnable]:
    """构造 `llm_factory`：签名是 (method) -> runnable。"""

    def build(method: str) -> _FakeRunnable:
        return _FakeRunnable(responder, log, method)

    return build


def _ok(draft: dict) -> dict:
    return {"raw": AIMessage(content="{}"), "parsed": draft, "parsing_error": None}


def _empty() -> dict:
    """官方已知问题：思考模式没关干净 / 被推理 token 挤占时，content 为空。"""
    return {"raw": AIMessage(content=""), "parsed": None, "parsing_error": None}


def _parse_failed(message: str = "Expecting value: line 1 column 1") -> dict:
    return {
        "raw": AIMessage(content="```json\n{不是合法 json}\n```"),
        "parsed": None,
        "parsing_error": ValueError(message),
    }


def _calls_until(valid_at: int, draft: dict, log: list[str]) -> Callable[[int, str], dict]:
    """第 `valid_at` 次调用（0 基）之前一直返回空响应，之后成功。"""

    def responder(index: int, _method: str) -> dict:
        return _ok(draft) if index >= valid_at else _empty()

    return responder


# -----------------------------------------------------------------------------
# 主通道直接成功
# -----------------------------------------------------------------------------
def test_primary_success_returns_quiz(settings, sample_draft_payload: dict) -> None:
    log: list[str] = []
    factory = _factory(lambda i, m: _ok(sample_draft_payload), log)

    quiz = qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=factory)

    assert isinstance(quiz, Quiz)
    assert log == ["json_mode"], "首选方法应为 json_mode（实测一次通过率高于 function_calling）"
    assert quiz.title == sample_draft_payload["title"]
    assert quiz.total_xp == 200, "3 单选 + 1 多选 + 1 判断 = 200 XP"
    assert quiz.question_stats.summary_text() == "3 单选 · 1 多选 · 1 判断"


def test_derived_fields_and_server_owned_fields(settings, sample_draft_payload: dict) -> None:
    factory = _factory(lambda i, m: _ok(sample_draft_payload), [])

    quiz = qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=factory)

    # AI 不负责这些字段，由服务端补齐
    assert quiz.quiz_id.startswith("quiz_")
    assert quiz.user_input == USER_INPUT
    assert quiz.source_type == "text"
    # 知识点由题目派生（draft 里 knowledge_points=None）
    assert quiz.knowledge_points == ["RAG 基本定义", "向量检索", "与搜索引擎的边界", "应用场景"]


def test_prompt_carries_user_input_and_question_count(settings, sample_draft_payload: dict) -> None:
    captured: list[Any] = []

    def responder(index: int, _method: str) -> dict:
        return _ok(sample_draft_payload)

    factory = _factory(responder, [])
    # 直接拿假 runnable 的 payload 做断言
    holder: list[_FakeRunnable] = []

    def build(method: str) -> _FakeRunnable:
        r = _FakeRunnable(responder, [], method)
        holder.append(r)
        return r

    qc.generate_quiz(
        user_input=USER_INPUT, question_count=3, difficulty="hard", settings=settings, llm_factory=build
    )
    captured.extend(holder[0].payloads)

    text = captured[0].to_string()
    assert USER_INPUT in text
    assert "3" in text and "hard" in text


# -----------------------------------------------------------------------------
# 默认通道（回归护栏）
# -----------------------------------------------------------------------------
def test_default_channel_is_json_mode(settings) -> None:
    """默认主通道必须是 json_mode。

    这条用例存在的意义：默认值是在实测量化之后（json_mode 6/6 vs function_calling 4/6）
    才调换过来的。没有护栏的话，某次「顺手改回 function_calling」不会让任何测试变红，
    却会把首轮失败率从 0% 抬回 33%。
    """
    assert settings.structured_output_primary == "json_mode"
    assert settings.structured_output_fallback == "function_calling"


def test_attempt_plan_starts_with_configured_primary(settings) -> None:
    plan = qc._attempt_plan(settings)

    assert plan[0] == "json_mode"
    assert len(plan) == 4, "2 + QUIZ_MAX_RETRIES(2)"


# -----------------------------------------------------------------------------
# 降级：空响应
# -----------------------------------------------------------------------------
def test_empty_response_falls_back_to_function_calling(
    settings, sample_draft_payload: dict
) -> None:
    log: list[str] = []
    factory = _factory(_calls_until(1, sample_draft_payload, log), log)

    quiz = qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=factory)

    assert isinstance(quiz, Quiz)
    assert log == ["json_mode", "function_calling"], "空响应后应降级到 function_calling"


# -----------------------------------------------------------------------------
# 重试：schema 映射失败
# -----------------------------------------------------------------------------
def test_parsing_error_switches_method_then_succeeds(settings, sample_draft_payload: dict) -> None:
    """schema 映射失败后，第 2 次会换到降级通道，而不是在同一条通道上再撞一次。"""
    log: list[str] = []

    def responder(index: int, _method: str) -> dict:
        return _parse_failed() if index == 0 else _ok(sample_draft_payload)

    quiz = qc.generate_quiz(
        user_input=USER_INPUT, settings=settings, llm_factory=_factory(responder, log)
    )

    assert isinstance(quiz, Quiz)
    assert log == ["json_mode", "function_calling"], "应尽早换通道"


def test_draft_missing_required_field_is_treated_as_failure(settings) -> None:
    """字段缺失（缺 questions）→ 本轮记为失败，而不是把半个对象递出去。"""
    log: list[str] = []

    def responder(index: int, _method: str) -> dict:
        if index == 0:
            return {"raw": AIMessage(content='{"title":"x"}'), "parsed": {"title": "x"}, "parsing_error": None}
        return _parse_failed("questions: Field required")

    with pytest.raises(AppError) as exc:
        qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=_factory(responder, log))

    assert exc.value.code == ErrorCode.AI_GENERATION_FAILED
    assert len(log) == 4, "默认 2 + QUIZ_MAX_RETRIES(2) = 4 次尝试"


def test_draft_with_too_few_questions_is_treated_as_failure(settings, sample_draft_payload: dict) -> None:
    """题量不足 3 道 —— 即使 JSON 合法也必须拦下（质量闸门）。"""
    from app.llm.output_schemas import QuizDraft

    log: list[str] = []
    short = dict(sample_draft_payload)
    short["questions"] = sample_draft_payload["questions"][:2]

    responder = _calls_until(99, short, log)  # 永远返回同一份非法 draft
    with pytest.raises(AppError) as exc:
        qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=_factory(responder, log))

    assert exc.value.code == ErrorCode.AI_GENERATION_FAILED
    # 确认这份样本确实过不了 schema，否则上面的断言会失去意义
    with pytest.raises(Exception):
        QuizDraft.model_validate(short)


# -----------------------------------------------------------------------------
# 阶梯顺序与次数
# -----------------------------------------------------------------------------
def test_ladder_alternates_primary_and_fallback(settings, sample_draft_payload: dict) -> None:
    log: list[str] = []
    s = settings.model_copy(update={"quiz_max_retries": 2})
    # 第 3 次（index=2）才成功，验证前两次确实分别在两个通道上
    factory = _factory(_calls_until(2, sample_draft_payload, log), log)

    qc.generate_quiz(user_input=USER_INPUT, settings=s, llm_factory=factory)

    assert log == ["json_mode", "function_calling", "json_mode"], (
        "两个通道应交替尝试，而不是在同一条通道上连撞"
    )


def test_ladder_respects_configured_methods(settings, sample_draft_payload: dict) -> None:
    """阶梯的两级都来自配置，换配置不改代码（§2.5 的可切换设计）。

    这里刻意把两条通道**都设成与默认相反**的 function_calling：
    如果实现里悄悄把默认值写死，这条用例就会失败。
    """
    log: list[str] = []
    s = settings.model_copy(
        update={
            "structured_output_primary": "function_calling",
            "structured_output_fallback": "function_calling",
            "quiz_max_retries": 0,
        }
    )
    factory = _factory(lambda i, m: _ok(sample_draft_payload), log)

    qc.generate_quiz(user_input=USER_INPUT, settings=s, llm_factory=factory)

    assert log == ["function_calling"]


# -----------------------------------------------------------------------------
# 彻底失败 → 5001
# -----------------------------------------------------------------------------
def test_all_attempts_fail_raises_5001(settings) -> None:
    log: list[str] = []
    factory = _factory(lambda i, m: _empty(), log)

    with pytest.raises(AppError) as exc:
        qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=factory)

    assert exc.value.code == ErrorCode.AI_GENERATION_FAILED
    assert log == ["json_mode", "function_calling", "json_mode", "function_calling"], (
        "默认共 4 次尝试（2 + QUIZ_MAX_RETRIES），两个通道交替"
    )


def test_5001_message_is_user_readable(settings) -> None:
    factory = _factory(lambda i, m: _empty(), [])

    with pytest.raises(AppError) as exc:
        qc.generate_quiz(user_input=USER_INPUT, settings=settings, llm_factory=factory)

    # 提示语会直接在界面上展示，不能是空串或英文堆栈
    assert exc.value.message
    assert "json" not in exc.value.message.lower()


# -----------------------------------------------------------------------------
# 时间预算兜底
# -----------------------------------------------------------------------------
def test_budget_guard_stops_early(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    """每次尝试都慢时，超过时间预算就停止，不再把剩余尝试打完。"""
    now = {"t": 0.0}
    monkeypatch.setattr(qc, "_clock", lambda: now["t"])

    log: list[str] = []
    s = settings.model_copy(update={"quiz_generation_budget_seconds": 10})

    def responder(_index: int, _method: str) -> dict:
        now["t"] += 6.0  # 每次尝试耗时 6s
        return _empty()

    with pytest.raises(AppError) as exc:
        qc.generate_quiz(user_input=USER_INPUT, settings=s, llm_factory=_factory(responder, log))

    assert exc.value.code == ErrorCode.AI_GENERATION_FAILED
    assert len(log) == 2, f"6s + 6s 已越过 10s 预算，不应发起第 3 次（实际 {log}）"


def test_budget_guard_always_allows_first_attempt(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    """预算为 0 也必须至少发起一次 —— 否则接口会变成永远失败的死路。"""
    now = {"t": 0.0}
    monkeypatch.setattr(qc, "_clock", lambda: now["t"])

    log: list[str] = []
    s = settings.model_copy(update={"quiz_generation_budget_seconds": 0})

    with pytest.raises(AppError):
        qc.generate_quiz(
            user_input=USER_INPUT,
            settings=s,
            llm_factory=_factory(lambda i, m: _empty(), log),
        )

    assert len(log) == 1
