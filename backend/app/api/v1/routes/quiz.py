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

from app.api.deps import CurrentUser, DbSession
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

    # 本次召唤要不要让 AI 主动去网上搜。**默认开启**：用户来问「很新的知识」时，
    # 联网是唯一能让题目基于训练数据之外的资料的办法，所以「不联网」才是需要
    # 用户主动表达的那个例外（大厅那只 pill 就是它的控制面）。
    #
    # ⚠️ 它是**意愿**，不是能力：后端有没有配好检索是另一回事。两者都满足才会真的联网，
    # 前端按这两件事的组合显示四种文案（见 `frontend/src/pages/hall/index.tsx`）。
    #
    # ⚠️ 它**压不住用户自己贴的链接** —— 输入里给了链接就一定会去读那次（design D4）。
    # 语义是「别主动去搜」，不是「别碰网络」。文案必须说清这一点，否则开关就在说谎。
    use_search: bool = Field(default=True, description="是否让 AI 联网补充资料（不影响读取你给的链接）")

    # 本次出题去哪个知识库取材。**可选**：不带就是原来的行为，一个字都不变。
    #
    # ⚠️ 归属校验发生在服务层、且在建任务**之前**（design D13）——
    # 越权 / 不存在会直接返 4005，不会先给一个注定失败的 task_id。
    #
    # `ge=1` 是刻意的：`kb_id=0` / 负数一律 4000 拒掉。静默当成「没传」
    # 是最糟的处理 —— 用户以为自己选了某个库，结果出题用的是默认库。
    kb_id: int | None = Field(default=None, ge=1, description="知识库 id；不传则不使用知识库")

    # 本次召唤要不要给题目配图。**默认关闭**，与 `use_search` 的默认恰好相反 ——
    # 理由不同：联网是「几乎总能帮上忙」，而配图会额外花钱（生图 + 对象存储），
    # 所以该由用户主动要。默认 `false` 还有个硬作用：不传该字段的调用方
    # （含所有既有测试与 `scripts/verify_*.py`）行为逐位不变。
    #
    # ⚠️ 它是**意愿**，不是能力。开关关着 / 缺百炼 key / 缺 COS 凭据时，
    # 传 `true` 会被 4001 拒掉（而不是默默忽略）—— 默默忽略更糟：
    # 用户以为开了配图，拿到题目才发现一张图都没有，界面还不给任何解释。
    generate_images: bool = Field(default=False, description="是否给题目生成配图")


@router.post("/quiz/generate", summary="创建出题任务")
def create_quiz_task(payload: QuizGenerateRequest, user: CurrentUser, db: DbSession) -> dict:
    """校验输入并创建异步出题任务，立刻返回 `task_id` 与轮询间隔。

    `db` 只用于 `kb_id` 的归属校验与配图额度的预扣（design D13 / D6）——
    校验与预扣通过后，真正取资料与生图都发生在后台线程里（那时另有自己的会话）。
    """
    submission = quiz_service.submit_quiz_request(
        user_id=int(user.id),
        user_input=payload.user_input,
        question_count=payload.question_count,
        difficulty=payload.difficulty,
        use_search=payload.use_search,
        kb_id=payload.kb_id,
        generate_images=payload.generate_images,
        session=db,
    )
    return ok(submission.as_data())
