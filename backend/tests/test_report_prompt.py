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

## v2 新增（`add-web-search-grounding` 第 9 组，design D11）

v2 **只加一条约束，其余一个字不动** —— 因为报告链吃的是「已被资料约束过的题库」，
真正的取材风险在出题链就处理完了。新增的是：

> **三句话总结不得引入本次题库之外的新知识。**

它防的不是幻觉，而是**越界补课**：模型看到「向量检索」这个知识点，顺手把
训练数据里关于向量数据库的一堆东西写进总结，用户会以为自己学过。

同一节还要钉住两条**存量**契约（本次没改，但正是最容易被顺手破坏的）：

1. `REPORT_HUMAN_TEMPLATE` 的变量集合**只允许**那四个 —— 尤其不许出现 `reference`。
   第三方原文**不进**报告 Prompt（D11）：报告是**复述**，塞原文只增加不确定性，
   还会让输入体积不可控。
2. 统计数字字段名（`accuracy` 等）仍**不得**出现在 System Prompt 里。
"""

from __future__ import annotations

import re

import pytest
from langchain_core.prompts import ChatPromptTemplate

from app.prompts.quiz_prompt import REFERENCE_BEGIN, REFERENCE_END
from app.prompts.report_prompt import (
    REPORT_ADVICE_COUNT,
    REPORT_HUMAN_TEMPLATE,
    REPORT_PROMPT_VERSION,
    REPORT_SUMMARY_LINES,
    REPORT_SYSTEM_PROMPT,
    build_report_prompt,
)


def _flat(text: str) -> str:
    """把换行与连续空白压成单个空格 —— 断言不受排版换行影响。"""
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------- 版本化
def test_prompt_is_versioned() -> None:
    assert REPORT_PROMPT_VERSION == "v2"


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
    ["accuracy", "xp_gained", "coins_gained", "progress", "avg_duration_ms"],
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


# ---------------------------------------------------------------- v2 来源受限（D11）
def test_summary_must_not_introduce_new_knowledge() -> None:
    """三句话总结只能复述本次题库 —— 越界补课会让用户以为自己学过。"""
    flat = _flat(REPORT_SYSTEM_PROMPT)
    assert re.search(r"不得引入[^。]{0,20}(新知识|新名词|新结论|没考到)", flat)
    assert re.search(r"(只能来自|只能取自|仅限于|限于)[^。]{0,10}(本次)?题库", flat)


def test_points_are_limited_to_quiz_knowledge_points() -> None:
    """掌握点 / 薄弱点必须是**本次题库**里的知识点标签，不许自己造。"""
    flat = _flat(REPORT_SYSTEM_PROMPT)
    assert re.search(r"mastered_points[^。]{0,60}知识点标签", flat)
    assert re.search(r"weak_points[^。]{0,60}知识点标签", flat)
    assert re.search(r"(不要凭空写出|不要为了凑数编)[^。]{0,20}(知识点|薄弱点)", flat)


def test_human_template_slot_set_is_exactly_the_four_known() -> None:
    """四个槽位之外一个都不许有 —— 尤其不许出现 `reference`（D11：第三方原文不进报告）。"""
    slots = set(re.findall(r"\{(\w+)\}", REPORT_HUMAN_TEMPLATE))
    assert slots == {"topic", "quiz_json", "answer_records", "score_summary"}


def test_report_prompt_carries_no_reference_delimiters() -> None:
    """报告链**不复用**出题链的资料定界标记 —— 它压根不给第三方原文。"""
    for marker in (REFERENCE_BEGIN, REFERENCE_END):
        assert marker not in REPORT_SYSTEM_PROMPT
        assert marker not in REPORT_HUMAN_TEMPLATE


def test_stats_field_names_still_absent_after_v2_upgrade() -> None:
    """v2 只加约束，不许顺手把统计字段挪回来（存量契约，回归用）。

    `percentile` 已随该字段的删除换成 `progress`（2026-09-23）：留着一个指向
    已不存在字段的断言，看着绿、实际什么都没守着。
    """
    for field in ("accuracy", "xp_gained", "coins_gained", "progress", "avg_duration_ms"):
        assert field not in REPORT_SYSTEM_PROMPT
