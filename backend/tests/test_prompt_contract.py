"""Prompt 契约测试（Phase 1.4）—— TDD 红灯先行。

Prompt 是这个产品里**最容易被后续改动破坏、又最难发现**的资产：
改一个措辞可能让题量约束失效、让模型开始输出 Markdown 代码块、或者让答案选项键对不上。
所以把 Prompt 当接口来测。

必须守住的硬约束：
1. **出现 "json" 字样并给出 JSON 结构示例** —— DeepSeek JSON Output 的官方硬性要求，
   缺了会导致 json_mode 直接报错或返回空内容。
2. 题量 3–5 道。
3. 题型构成约束（单选 / 多选 / 判断），与原型确认页的「3 单选 · 1 多选 · 1 判断」一致。
4. 明确禁止 Markdown 代码块与解释性前后缀 —— 否则结构化输出会被 ```json 包裹而解析失败。
5. 判断题的选项 key 必须是 T/F。
6. 单选 4 个选项、多选至少 2 个正确答案、答案必须在选项内。
"""

from __future__ import annotations

import re

import pytest
from langchain_core.prompts import ChatPromptTemplate

from app.prompts.quiz_prompt import (
    QUIZ_MAX_QUESTIONS,
    QUIZ_MIN_QUESTIONS,
    QUIZ_PROMPT_VERSION,
    QUIZ_SYSTEM_PROMPT,
    build_quiz_prompt,
)


# ---------------------------------------------------------------- 版本化
def test_prompt_is_versioned() -> None:
    """Prompt 必须版本化，便于出题质量回归时定位到具体版本。"""
    assert QUIZ_PROMPT_VERSION == "v1"


# ---------------------------------------------------------------- JSON 硬性要求
def test_prompt_mentions_json_keyword() -> None:
    """DeepSeek 官方要求：使用 JSON Output 时 prompt 中必须出现 "json" 字样。"""
    assert "json" in QUIZ_SYSTEM_PROMPT.lower()


def test_prompt_contains_json_structure_example() -> None:
    """必须给出 JSON 结构示例，否则模型不知道该输出哪些字段。"""
    assert "{" in QUIZ_SYSTEM_PROMPT and "}" in QUIZ_SYSTEM_PROMPT
    # 示例里必须体现核心字段名
    for field in ("title", "questions", "stem", "options", "answer", "explanation"):
        assert field in QUIZ_SYSTEM_PROMPT, f"JSON 示例缺少字段 {field}"


def test_prompt_forbids_markdown_code_fence() -> None:
    """禁止 ```json 包裹 —— 否则解析会拿到带围栏的字符串。"""
    lowered = QUIZ_SYSTEM_PROMPT
    assert "```" in lowered, "Prompt 应当显式举例说明「不要用 ``` 包裹」"
    # 必须出现明确的禁止词
    assert re.search(r"(不要|禁止|不得)", lowered), "缺少明确的禁止措辞"


def test_prompt_forbids_extra_prose() -> None:
    """禁止在 JSON 之外输出任何解释性文字。"""
    assert re.search(r"(只输出|不要输出|不要添加|no\s+explanation|仅输出)", QUIZ_SYSTEM_PROMPT)


# ---------------------------------------------------------------- 题量
def test_prompt_states_question_count_bounds() -> None:
    assert str(QUIZ_MIN_QUESTIONS) in QUIZ_SYSTEM_PROMPT
    assert str(QUIZ_MAX_QUESTIONS) in QUIZ_SYSTEM_PROMPT
    assert QUIZ_MIN_QUESTIONS == 3
    assert QUIZ_MAX_QUESTIONS == 5


# ---------------------------------------------------------------- 题型构成
@pytest.mark.parametrize("keyword", ["单选", "多选", "判断"])
def test_prompt_specifies_all_question_types(keyword: str) -> None:
    assert keyword in QUIZ_SYSTEM_PROMPT, f"Prompt 未提及题型：{keyword}"


def test_prompt_uses_english_type_values() -> None:
    """type 字段的取值必须是 single/multiple/judge（与 Pydantic 枚举一致）。"""
    for value in ("single", "multiple", "judge"):
        assert value in QUIZ_SYSTEM_PROMPT, f"Prompt 未说明 type 取值 {value}"


