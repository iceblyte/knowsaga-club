"""结构化输出的 Schema。

**这一层与 `app/models/quiz.py` 的分工是刻意分开的**：

| | 归属 | 谁负责 |
|---|---|---|
| `Quiz` / `Question` | `models/` | 服务端与前端之间的**接口契约**，字段一个都不能少 |
| `QuizDraft` | 这里 | 模型**结构化输出的形状**，只包含模型真正该产出的字段 |

模型不该产出 `quiz_id`（服务端生成）、也不该产出 `user_input` / `source_type`
（服务端已知）。如果直接把 `Quiz` 当成 `with_structured_output` 的 schema，
就会出现两件坏事：一是模型被迫回显一段它没必要的用户输入（浪费 token 且可能被改写），
二是生成了服务端也不打算用的 ID（还可能与真实 ID 不一致）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.quiz import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    NonEmptyStr,
    Question,
    Quiz,
    build_quiz,
)


class QuizDraft(BaseModel):
    """模型产出的一份题库草稿。

    与 `Quiz` 的差别只有「服务端才知道的字段」：`quiz_id` / `user_input` / `source_type`
    以及派生的 `question_stats`。
    """

    model_config = ConfigDict(extra="ignore")

    title: NonEmptyStr = Field(description="题库标题，如「RAG 入门闯关」")
    summary: NonEmptyStr = Field(description="一句话摘要，用于副本确认页")
    knowledge_points: list[NonEmptyStr] | None = Field(
        default=None,
        description="知识点标签；可由题目派生，模型也可以直接给出",
    )
    questions: list[Question] = Field(
        min_length=MIN_QUESTIONS,
        max_length=MAX_QUESTIONS,
        description=f"题目列表，{MIN_QUESTIONS}–{MAX_QUESTIONS} 道",
    )

    @model_validator(mode="after")
    def _validate_question_ids(self) -> "QuizDraft":
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError(f"题号（id）不能重复，当前为 {ids}")
        return self


class ImageSelectionDraft(BaseModel):
    """配图判断题的模型输出（`add-question-image-generation` 第 18 组）。

    ⚠️ `ids` **没有默认值**，这是刻意的：模型偶尔会漏字段，若给它 `[]` 兜底，
    「模型漏了字段」就会被解读成「一道都不需要配图」—— 用户勾了配图却一张都
    拿不到，而且不报错。现在漏字段会撞 `ValidationError`，
    `selector` 据此回退成「全部配图」（安全的一侧）。
    """

    model_config = ConfigDict(extra="ignore")

    ids: list[str] = Field(
        description="需要配图的题号列表；一道都不需要时为空数组"
    )


def draft_to_quiz(
    draft: QuizDraft,
    *,
    user_input: str,
    source_type: str = "text",
    quiz_id: str | None = None,
    retrieve_hit_count: int = 0,
) -> Quiz:
    """把模型草稿补全成对外契约 `Quiz`。

    Args:
        draft: 通过校验的模型输出。
        user_input: 服务端记录的**原始**输入（不清洗，清洗结果已在 Prompt 中使用）。
        source_type: 资料来源类型。
        quiz_id: 不传则新生成一个。
        retrieve_hit_count: 预留，便于后续在用上检索时把来源信息带进题库。
    """
    from app.utils.id_generator import new_quiz_id

    # 配图只能由服务端生图段写入。`Question.image_url` 是**已声明**的字段，
    # 而 `Question` 是 `extra="ignore"` —— 「ignore」只管未声明的字段，
    # 已声明的字段模型一旦给了就会被收下。所以这里显式清空（design D11）：
    # 不清的话，模型可以编一个图片地址进来，而那是最难查的一类假数据
    # （不报错、界面照常显示一张与本题无关的图）。
    stripped = [
        question.model_copy(update={"image_url": None}) for question in draft.questions
    ]

    return build_quiz(
        quiz_id=quiz_id or new_quiz_id(),
        title=draft.title,
        summary=draft.summary,
        source_type=source_type,  # type: ignore[arg-type]
        user_input=user_input,
        questions=stripped,
        knowledge_points=draft.knowledge_points,
    )
