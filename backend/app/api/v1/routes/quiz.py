"""出题接口。

`POST /quiz/generate` 只做「校验 + 入队」，**不在这里调用模型** ——
模型调用在后台线程里推进，进度通过 `GET /tasks/{task_id}` 轮询（见 §7.2 / §7.3）。

## 为什么这个接口也要鉴权

题库会落库到 `quizzes` 并归属某个用户（方案 §4.3 的鉴权矩阵）。
不鉴权的话「谁生成的卷轴算谁的」就无从谈起，而卷轴是后续结算、报告、
历史记录的共同起点。入队时把 `user.id` 写进任务归属，轮询端点据此校验。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser
from app.core.response import ok
from app.models.quiz import MAX_QUESTIONS, MIN_QUESTIONS
from app.services import quiz_service
from app.utils.text_cleaner import MAX_INPUT_LEN

router = APIRouter(tags=["quiz"])


class QuizGenerateRequest(BaseModel):
    """出题请求体（§7.2）。"""

    model_config = ConfigDict(extra="ignore")

    # 这里的 max_length 是**原始字符数**的硬上限，只用来挡掉明显异常的请求体；
    # 真正的长度规则（含「空白不算数」）在 `validate_input` 里，失败返回 4001
    # 而不是 4000 —— 因为 4001 的提示语是给用户看的，4000 的是给开发者看的。
    user_input: str = Field(min_length=1, max_length=MAX_INPUT_LEN, description="想学的知识")

    question_count: int = Field(
        default=MAX_QUESTIONS,
        ge=MIN_QUESTIONS,
        le=MAX_QUESTIONS,
        description=f"题量，{MIN_QUESTIONS}–{MAX_QUESTIONS}",
    )

    difficulty: Literal["easy", "medium", "hard", "mixed"] = Field(
        default="mixed", description="难度偏好"
    )


@router.post("/quiz/generate", summary="创建出题任务")
def create_quiz_task(payload: QuizGenerateRequest, user: CurrentUser) -> dict:
    """校验输入并创建异步出题任务，立刻返回 `task_id` 与轮询间隔。"""
    submission = quiz_service.submit_quiz_request(
        user_id=int(user.id),
        user_input=payload.user_input,
        question_count=payload.question_count,
        difficulty=payload.difficulty,
    )
    return ok(submission.as_data())
