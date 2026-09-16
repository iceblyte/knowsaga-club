"""出题服务：把「校验 → 建任务 → 后台出题 → 推进度」串起来。

## 为什么是「建任务 + 后台线程」而不是直接返回结果

小程序单次请求有 60s 上限，而一次出题（含重试）可能到几十秒。同步接口意味着
要么超时失败，要么把用户按在加载动画上赌运气。所以：

    POST /quiz/generate   校验 + 入队，立刻返回 task_id
    GET  /tasks/{id}      轮询，由后端推进度条

这也正是原型「副本召唤中」那张屏（三步状态卡 + 进度条 + 8s 后出取消）需要的形状 ——
进度必须来自后端，前端自己编一个假进度只会在失败时显得格外不可信。

## 进度是「真进度」还是「动画」

是**真实阶段进度**，不是按时间插值。三个阶段的切换点由实际发生的事情决定：
检索真的返回了、题目真的生成了、结构真的校验过了。
唯一带一点估算的是 `estimated_seconds`，它只用于前端展示「大约还要多久」，
不参与任何逻辑判断。
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ErrorCode, DEFAULT_MESSAGES
from app.core.logging import get_logger
from app.llm import quiz_chain
from app.llm.search import SearchProvider, get_search_provider
from app.models.quiz import Quiz
from app.services import task_service
from app.services.task_service import TaskRecord, TaskStep
from app.utils.content_filter import check_content
from app.utils.text_cleaner import validate_input

logger = get_logger(__name__)

#: 出题任务在界面上固定三步（原型「副本召唤中」屏）
STEP_RETRIEVE = "retrieve"
STEP_GENERATE = "generate"
STEP_VALIDATE = "validate"

# 各阶段对应的进度值。数字本身不重要，重要的是必须**单调递增**，
# 否则进度条会往回跳，用户会以为出错了。
_PROGRESS_RETRIEVE = 25
_PROGRESS_GENERATE_DONE = 85
_PROGRESS_VALIDATE = 90
_PROGRESS_DONE = 100

#: 后台执行器。**有界**是关键：无界的线程创建会让一次流量高峰把进程打穿。
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quiz-gen")


def _submit(fn: Callable[[], None]) -> None:
    """把出题函数交给后台线程。测试可替换成同步执行以获得确定性的轮询结果。"""
    _executor.submit(fn)


def estimate_seconds(question_count: int) -> int:
    """给前端的「大约还需要多久」估算。

    只是展示用的提示（原型里是「预计 12 秒」），**不参与逻辑判断**，
    因此这里用一个简单的线性经验式就够了，不需要也不应该做成精确预测。
    """
    return max(8, math.ceil(question_count * 2.4))


@dataclass(frozen=True)
class QuizSubmission:
    """`POST /quiz/generate` 的返回内容（§7.2）。"""

    task_id: str
    status: str
    poll_interval_ms: int
    estimated_seconds: int

    def as_data(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "poll_interval_ms": self.poll_interval_ms,
            "estimated_seconds": self.estimated_seconds,
        }


# -----------------------------------------------------------------------------
# 进度推进
# -----------------------------------------------------------------------------
def _initial_steps(provider: SearchProvider, question_count: int) -> list[TaskStep]:
    """三步状态卡的初始状态。

    第一步的名字来自 Provider：不联网是「理解你的输入」，联网时是「联网检索知识」。
    前端不做这个判断（§7.3），所以它必须在这里就定下来。
    """
    return [
        TaskStep(key=STEP_RETRIEVE, name=provider.step_name, status="pending", detail="准备中"),
        TaskStep(
            key=STEP_GENERATE,
            name="生成闯关题目",
            status="pending",
            detail=f"将生成 {question_count} 道题",
        ),
        TaskStep(key=STEP_VALIDATE, name="校验题目结构", status="pending", detail="等待中"),
    ]


def _advance(
    task_id: str,
    key: str,
    *,
    status: str,
    detail: str | None = None,
    progress: int | None = None,
) -> None:
    """推进某一步的状态与整体进度。

    任务已进入终态（成功 / 失败 / 已取消）时**直接返回**：
    用户点了取消之后，后台残留的进度更新不该继续改写界面。
    """
    record = task_service.get_task_or_none(task_id)
    if record is None or task_service.is_finished(record.status):
        return

    steps: list[TaskStep] = []
    for step in record.steps:
        if step.key == key:
            changes: dict[str, object] = {"status": status}
            if detail is not None:
                changes["detail"] = detail
            steps.append(step.model_copy(update=changes))
        else:
            steps.append(step)

    fields: dict[str, object] = {"steps": steps}
    if progress is not None:
        fields["progress"] = progress
    task_service.update_task(task_id, **fields)


def _finish_failed(task_id: str, code: int, message: str, *, step_key: str = STEP_GENERATE) -> None:
    """把任务标记为失败。**绝不覆盖已取消状态**（用户的选择优先）。"""
    record = task_service.get_task_or_none(task_id)
    if record is None or record.status == "cancelled":
        return

    steps: list[TaskStep] = []
    for step in record.steps:
        if step.key == step_key:
            steps.append(step.model_copy(update={"status": "failed"}))
        elif step.status == "running":
            # 还在跑的步骤已经没有意义了，一起收尾，避免界面停在「进行中」
            steps.append(step.model_copy(update={"status": "failed"}))
        else:
            steps.append(step)

    task_service.update_task(
        task_id,
        status="failed",
        steps=steps,
        error=task_service.TaskError(code=code, message=message),
    )


# -----------------------------------------------------------------------------
# 后台出题
# -----------------------------------------------------------------------------
def run_quiz_generation(
    task_id: str,
    *,
    user_input: str,
    question_count: int,
    difficulty: str,
    settings: Settings | None = None,
    generate: Callable[..., Quiz] | None = None,
    search_provider: SearchProvider | None = None,
) -> None:
    """后台出题主流程。**这个函数不抛异常** —— 任何失败都落到任务的 `failed` 状态上。

    Args:
        task_id: 已创建的任务。
        user_input: 已清洗的输入。
        generate: 注入出题函数（测试用）；不传则用 `quiz_chain.generate_quiz`。
        search_provider: 注入检索 Provider（测试用）；不传则按配置取。
    """
    s = settings or get_settings()
    provider = search_provider or get_search_provider(s)
    # 用 module 属性现取，这样测试 monkeypatch `quiz_chain.generate_quiz` 才会生效
    generate_quiz = generate or quiz_chain.generate_quiz

    record = task_service.get_task_or_none(task_id)
    if record is None or task_service.is_finished(record.status):
        # 任务已过期或已被取消 —— 不要再开工，也不要覆盖任何东西
        logger.info("出题任务 %s 已结束或不存在，跳过执行", task_id)
        return

    try:
        task_service.update_task(task_id, status="running", progress=5)

        # ---- 第一步：检索 / 理解输入 ----
        _advance(task_id, STEP_RETRIEVE, status="running", detail="正在解析你的学习需求", progress=8)
        outcome = provider.search(user_input)
        # 走到这里之前还不知道会提炼出几个概念，先用计划题量给一个即时反馈
        descriptor = outcome.first_step(concept_count=question_count)
        _advance(
            task_id,
            STEP_RETRIEVE,
            status="done",
            detail=descriptor.detail,
            progress=_PROGRESS_RETRIEVE,
        )

        # ---- 第二步：出题 ----
        _advance(
            task_id,
            STEP_GENERATE,
            status="running",
            detail=f"正在生成第 1 / {question_count} 题",
            progress=_PROGRESS_RETRIEVE + 5,
        )
        quiz = generate_quiz(
            user_input=user_input,
            question_count=question_count,
            difficulty=difficulty,
            reference=outcome.as_reference(),
            settings=s,
        )

        record = task_service.get_task_or_none(task_id)
        if record is None or record.status == "cancelled":
            # 用户已经放弃这次召唤：结果丢掉，不写回任务
            logger.info("出题任务 %s 已被取消，丢弃生成结果", task_id)
            return

        # 概念数现在才真正知道，把第一步的文案修正为真值
        concept_count = len(quiz.knowledge_points) or question_count
        _advance(task_id, STEP_RETRIEVE, status="done", detail=f"已提炼 {concept_count} 个核心概念")
        _advance(
            task_id,
            STEP_GENERATE,
            status="done",
            detail=f"已生成 {len(quiz.questions)} 道题",
            progress=_PROGRESS_GENERATE_DONE,
        )

        # ---- 第三步：校验 ----
        # 走到这里就说明 `QuizDraft` + `Quiz` 的 Pydantic 校验已经全部通过了。
        # 这一步不是装饰：它把「质量闸门确实执行过」显式地报给用户看。
        _advance(
            task_id,
            STEP_VALIDATE,
            status="running",
            detail="正在检查答案与选项是否自洽",
            progress=_PROGRESS_VALIDATE,
        )
        _advance(
            task_id,
            STEP_VALIDATE,
            status="done",
            detail=f"已校验通过 · 满分 {quiz.total_xp} XP",
            progress=_PROGRESS_DONE,
        )

        task_service.update_task(task_id, status="succeeded", quiz=quiz)

    except AppError as exc:
        logger.warning("出题任务 %s 失败：code=%s detail=%s", task_id, exc.code, exc.detail)
        _finish_failed(task_id, exc.code, exc.message)

    except Exception as exc:  # noqa: BLE001
        # 后台线程里的意外异常必须在这里被兜住。否则它会静默死在线程里，
        # 而任务永远停在 running —— 前端只能一直转圈到超时。
        logger.exception("出题任务 %s 出现未预期异常", task_id)
        _finish_failed(
            task_id,
            int(ErrorCode.INTERNAL_ERROR),
            DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
        )
        logger.debug("未预期异常详情：%r", exc)


# -----------------------------------------------------------------------------
# 提交入口
# -----------------------------------------------------------------------------
def submit_quiz_request(
    *,
    user_input: str,
    question_count: int,
    difficulty: str,
    settings: Settings | None = None,
    search_provider: SearchProvider | None = None,
) -> QuizSubmission:
    """校验输入并创建出题任务（同步返回，不等出题）。

    **校验顺序是「先长度、后内容」**：长度检查便宜且无需加载词表，
    而一段连 8 个字都不到的输入本来就该先提示「再多说一点」，
    不必走到敏感词判断。

    Raises:
        AppError: 4001 内容过短 / 过长 / 命中敏感词或提示词注入。
    """
    s = settings or get_settings()

    cleaned = validate_input(user_input)
    check_content(cleaned)

    provider = search_provider or get_search_provider(s)
    record = task_service.create_task(
        "quiz", steps=_initial_steps(provider, question_count)
    )

    _submit(
        lambda: run_quiz_generation(
            record.task_id,
            user_input=cleaned,
            question_count=question_count,
            difficulty=difficulty,
            settings=s,
            search_provider=provider,
        )
    )

    return QuizSubmission(
        task_id=record.task_id,
        status=record.status,
        poll_interval_ms=s.quiz_task_poll_interval_ms,
        estimated_seconds=estimate_seconds(question_count),
    )


def shutdown_executor(wait: bool = False) -> None:
    """关闭后台执行器（进程退出或测试收尾时调用）。"""
    _executor.shutdown(wait=wait)


def get_task_for_polling(task_id: str) -> TaskRecord:
    """轮询入口的语义封装（等价于 `task_service.get_task`，便于上层换实现）。"""
    return task_service.get_task(task_id)
