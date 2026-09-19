"""报告 Prompt 契约测试 —— TDD 红灯先行。

与出题 Prompt 一样，报告 Prompt 也是「改一个措辞就可能破坏契约」的资产。
除了通用约束（含 "json" 字样 + JSON 示例 + 禁止代码块围栏）之外，
报告 Prompt 还多一条**本项目特有**的硬约束：

> **不许让模型输出正确率、XP、金币这类统计数字。**

原因：那些数字由 `services/scoring.py` 确定性算出并写在 `attempts` 上
（MVP开发计划 §8.4）。如果又让模型在报告里回显一遍，就出现了**两个事实源**，
两者一旦不一致，用户会看到「环上是 85% / 文字说 80%」——
这种自相矛盾的报告比没有报告更糟。所以模型只负责「把已知数据讲成人话」，
统计数字一律由服务端注入。
"""

from __future__ import annotations

import re

import pytest
from langchain_core.prompts import ChatPromptTemplate

from app.prompts.report_prompt import (
    REPORT_ADVICE_COUNT,
    REPORT_PROMPT_VERSION,
    REPORT_SUMMARY_LINES,
    REPORT_SYSTEM_PROMPT,
    build_report_prompt,
)


# ---------------------------------------------------------------- 版本化
def test_prompt_is_versioned() -> None:
    assert REPORT_PROMPT_VERSION == "v1"


# ---------------------------------------------------------------- JSON 硬性要求
def test_prompt_mentions_json_keyword() -> None:
    """DeepSeek 官方要求：使用 JSON Output 时 prompt 中必须出现 "json" 字样。"""
    assert "json" in REPORT_SYSTEM_PROMPT.lower()


def test_prompt_contains_json_structure_example() -> None:
    """必须给出 JSON 结构示例，且字段名与 `models/report.py` 的契约一字不差。"""
    assert "{" in REPORT_SYSTEM_PROMPT and "}" in REPORT_SYSTEM_PROMPT
    for field in (
        "mastered_points",
        "weak_points",
        "three_line_summary",
        "advice",
        "title",
        "body",
    ):
        assert field in REPORT_SYSTEM_PROMPT, f"JSON 示例缺少字段 {field}"


def test_prompt_forbids_markdown_code_fence() -> None:
    assert "```" in REPORT_SYSTEM_PROMPT, "Prompt 应当显式举例说明「不要用 ``` 包裹」"
    assert re.search(r"(不要|禁止|不得)", REPORT_SYSTEM_PROMPT)


def test_prompt_forbids_extra_prose() -> None:
    assert re.search(
        r"(只输出|不要输出|不要添加|仅输出)", REPORT_SYSTEM_PROMPT
    ), "缺少「只输出 JSON」的明确措辞"


# ------------------------------------------------- 统计数字必须由服务端注入
@pytest.mark.parametrize(
    "field",
    ["accuracy", "xp_gained", "coins_gained", "percentile", "avg_duration_ms"],
)
def test_prompt_forbids_echoing_deterministic_stats(field: str) -> None:
    """模型不得输出统计数字 —— 否则同一事实出现两个来源，必然有一天对不上。"""
    assert field not in REPORT_SYSTEM_PROMPT, (
        f"JSON 示例里不该出现统计字段 {field}：它由 scoring 确定性计算，"
        "让模型回显会造成双事实源"
    )


def test_prompt_says_stats_are_provided_by_system() -> None:
    """要明确告诉模型「数字我算好了，你只负责解读」，否则它可能自己再算一遍。"""
    assert re.search(
        r"(已经|已由|由系统|系统(会)?提供|不要(自己)?(重新)?计算)", REPORT_SYSTEM_PROMPT
    )


# ---------------------------------------------------------------- 条数约束
def test_summary_lines_count_is_three() -> None:
    assert REPORT_SUMMARY_LINES == 3
    assert "3" in REPORT_SYSTEM_PROMPT


def test_advice_count_is_three() -> None:
    """原型 03「复习建议」屏恰好三张卡，每张一个可执行动作。"""
    assert REPORT_ADVICE_COUNT == 3


def test_prompt_states_exact_counts() -> None:
    assert re.search(r"(三句|3\s*句|三条|3\s*条)", REPORT_SYSTEM_PROMPT)


# ---------------------------------------------------------------- 内容质量
def test_prompt_demands_chinese() -> None:
    assert "中文" in REPORT_SYSTEM_PROMPT


def test_prompt_forbids_inventing() -> None:
    """报告必须基于真实作答，不能编造未出现的结论。"""
    assert re.search(r"(不要编造|不得编造|不要虚构|真实)", REPORT_SYSTEM_PROMPT)


def test_prompt_requires_advice_to_be_actionable() -> None:
    """原型批注：给出可执行的动作，而不是空泛的鼓励。"""
    assert re.search(r"(可执行|具体|动作|不要空泛|不要泛泛)", REPORT_SYSTEM_PROMPT)


def test_prompt_requires_encouraging_tone() -> None:
    """方案设计 §8.6 要求「清晰、鼓励式，但不要空泛」。"""
    assert re.search(r"鼓励", REPORT_SYSTEM_PROMPT)


def test_prompt_mentions_mobile_readability() -> None:
    """方案设计 §8.6：「总结要适合移动端阅读」。"""
    assert re.search(r"(移动端|手机|短句|精简)", REPORT_SYSTEM_PROMPT)


# ---------------------------------------------------------------- 模板装配
def test_build_report_prompt_returns_template() -> None:
    assert isinstance(build_report_prompt(), ChatPromptTemplate)


def _render(**kwargs: object) -> str:
    defaults: dict[str, object] = {
        "topic": "RAG 入门",
        "quiz_json": '{"questions": []}',
        "answer_records": "[]",
        "score_summary": "正确率 80%",
    }
    defaults.update(kwargs)
    rendered = build_report_prompt().invoke(defaults)
    return "\n".join(str(m.content) for m in rendered.messages)


def test_built_prompt_has_system_and_human() -> None:
    rendered = build_report_prompt().invoke(
        {
            "topic": "RAG 入门",
            "quiz_json": "{}",
            "answer_records": "[]",
            "score_summary": "正确率 80%",
        }
    )
    roles = [m.type for m in rendered.messages]
    assert "system" in roles
    assert "human" in roles


def test_rendered_prompt_carries_all_inputs() -> None:
    """四类输入必须真的进到 prompt 里，否则模型无从分析。"""
    topic = "RAG 入门闯关"
    quiz_json = '{"quiz_id":"1","title":"RAG 入门闯关"}'
    records = "q1 选 A 答对；q2 选 B 答错"
    summary = "正确率 80%，答对 4 题，答错 1 题"
    joined = _render(
        topic=topic,
        quiz_json=quiz_json,
        answer_records=records,
        score_summary=summary,
    )
    for piece in (topic, quiz_json, records, summary):
        assert piece in joined
