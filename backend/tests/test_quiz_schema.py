"""题库数据结构测试（Phase 1.3）—— TDD 红灯先行。

这一层是**出题链的质量闸门**：AI 返回的脏数据绝不允许外泄到前端，
所有结构性问题必须在 Pydantic 校验阶段被拦下，转成 5001 错误并触发重试。

覆盖点（计划 §10）：
- 字段完整性
- type 枚举
- answer ⊆ options.keys
- 单选答案唯一
- 判断题选项固定 2 项
- 题量 3–5

设计约定：
- 单选/多选：3–5 个选项（Prompt 会要求 4 个，与原型一致；但允许 3–5 以降低重试率）
- 判断题：**固定 2 个选项**，key 为 "T"/"F"，文字为 "正确"/"错误"
- 多选：正确答案至少 2 项，且不能是全部选项（否则退化成单选）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.quiz import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    Option,
    Question,
    QuestionStats,
    Quiz,
    build_quiz,
)


# ------------------------------------------------------------------ 辅助构造
def make_options(n: int = 4) -> list[dict]:
    return [{"key": chr(ord("A") + i), "text": f"选项{i + 1}"} for i in range(n)]


def make_question(**overrides) -> dict:
    base = {
        "id": "q1",
        "type": "single",
        "stem": "RAG 与传统关键词检索最核心的差别是什么？",
        "options": make_options(4),
        "answer": ["C"],
        "explanation": "RAG 按语义相似度召回相关片段。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "medium",
    }
    base.update(overrides)
    return base


def make_quiz(**overrides) -> dict:
    base = {
        "quiz_id": "quiz_test123",
        "title": "RAG 入门闯关",
        "summary": "围绕 RAG 基础概念与应用场景生成的题库",
        "source_type": "text",
        "user_input": "我想学习什么是 RAG",
        # 默认 3 题（题量下限），保证直接构造 Quiz 时不会因题量不足而失败
        "question_stats": {"single": 3, "multiple": 0, "judge": 0},
        "knowledge_points": ["RAG 基本定义"],
        "questions": [
            make_question(id="q1", answer=["A"]),
            make_question(id="q2", answer=["B"]),
            make_question(id="q3", answer=["C"]),
        ],
    }
    base.update(overrides)
    return base


# ================================================================== Option
def test_option_requires_key_and_text() -> None:
    with pytest.raises(ValidationError):
        Option(key="A")
    with pytest.raises(ValidationError):
        Option(text="缺 key")


def test_option_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        Option(key="A", text="   ")


def test_option_strips_text() -> None:
    assert Option(key="A", text="  有空白  ").text == "有空白"


# ================================================================== Question 基本字段
def test_question_parses_valid_payload() -> None:
    q = Question(**make_question())
    assert q.type == "single"
    assert len(q.options) == 4
    assert q.answer == ["C"]


@pytest.mark.parametrize(
    "missing",
    ["id", "type", "stem", "options", "answer", "explanation", "knowledge_point", "difficulty"],
)
def test_question_requires_all_fields(missing: str) -> None:
    """字段完整性：少任何一个都必须报错。"""
    payload = make_question()
    payload.pop(missing)
    with pytest.raises(ValidationError):
        Question(**payload)


def test_question_stem_not_empty() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(stem="   "))


def test_question_explanation_not_empty() -> None:
    """讲解不能为空 —— 原型每道题答完都要展示讲解卡。"""
    with pytest.raises(ValidationError):
        Question(**make_question(explanation="  "))


# ================================================================== type 枚举
def test_question_type_enum_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(type="essay"))


@pytest.mark.parametrize("qtype", ["single", "multiple", "judge"])
def test_question_type_enum_accepts_known(qtype: str) -> None:
    payload = make_question(type=qtype)
    if qtype == "multiple":
        payload["options"] = make_options(4)
        payload["answer"] = ["A", "C"]
    elif qtype == "judge":
        payload["options"] = [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]
        payload["answer"] = ["T"]
    assert Question(**payload).type == qtype


def test_difficulty_enum_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(difficulty="very_hard"))


# ================================================================== answer ⊆ options.keys
def test_answer_must_be_subset_of_option_keys() -> None:
    with pytest.raises(ValidationError) as ei:
        Question(**make_question(answer=["E"]))  # 只有 A-D
    assert "answer" in str(ei.value).lower() or "选项" in str(ei.value)


def test_answer_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(answer=[]))


def test_answer_cannot_have_duplicates() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(answer=["C", "C"]))


def test_option_keys_must_be_unique() -> None:
    """两个选项用同一个 key 会让判题逻辑直接错乱。"""
    with pytest.raises(ValidationError):
        Question(
            **make_question(
                options=[
                    {"key": "A", "text": "甲"},
                    {"key": "A", "text": "乙"},
                ],
                answer=["A"],
            )
        )


# ================================================================== 单选
def test_single_requires_exactly_one_answer() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(type="single", answer=["A", "C"]))


def test_single_option_count_bounds() -> None:
    with pytest.raises(ValidationError):
        Question(**make_question(options=make_options(2), answer=["A"]))
    with pytest.raises(ValidationError):
        Question(**make_question(options=make_options(6), answer=["A"]))
    # 3–5 都合法
    for n in (3, 4, 5):
        opts = make_options(n)
        assert len(Question(**make_question(options=opts, answer=["A"])).options) == n


# ================================================================== 多选
def test_multiple_requires_at_least_two_answers() -> None:
    """只有一个正确答案的多选，本质上还是单选。"""
    with pytest.raises(ValidationError):
        Question(**make_question(type="multiple", answer=["A"]))


def test_multiple_cannot_have_all_options_correct() -> None:
    """全部选项都正确会让题目失去区分度。"""
    with pytest.raises(ValidationError):
        Question(**make_question(type="multiple", options=make_options(4), answer=["A", "B", "C", "D"]))


def test_multiple_valid_payload() -> None:
    q = Question(**make_question(type="multiple", options=make_options(4), answer=["A", "C", "D"]))
    assert q.type == "multiple"
    assert set(q.answer) == {"A", "C", "D"}


# ================================================================== 判断题
def test_judge_requires_exactly_two_options() -> None:
    with pytest.raises(ValidationError):
        Question(
            **make_question(
                type="judge",
                options=make_options(4),
                answer=["A"],
            )
        )


def test_judge_option_keys_must_be_t_and_f() -> None:
    """判断题的 key 固定为 T/F，前端据此渲染 ✓/✗（原型：符号而非字母）。"""
    with pytest.raises(ValidationError):
        Question(
            **make_question(
                type="judge",
                options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
                answer=["A"],
            )
        )


def test_judge_valid_payload() -> None:
    q = Question(
        **make_question(
            type="judge",
            options=[{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}],
            answer=["F"],
        )
    )
    assert q.type == "judge"
    assert len(q.options) == 2


# ================================================================== Quiz 题量
def test_quiz_question_count_bounds() -> None:
    assert MIN_QUESTIONS == 3
    assert MAX_QUESTIONS == 5

    with pytest.raises(ValidationError):
        build_quiz(**make_quiz(questions=[]))
    with pytest.raises(ValidationError):
        build_quiz(**make_quiz(questions=[make_question(id=f"q{i}") for i in range(6)]))


def test_quiz_accepts_min_and_max() -> None:
    for n in (MIN_QUESTIONS, MAX_QUESTIONS):
        qs = [make_question(id=f"q{i}", answer=["A"]) for i in range(n)]
        quiz = build_quiz(**make_quiz(questions=qs))
        assert len(quiz.questions) == n


def test_quiz_question_ids_unique() -> None:
    """题号重复会让作答记录对不上题。题量满足下限，确保失败原因是 id 重复。"""
    qs = [
        make_question(id="q1", answer=["A"]),
        make_question(id="q1", answer=["B"]),
        make_question(id="q3", answer=["C"]),
    ]
    with pytest.raises(ValidationError) as ei:
        build_quiz(**make_quiz(questions=qs))
    assert "id" in str(ei.value).lower() or "题号" in str(ei.value)


# ================================================================== 派生字段
def test_build_quiz_derives_question_stats() -> None:
    """question_stats 必须由后端派生，前端不二次计算（计划 §8.1）。"""
    qs = [
        make_question(id="q1", type="single", answer=["A"]),
        make_question(id="q2", type="single", answer=["B"]),
        make_question(id="q3", type="single", answer=["C"]),
        make_question(id="q4", type="multiple", options=make_options(4), answer=["A", "C"]),
        make_question(
            id="q5",
            type="judge",
            options=[{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}],
            answer=["T"],
        ),
    ]
    quiz = build_quiz(**make_quiz(questions=qs, question_stats={"single": 0, "multiple": 0, "judge": 0}))
    assert quiz.question_stats.single == 3
    assert quiz.question_stats.multiple == 1
    assert quiz.question_stats.judge == 1


def test_build_quiz_derives_knowledge_points() -> None:
    """未显式指定知识点时，从题目聚合、去重、保持首次出现顺序。"""
    qs = [
        make_question(id="q1", knowledge_point="向量检索", answer=["A"]),
        make_question(id="q2", knowledge_point="RAG 基本定义", answer=["B"]),
        make_question(id="q3", knowledge_point="向量检索", answer=["C"]),
    ]
    quiz = build_quiz(**make_quiz(questions=qs, knowledge_points=None))
    assert quiz.knowledge_points == ["向量检索", "RAG 基本定义"]


def test_build_quiz_keeps_explicit_knowledge_points() -> None:
    """已经指定知识点时以调用方为准，不覆盖。"""
    qs = [
        make_question(id="q1", knowledge_point="向量检索", answer=["A"]),
        make_question(id="q2", knowledge_point="语义相似度", answer=["B"]),
        make_question(id="q3", knowledge_point="RAG 基本定义", answer=["C"]),
    ]
    quiz = build_quiz(**make_quiz(questions=qs, knowledge_points=["我指定的", "两个标签"]))
    assert quiz.knowledge_points == ["我指定的", "两个标签"]


def test_knowledge_points_cannot_be_empty() -> None:
    """显式传空列表是调用方的错误，不能静默改成派生。"""
    with pytest.raises(ValidationError):
        build_quiz(**make_quiz(knowledge_points=[]))


def test_question_stats_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        QuestionStats(single=-1, multiple=0, judge=0)


# ================================================================== 序列化
def test_quiz_serializes_to_json_safe_dict() -> None:
    """必须能安全序列化为 JSON（前端直接消费）。"""
    import json

    quiz = build_quiz(**make_quiz())
    payload = json.loads(quiz.model_dump_json())
    assert payload["quiz_id"] == "quiz_test123"
    assert isinstance(payload["questions"], list)
    assert payload["questions"][0]["options"][0]["key"] == "A"


def test_quiz_title_and_summary_not_empty() -> None:
    with pytest.raises(ValidationError):
        Quiz(**make_quiz(title=""))
    with pytest.raises(ValidationError):
        Quiz(**make_quiz(summary="   "))


def test_quiz_source_type_enum() -> None:
    with pytest.raises(ValidationError):
        Quiz(**make_quiz(source_type="audio"))
