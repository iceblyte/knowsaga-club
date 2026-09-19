"""报告链测试（对应 docs/MVP开发计划.md §10 的「AI 失败降级为确定性模板报告」）。

报告链与出题链**只有一处**行为不同，而这一处是这个产品的关键裁决：

| | 全部尝试都失败时 |
|---|---|
| 出题链 | 抛 5001 —— 模板拼出来的题本质是**编造学习材料**，比报错更有害 |
| 报告链 | **降级为确定性模板报告** —— 报告是对已知数据（正确率 / XP / 金币）的复述，模板降级后仍是真话 |

（裁决原文见 MVP开发计划 §6 第 6 条。）

## 这里一个真实请求都不发

理由与出题链相同：DeepSeek 的空响应是**偶发**的，靠真实调用复现等于掷骰子。
链路把 LLM 构造抽成可注入的 `llm_factory`，测试用假 runnable 精确制造每种失败。
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from langchain_core.messages import AIMessage

from app.core.exceptions import AppError, ai_generation_failed
from app.llm import report_chain as rc
from app.models.report import ADVICE_COUNT, SUMMARY_LINES, ReportDraft

TOPIC = "RAG 入门闯关"
QUIZ_JSON = '{"quiz_id": "1", "title": "RAG 入门闯关"}'
RECORDS = "第 1 题（单选）选 C，答对"
SCORE_SUMMARY = "正确率 80%，答对 4 题，答错 1 题"


# -----------------------------------------------------------------------------
# 假 runnable
# -----------------------------------------------------------------------------
class _FakeRunnable:
    def __init__(self, responder: Callable[[int, str], Any], log: list[str], method: str) -> None:
        self._responder = responder
        self._log = log
        self._method = method

    def invoke(self, _payload: Any) -> Any:
        index = len(self._log)
        self._log.append(self._method)
        return self._responder(index, self._method)


def _factory(responder: Callable[[int, str], Any], log: list[str]) -> Callable[[str], _FakeRunnable]:
    def build(method: str) -> _FakeRunnable:
        return _FakeRunnable(responder, log, method)

    return build


def _ok(draft: dict) -> dict:
    return {"raw": AIMessage(content="{}"), "parsed": draft, "parsing_error": None}


def _empty() -> dict:
    return {"raw": AIMessage(content=""), "parsed": None, "parsing_error": None}


def _parse_failed() -> dict:
    return {
        "raw": AIMessage(content="```json\n{不是合法 json}\n```"),
        "parsed": None,
        "parsing_error": ValueError("Expecting value: line 1 column 1"),
    }


# -----------------------------------------------------------------------------
# 输入样本
# -----------------------------------------------------------------------------
def _facts(**overrides: Any) -> rc.ReportFacts:
    base: dict[str, Any] = {
        "total_count": 5,
        "correct_count": 4,
        "wrong_count": 1,
        "accuracy": 80,
        "xp_gained": 180,
        "coins_gained": 32,
        "mastered_points": ("RAG 基本定义", "向量检索"),
        "weak_points": ("RAG 与搜索引擎的边界",),
    }
    base.update(overrides)
    return rc.ReportFacts(**base)


def _draft(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "mastered_points": ["RAG 基本定义"],
        "weak_points": ["RAG 与搜索引擎的边界"],
        "three_line_summary": ["第一句。", "第二句。", "第三句。"],
        "advice": [
            {"title": "重做错题", "body": "再练一遍会更牢。"},
            {"title": "按曲线复习", "body": "已排入复习计划。"},
            {"title": "继续下一张", "body": "换一张卷轴。"},
        ],
    }
    base.update(overrides)
    return base


def _generate(factory: Callable[[str], _FakeRunnable], **overrides: Any):  # noqa: ANN201
    kwargs: dict[str, Any] = {
        "topic": TOPIC,
        "quiz_json": QUIZ_JSON,
        "answer_records": RECORDS,
        "score_summary": SCORE_SUMMARY,
        "facts": _facts(),
        "llm_factory": factory,
    }
    kwargs.update(overrides)
    return rc.generate_report_draft(**kwargs)


# -----------------------------------------------------------------------------
# 主通道直接成功
# -----------------------------------------------------------------------------
def test_primary_success_returns_draft(settings) -> None:
    log: list[str] = []
    draft, degraded = _generate(_factory(lambda i, m: _ok(_draft()), log), settings=settings)

    assert log == ["json_mode"], "首选通道应为 json_mode，与出题链保持一致"
    assert degraded is False
    assert isinstance(draft, ReportDraft)
    assert draft.three_line_summary[0] == "第一句。"


def test_success_keeps_model_wording(settings) -> None:
    """模型给的文案要原样保留 —— 服务层只补缺失，不改写。"""
    log: list[str] = []
    draft, _ = _generate(
        _factory(lambda i, m: _ok(_draft(mastered_points=["模型自己写的标签"])), log),
        settings=settings,
    )
    assert draft.mastered_points == ["模型自己写的标签"]


# -----------------------------------------------------------------------------
# 重试阶梯
# -----------------------------------------------------------------------------
def test_empty_response_then_success(settings) -> None:
    """空响应是瞬时的，换不换通道都一样 —— 重一次就好。"""
    log: list[str] = []
    factory = _factory(lambda i, m: _ok(_draft()) if i >= 1 else _empty(), log)
    draft, degraded = _generate(factory, settings=settings)

    assert log == ["json_mode", "function_calling"], "第 2 次应换降级通道"
    assert degraded is False
    assert len(draft.advice) == ADVICE_COUNT


def test_parse_failure_then_success(settings) -> None:
    log: list[str] = []
    factory = _factory(lambda i, m: _ok(_draft()) if i >= 2 else _parse_failed(), log)
    _, degraded = _generate(factory, settings=settings)

    assert degraded is False
    assert log == ["json_mode", "function_calling", "json_mode"]


def test_invalid_draft_is_retried(settings) -> None:
    """字段条数不对算 `invalid_draft`，不该直接判定整条链失败。"""
    log: list[str] = []
    bad = _draft(three_line_summary=["只有一句。"])
    factory = _factory(lambda i, m: _ok(_draft()) if i >= 1 else _ok(bad), log)
    draft, degraded = _generate(factory, settings=settings)

    assert degraded is False
    assert len(draft.three_line_summary) == SUMMARY_LINES


def test_attempt_order_alternates_channels(settings) -> None:
    """阶梯必须是交替的：同通道连撞对「通道不兼容」毫无办法。"""
    log: list[str] = []
    _generate(_factory(lambda i, m: _empty(), log), settings=settings)

    assert log == ["json_mode", "function_calling", "json_mode", "function_calling"]


# -----------------------------------------------------------------------------
# 降级为确定性模板
# -----------------------------------------------------------------------------
def test_all_failures_degrade_to_template(settings) -> None:
    """**核心裁决**：全失败不抛错，而是产出一份模板报告，并标记 degraded。"""
    log: list[str] = []
    draft, degraded = _generate(_factory(lambda i, m: _empty(), log), settings=settings)

    assert degraded is True, "必须标记为降级产物，否则兜底会变成只有翻日志才知道的事"
    assert isinstance(draft, ReportDraft)
    assert len(draft.three_line_summary) == SUMMARY_LINES
    assert len(draft.advice) == ADVICE_COUNT


def test_template_report_still_contains_real_facts(settings) -> None:
    """模板报告必须是**真话**：正确率、题量都来自服务端事实。"""
    log: list[str] = []
    facts = _facts(total_count=5, correct_count=4, accuracy=80)
    draft, _ = _generate(_factory(lambda i, m: _empty(), log), facts=facts, settings=settings)

    joined = "".join(draft.three_line_summary)
    assert "5" in joined and "4" in joined, f"模板总结里应体现题量与实际答对数，实际为：{joined}"


def test_template_lists_points_from_facts(settings) -> None:
    """模板的掌握 / 薄弱点来自**本次作答**推导，不是凭空写的。"""
    log: list[str] = []
    facts = _facts(mastered_points=("向量检索",), weak_points=("与搜索引擎的边界",))
    draft, _ = _generate(_factory(lambda i, m: _empty(), log), facts=facts, settings=settings)

    assert draft.mastered_points == ["向量检索"]
    assert draft.weak_points == ["与搜索引擎的边界"]


def test_template_does_not_invent_weak_points_when_all_correct(settings) -> None:
    """全对时**绝不能**出现薄弱点 —— 编一个出来是最伤信任的一类假话。"""
    log: list[str] = []
    facts = _facts(correct_count=5, wrong_count=0, accuracy=100, weak_points=())
    draft, _ = _generate(_factory(lambda i, m: _empty(), log), facts=facts, settings=settings)

    assert draft.weak_points == []


def test_template_does_not_claim_mastery_when_all_wrong(settings) -> None:
    log: list[str] = []
    facts = _facts(correct_count=0, wrong_count=5, accuracy=0, mastered_points=())
    draft, _ = _generate(_factory(lambda i, m: _empty(), log), facts=facts, settings=settings)

    assert draft.mastered_points == []


def test_config_error_is_not_swallowed(settings) -> None:
    """未配 Key 这类**配置错误**必须抛出来，不能一直悄悄产出模板报告。

    否则线上会表现为「报告质量一直很差」，而没人知道模型其实一次都没调用成功。
    """

    def raising_factory(_method: str) -> Any:
        raise ai_generation_failed("未配置 DEEPSEEK_API_KEY，无法调用大模型")

    with pytest.raises(AppError) as excinfo:
        _generate(raising_factory, settings=settings)
    assert excinfo.value.code == 5001


# -----------------------------------------------------------------------------
# 时间预算
# -----------------------------------------------------------------------------
def test_budget_stops_remaining_attempts(settings, monkeypatch) -> None:
    """越过总预算就不再发起剩余尝试 —— 快速失败比让用户干等更友好。"""
    log: list[str] = []
    ticks = iter([0.0, 0.0, 999.0, 999.0, 999.0, 999.0])
    monkeypatch.setattr(rc, "_clock", lambda: next(ticks))

    _, degraded = _generate(_factory(lambda i, m: _empty(), log), settings=settings)

    assert degraded is True
    assert len(log) < 4, f"越过预算后不该继续尝试，实际尝试了 {len(log)} 次"


# -----------------------------------------------------------------------------
# 字段完整性兜底（MVP开发计划 §8.4「服务层做字段完整性兜底」）
# -----------------------------------------------------------------------------
def test_empty_points_are_filled_from_facts(settings) -> None:
    """模型返回了合法 JSON 但把知识点留空 —— 用事实补齐，而不是显示空 chip。"""
    log: list[str] = []
    draft, degraded = _generate(
        _factory(lambda i, m: _ok(_draft(mastered_points=[], weak_points=[])), log),
        settings=settings,
    )

    assert degraded is False, "这是字段兜底，不是整条链降级"
    assert draft.mastered_points == ["RAG 基本定义", "向量检索"]
    assert draft.weak_points == ["RAG 与搜索引擎的边界"]


def test_model_weak_points_cleared_when_all_correct(settings) -> None:
    """模型硬说「全对但某处薄弱」时，以事实为准把它清掉。"""
    log: list[str] = []
    facts = _facts(correct_count=5, wrong_count=0, accuracy=100, weak_points=())
    draft, _ = _generate(
        _factory(lambda i, m: _ok(_draft(weak_points=["凭空捏造的薄弱点"])), log),
        facts=facts,
        settings=settings,
    )

    assert draft.weak_points == []


def test_model_mastery_cleared_when_all_wrong(settings) -> None:
    log: list[str] = []
    facts = _facts(correct_count=0, wrong_count=5, accuracy=0, mastered_points=())
    draft, _ = _generate(
        _factory(lambda i, m: _ok(_draft(mastered_points=["凭空捏造的掌握点"])), log),
        facts=facts,
        settings=settings,
    )

    assert draft.mastered_points == []