def test_prompt_requires_judge_keys_tf() -> None:
    """判断题 key 必须是 T/F —— 与 models/quiz.py 的校验一致。"""
    assert '"T"' in QUIZ_SYSTEM_PROMPT or "'T'" in QUIZ_SYSTEM_PROMPT
    assert '"F"' in QUIZ_SYSTEM_PROMPT or "'F'" in QUIZ_SYSTEM_PROMPT


def test_prompt_requires_four_options_for_choice_types() -> None:
    """原型里单选/多选都是 4 个选项（A/B/C/D）。"""
    assert re.search(r"4\s*个选项|四个选项|A.{0,3}B.{0,3}C.{0,3}D", QUIZ_SYSTEM_PROMPT)


def test_prompt_requires_multiple_has_at_least_two_answers() -> None:
    assert re.search(r"多选[^。\n]{0,40}(2|两).{0,4}(个|项)", QUIZ_SYSTEM_PROMPT)


def test_prompt_requires_answer_within_options() -> None:
    """明确要求 answer 只能取 options 里的 key，降低结构非法率。"""
    assert re.search(r"(answer|答案)[^。\n]{0,60}(必须|只能|一定是)", QUIZ_SYSTEM_PROMPT)


def test_prompt_requires_explanation() -> None:
    """每道题都要有讲解 —— 原型答题后必然展示讲解卡。"""
    assert "explanation" in QUIZ_SYSTEM_PROMPT
    assert re.search(r"讲解|解析", QUIZ_SYSTEM_PROMPT)


def test_prompt_requires_knowledge_point() -> None:
    assert "knowledge_point" in QUIZ_SYSTEM_PROMPT
    assert re.search(r"知识点", QUIZ_SYSTEM_PROMPT)


def test_prompt_demands_chinese_output() -> None:
    """题干、选项、讲解一律中文（产品是中文学习场景）。"""
    assert re.search(r"中文", QUIZ_SYSTEM_PROMPT)


def test_prompt_forbids_inventing_facts() -> None:
    """抗幻觉：不确定的内容不要编造，避免出题错误。"""
    assert re.search(r"(不要编造|不得编造|不要虚构|基于.{0,10}事实|准确)", QUIZ_SYSTEM_PROMPT)


# ---------------------------------------------------------------- 模板装配
def test_build_quiz_prompt_returns_template() -> None:
    prompt = build_quiz_prompt()
    assert isinstance(prompt, ChatPromptTemplate)


def test_built_prompt_has_system_and_human() -> None:
    prompt = build_quiz_prompt()
    rendered = prompt.invoke(
        {"user_input": "我想学习什么是 RAG", "question_count": 5, "difficulty": "mixed", "reference": ""}
    )
    roles = [m.type for m in rendered.messages]
    assert "system" in roles
    assert "human" in roles


def test_rendered_prompt_contains_user_input() -> None:
    prompt = build_quiz_prompt()
    user_text = "我想学习什么是 RAG，以及它和传统搜索有什么区别"
    rendered = prompt.invoke(
        {"user_input": user_text, "question_count": 5, "difficulty": "mixed", "reference": ""}
    )
    joined = "\n".join(m.content for m in rendered.messages)
    assert user_text in joined


def test_rendered_prompt_contains_question_count() -> None:
    prompt = build_quiz_prompt()
    rendered = prompt.invoke(
        {"user_input": "RAG 入门", "question_count": 4, "difficulty": "mixed", "reference": ""}
    )
    joined = "\n".join(m.content for m in rendered.messages)
    assert "4" in joined


def test_rendered_prompt_without_reference_marks_as_no_retrieval() -> None:
    """MVP 未开启联网检索时，要明确告诉模型「没有外部资料」，避免它假装有出处。"""
    prompt = build_quiz_prompt()
    rendered = prompt.invoke(
        {"user_input": "RAG 入门", "question_count": 5, "difficulty": "mixed", "reference": ""}
    )
    joined = "\n".join(m.content for m in rendered.messages)
    assert re.search(r"(没有|无).{0,10}(外部|检索|参考资料)|未提供", joined)


def test_rendered_prompt_with_reference_includes_it() -> None:
    """开启联网检索后，检索到的资料必须真的进到 prompt 里。"""
    prompt = build_quiz_prompt()
    snippet = "RAG 由 Lewis 等人于 2020 年提出，结合了检索与生成。"
    rendered = prompt.invoke(
        {
            "user_input": "RAG 入门",
            "question_count": 5,
            "difficulty": "mixed",
            "reference": snippet,
        }
    )
    joined = "\n".join(m.content for m in rendered.messages)
    assert snippet in joined
