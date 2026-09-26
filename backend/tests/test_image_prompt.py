"""生图提示词构建（`add-question-image-generation` 第 3 组）。

**这个文件守的是「不泄题」**：配图是永久留在题目里的，一旦把正确答案画进画面，
这道题就废了，而从界面上看不出任何异常。所以每条规则都要被断言钉住。
"""

from __future__ import annotations

import pytest

from app.llm.image import prompt as prompt_builder
from app.models.quiz import Question

from tests.conftest import SAMPLE_QUESTIONS


def _question(**overrides: object) -> Question:
    base = {
        "id": "q1",
        "type": "single",
        "stem": "RAG 的核心思路是什么？",
        "options": [
            {"key": "A", "text": "先检索相关资料，再把资料交给模型生成回答"},
            {"key": "B", "text": "把模型参数调大以获得更多知识"},
            {"key": "C", "text": "只用关键词匹配返回链接列表"},
        ],
        "answer": ["A"],
        "explanation": "RAG 先检索外部资料，再让模型基于资料作答。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "easy",
    }
    base.update(overrides)
    return Question.model_validate(base)


# ---------------------------------------------------------------- 基本形状
def test_prompt_contains_knowledge_point_and_topic() -> None:
    q = _question()
    text = prompt_builder.build_prompt(q)

    assert "RAG 基本定义" in text
    # 主题词来自题干（剥掉「是什么」这类模板之后剩下的部分）
    assert "RAG" in text
    assert prompt_builder.topic_of(q)


def test_prompt_forbids_text_in_image() -> None:
    """「画面不出现文字」必须显式写进提示词。

    它是唯一能约束画面的手段（模型端只能靠它 + 负向提示词），
    而画面出现文字几乎必然泄题（题面、选项、答案都可能在文字里）。
    """
    text = prompt_builder.build_prompt(_question())

    assert "不得出现任何文字" in text
    assert "字母" in text
    assert "标志" in text


def test_prompt_asks_for_neutral_illustration() -> None:
    """中性示意：不画试卷 / 选项列表 / 对勾叉号 —— 它们暗示正确答案。"""
    text = prompt_builder.build_prompt(_question())

    assert "不表达对错" in text
    assert "选项列表" in text


# ---------------------------------------------------------------- 不泄题（核心）
def test_prompt_hides_answer_object_written_in_stem() -> None:
    """「下面哪个是苹果」这类题：苹果是答案，也是选项，绝不能进提示词。

    这一条是本功能最容易出的严重问题：只按题干构建提示词时，
    「苹果」会直接进画面 —— 等于把答案画出来。
    """
    q = _question(
        stem="下面哪个是苹果？",
        options=[
            {"key": "A", "text": "苹果"},
            {"key": "B", "text": "香蕉"},
            {"key": "C", "text": "橘子"},
        ],
        answer=["A"],
        knowledge_point="常见水果识别",
    )
    text = prompt_builder.build_prompt(q)

    for label in ("苹果", "香蕉", "橘子"):
        assert label not in text, f"选项文字 {label!r} 出现在了提示词里"
    # 主题被抹空之后必须回退成知识点，而不是把模板骨架当成画面内容
    assert "常见水果识别" in text
    assert prompt_builder.topic_of(q) == ""


@pytest.mark.parametrize("payload", SAMPLE_QUESTIONS, ids=[q["id"] for q in SAMPLE_QUESTIONS])
def test_prompt_never_contains_option_texts(payload: dict) -> None:
    """对**每一个**样本题目断言：任何选项文字都不在提示词里。

    比「只测一个特例」可靠：选项文字出现在题干里这件事与题型无关，
    而一旦出现就必须被抹掉。
    """
    q = Question.model_validate(payload)
    text = prompt_builder.build_prompt(q)

    for option in q.options:
        label = option.text.strip()
        # 判断题的「正确 / 错误」是**故意**不抹的（它们不是画面里的东西），
        # 所以这里与实现保持同一套豁免规则。
        if len(label) >= 2 and label.lower() not in prompt_builder._JUDGE_LABELS:
            assert label not in text, f"选项文字 {label!r} 出现在了提示词里"


