"""题库领域模型（Pydantic v2）。

这一层是**出题链的质量闸门**：AI 返回的任何脏数据在进入业务层之前必须被拦下。
所有约束都用 Pydantic 的校验器表达，失败即抛 `ValidationError`，
由上层转成 5001 并触发重试。

## 选项与答案的约定

| 题型 | 选项数 | 选项 key | 答案 |
|---|---|---|---|
| `single` 单选 | 3–5（Prompt 要求 4，与原型一致） | `A`/`B`/`C`/`D`… | 恰好 1 个 |
| `multiple` 多选 | 3–5（Prompt 要求 4） | `A`/`B`/`C`/`D`… | ≥2 个，且不能覆盖全部选项 |
| `judge` 判断 | **恰好 2** | **固定 `T` / `F`** | 恰好 1 个 |

判断题的 key 固定为 `T`/`F`，前端据此渲染 ✓/✗
（原型要求「选项键改用符号而非字母，减少一次语义转换」）。

## 派生字段

`question_stats` 与 `knowledge_points` 都是**派生字段**，
由后端从 `questions` 计算，用于直接驱动原型「副本确认页」的题型构成与知识点 chip，
前端不做二次计算。调用方传进来的值会被忽略（`knowledge_points` 除外：显式传入时以调用方为准）。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MIN_QUESTIONS = 3
MAX_QUESTIONS = 5

MIN_OPTIONS = 3
MAX_OPTIONS = 5

JUDGE_KEYS: frozenset[str] = frozenset({"T", "F"})

# 非空字符串：自动去首尾空白，且不得为空
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

QuestionType = Literal["single", "multiple", "judge"]
Difficulty = Literal["easy", "medium", "hard"]
SourceType = Literal["text", "pdf", "web", "video"]


class Option(BaseModel):
    """一个选项。"""

    model_config = ConfigDict(extra="ignore")

    key: NonEmptyStr = Field(description="选项键，如 A/B/C/D；判断题为 T/F")
    text: NonEmptyStr = Field(description="选项文字")


class Question(BaseModel):
    """一道题。"""

    model_config = ConfigDict(extra="ignore")

    id: NonEmptyStr = Field(description="题号，题库内唯一，如 q1")
    type: QuestionType = Field(description="题型")
    stem: NonEmptyStr = Field(description="题干")
    options: list[Option] = Field(min_length=2, max_length=6, description="选项列表")
    answer: list[NonEmptyStr] = Field(min_length=1, description="正确答案的选项键列表")
    explanation: NonEmptyStr = Field(description="解析讲解")
    knowledge_point: NonEmptyStr = Field(description="知识点标签")
    difficulty: Difficulty = Field(description="难度")

    @model_validator(mode="after")
    def _validate_answer_consistency(self) -> "Question":
        """答案与选项、题型之间的交叉校验。"""
        keys = [o.key for o in self.options]

        # 1) 选项 key 必须唯一，否则判题逻辑会错乱
        if len(set(keys)) != len(keys):
            raise ValueError("选项 key 必须唯一")

        key_set = set(keys)

        # 2) answer ⊆ options.keys
        unknown = [a for a in self.answer if a not in key_set]
        if unknown:
            raise ValueError(f"answer 含不在选项中的 key: {unknown}；可用 key 为 {sorted(key_set)}")

        # 3) answer 不能有重复项
        if len(set(self.answer)) != len(self.answer):
            raise ValueError("answer 不能有重复项")

        n_options = len(self.options)
        n_answers = len(self.answer)

        # 4) 分题型校验
        if self.type == "single":
            if n_answers != 1:
                raise ValueError("单选题必须有且仅有 1 个正确答案")
            if not (MIN_OPTIONS <= n_options <= MAX_OPTIONS):
                raise ValueError(f"单选题选项数必须为 {MIN_OPTIONS}-{MAX_OPTIONS}，当前 {n_options}")

        elif self.type == "multiple":
            if n_answers < 2:
                raise ValueError("多选题至少需要 2 个正确答案")
            if n_answers >= n_options:
                raise ValueError("多选题不能把所有选项都设为正确答案")
            if not (MIN_OPTIONS <= n_options <= MAX_OPTIONS):
                raise ValueError(f"多选题选项数必须为 {MIN_OPTIONS}-{MAX_OPTIONS}，当前 {n_options}")

        elif self.type == "judge":
            if n_options != 2:
                raise ValueError(f"判断题必须恰好 2 个选项，当前 {n_options}")
            if key_set != JUDGE_KEYS:
                raise ValueError(
                    f"判断题选项 key 必须为 T 与 F（分别表示正确/错误），当前 {sorted(key_set)}"
                )

        return self

    @property
    def max_xp(self) -> int:
        """该题满分经验值。规则见 docs/MVP开发计划.md §9.1。"""
        return {"single": 40, "multiple": 60, "judge": 20}[self.type]


class QuestionStats(BaseModel):
    """题型构成。用于驱动原型「副本确认页」的「3 单选 · 1 多选 · 1 判断」。"""

    model_config = ConfigDict(extra="ignore")

    single: int = Field(default=0, ge=0, description="单选题数量")
    multiple: int = Field(default=0, ge=0, description="多选题数量")
    judge: int = Field(default=0, ge=0, description="判断题数量")

    @property
    def total(self) -> int:
        return self.single + self.multiple + self.judge

    def summary_text(self) -> str:
        """原型确认页的题型构成文案，如「3 单选 · 1 多选 · 1 判断」。"""
        parts = []
        if self.single:
            parts.append(f"{self.single} 单选")
        if self.multiple:
            parts.append(f"{self.multiple} 多选")
        if self.judge:
            parts.append(f"{self.judge} 判断")
        return " · ".join(parts)


class Quiz(BaseModel):
    """一份题库。"""

    model_config = ConfigDict(extra="ignore")

    quiz_id: NonEmptyStr = Field(description="题库 ID")
    title: NonEmptyStr = Field(description="题库标题，如「RAG 入门闯关」")
    summary: NonEmptyStr = Field(description="一句话摘要，用于副本确认页")
    source_type: SourceType = Field(default="text", description="资料来源类型")
    user_input: str = Field(default="", description="用户原始输入")
    question_stats: QuestionStats = Field(
        default_factory=QuestionStats, description="题型构成（派生字段）"
    )
    knowledge_points: list[NonEmptyStr] = Field(
        min_length=1, description="知识点标签（派生字段）"
    )
    questions: list[Question] = Field(
        min_length=MIN_QUESTIONS,
        max_length=MAX_QUESTIONS,
        description=f"题目列表，{MIN_QUESTIONS}–{MAX_QUESTIONS} 道",
    )

    @model_validator(mode="before")
    @classmethod
    def _derive_from_questions(cls, data: object) -> object:
        """从题目派生 `question_stats` 与 `knowledge_points`。

        - `question_stats` **总是**由题目重算，调用方传入的值会被忽略（保证永不自相矛盾）
        - `knowledge_points` 仅在为 `None` 时派生；显式传入（含空列表）时以调用方为准
        """
        if not isinstance(data, dict):
            return data

        questions = data.get("questions") or []
        if not questions:
            return data

        def field_of(q: object, name: str) -> object:
            if isinstance(q, dict):
                return q.get(name)
            return getattr(q, name, None)

        # ---- 题型构成 ----
        stats = {"single": 0, "multiple": 0, "judge": 0}
        for q in questions:
            qtype = field_of(q, "type")
            if qtype in stats:
                stats[qtype] += 1
        data["question_stats"] = stats

        # ---- 知识点：去重且保持首次出现顺序 ----
        if data.get("knowledge_points") is None:
            seen: set[str] = set()
            points: list[str] = []
            for q in questions:
                kp = field_of(q, "knowledge_point")
                if isinstance(kp, str):
                    kp = kp.strip()
                    if kp and kp not in seen:
                        seen.add(kp)
                        points.append(kp)
            data["knowledge_points"] = points

        return data

    @model_validator(mode="after")
    def _validate_question_ids(self) -> "Quiz":
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"题号（id）不能重复，当前为 {ids}")
        return self

    @property
    def total_xp(self) -> int:
        """本局满分经验值。"""
        return sum(q.max_xp for q in self.questions)

    def find_question(self, question_id: str) -> Question | None:
        for q in self.questions:
            if q.id == question_id:
                return q
        return None


def build_quiz(
    *,
    quiz_id: str,
    title: str,
    summary: str,
    source_type: SourceType = "text",
    user_input: str = "",
    questions: list[Question | dict],
    question_stats: QuestionStats | dict | None = None,
    knowledge_points: list[str] | None = None,
) -> Quiz:
    """构造 `Quiz` 的便捷入口。

    `question_stats` 与 `knowledge_points` 会按 `Quiz` 的派生规则处理，
    因此调用方（LLM 链）不必自己算题型构成。
    """
    return Quiz(
        quiz_id=quiz_id,
        title=title,
        summary=summary,
        source_type=source_type,
        user_input=user_input,
        questions=questions,
        question_stats=question_stats if question_stats is not None else QuestionStats(),
        knowledge_points=knowledge_points,
    )