def test_prompt_does_not_use_explanation() -> None:
    """解析不进提示词：它通常包含答案的完整说明，是比选项更直接的泄题源。"""
    q = _question(explanation="解析里的独门措辞巧克力香蕉")
    text = prompt_builder.build_prompt(q)

    assert "解析里的独门措辞巧克力香蕉" not in text


def test_judge_labels_are_not_stripped_from_stem() -> None:
    """判断题的「正确 / 错误」不做抹除：它们不是画面里的东西，抹掉只会误伤题干。"""
    q = _question(
        stem="下列说法正确的一项是？",
        type="judge",
        options=[{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}],
        answer=["T"],
        knowledge_point="命题判定",
    )
    # 剥掉「下列说法」之后应当还留着「正确的一项」，而不是被抹成「的一项」
    assert "正确" in prompt_builder.topic_of(q)


# ---------------------------------------------------------------- 边界
def test_topic_is_bounded() -> None:
    """题干很长时主题词要截断：画面描述越短越可控。"""
    q = _question(stem="生物学里的细胞结构" + "很长的题干" * 60 + "？")
    topic = prompt_builder.topic_of(q)

    assert len(topic) <= prompt_builder._MAX_TOPIC_CHARS


def test_prompt_is_bounded() -> None:
    q = _question(knowledge_point="知识点" * 200, stem="题干" * 200)
    assert len(prompt_builder.build_prompt(q)) <= prompt_builder.MAX_PROMPT_CHARS


def test_constraints_survive_absurdly_long_input() -> None:
    """超长输入**不得把约束条款截掉**。

    约束条款在提示词尾部。如果只靠「整段截断」来控长度，一个超长知识点
    就能把它们整段切走 —— 而提示词看上去依然「正常」，泄题风险静默回归。
    正确做法是每个可变部分各自有界（主题 60 / 知识点 64），末尾上限只作防呆。
    """
    q = _question(knowledge_point="知识点" * 200, stem="题干" * 200)
    text = prompt_builder.build_prompt(q)

    assert "不得出现任何文字" in text
    assert "不表达对错" in text


def test_knowledge_point_is_bounded() -> None:
    """知识点上限与 `questions.knowledge_point VARCHAR(64)` 一致。"""
    assert prompt_builder._MAX_KNOWLEDGE_POINT_CHARS == 64


def test_topic_empty_when_stem_is_all_template() -> None:
    """整句都是模板（`下面哪个？`）时返回空串，而不是把模板当主题。"""
    q = _question(
        stem="下面哪个？",
        options=[
            {"key": "A", "text": "甲"},
            {"key": "B", "text": "乙"},
            {"key": "C", "text": "丙"},
        ],
    )

    assert prompt_builder.topic_of(q) == ""
    # 主题为空时回退成「只用知识点」，提示词仍然是一句能画的话
    # （不能把空提示词发给上游 —— 那必然 400）
    text = prompt_builder.build_prompt(q)
    assert "RAG 基本定义" in text


def test_prompt_falls_back_when_knowledge_point_is_missing_too() -> None:
    """极端兜底：连知识点都拿不到时也要产出一句能画的话。

    `Question.knowledge_point` 是 NonEmptyStr，所以这条分支在真实数据上走不到 ——
    但它挡的是「空提示词发给上游」这种必然 400 的失败，值得留着并单独覆盖。
    """
    from types import SimpleNamespace

    stub = SimpleNamespace(stem="下面哪个？", knowledge_point="", options=[])
    text = prompt_builder.build_prompt(stub)

    assert "画面主题" in text


def test_strip_templates_peels_multiple_layers() -> None:
    assert prompt_builder.strip_templates("下面关于 RAG 的说法？") == "RAG 的说法"
    assert prompt_builder.strip_templates("（多选）以下哪些属于收益？") == "属于收益"
