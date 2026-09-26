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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ErrorCode, DEFAULT_MESSAGES
from app.core.logging import get_logger
from app.db.session import session_scope
from app.llm import image as image_flow
from app.llm import quiz_chain
from app.llm.image import ImageOutcome
from app.llm.image import selector as image_select
from app.llm.search import SearchProvider, SearchRequest, get_search_provider
from app.llm.search import collector
from app.llm.search.agent import ToolProgress
from app.llm.search.base import KbScope, ReferenceCaps, SearchOutcome
from app.models.quiz import Question, Quiz
from app.services import image_quota_service, quiz_repository, task_service
from app.services.image_quota_service import QuotaHold
from app.services.task_service import TaskRecord, TaskStep
from app.utils.content_filter import check_content
from app.utils.links import extract_urls
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

#: 配图段在第二步内部推进的起点（= 取完材、刚出完题的时刻）。
#: 配图**不新增第四步**：原型的三步是界面裁决依据，生图只是「生成闯关题目」
#: 这件事的延伸，所以它借用第二步的 detail 与进度区间（design D10）。
_PROGRESS_IMAGE_START = _PROGRESS_RETRIEVE + 5

#: 后台执行器。**有界**是关键：无界的线程创建会让一次流量高峰把进程打穿。
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quiz-gen")

#: 落库用的会话工厂（可替换）。
#:
#: 出题跑在**后台线程**里，那里没有请求级会话，必须自己开一个。
#: 做成模块级可替换的变量，是为了让测试能把它指向测试库 ——
#: 否则后台写入会落到业务库上（`conftest` 里对此有明确警告）。
#: 服务层的其它函数一律**显式接收 session**，只有这一处例外。
_open_session: Callable[[], AbstractContextManager[Session]] = session_scope


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
def _initial_steps(
    provider: SearchProvider, request: SearchRequest, question_count: int
) -> list[TaskStep]:
    """三步状态卡的初始状态。

    第一步的名字来自 Provider：``「理解你的输入」/「联网检索知识」/「读取你给的网页」``。
    前端不做这个判断（§7.3），所以它必须在**建任务时**就定下来 ——
    而它的三态同时取决于「输入里有没有链接」「用户想不想搜」「这个 Provider 有没有这个能力」，
    因此必须把 `request` 传进来（只看 Provider 是判断不出来的）。
    """
    return [
        TaskStep(
            key=STEP_RETRIEVE,
            name=provider.initial_step(request).name,
            status="pending",
            detail="准备中",
        ),
        TaskStep(
            key=STEP_GENERATE,
            name="生成闯关题目",
            status="pending",
            detail=f"将生成 {question_count} 道题",
        ),
        TaskStep(key=STEP_VALIDATE, name="校验题目结构", status="pending", detail="等待中"),
    ]


def _build_search_request(
    user_input: str,
    settings: Settings,
    *,
    use_search: bool = True,
    kb: KbScope | None = None,
) -> SearchRequest:
    """把已清洗的输入组装成取材请求：链接从输入里抽，意愿由请求参数给。

    ⚠️ 链接抽取走**服务端自己的规则**（`app/utils/links.py`），不看前端的判断 ——
    前端那只 pill 只决定显示哪句话，不能作为「要读哪些页面」的依据。
    两边规则同源（同一组正则形态），所以要改一起改。

    Args:
        kb: 本次要用的知识库作用域。**归属已经校验过了**（见 `_resolve_kb_scope`）——
            本函数只负责装进请求，不判定权限。
    """
    return SearchRequest(
        query=user_input,
        urls=extract_urls(user_input),
        use_search=use_search,
        max_results=settings.search_max_results,
        kb=kb,
    )


def _resolve_kb_scope(
    kb_id: int | None, *, user_id: int, session: Session | None
) -> KbScope | None:
    """把请求里的 `kb_id` 变成取材作用域；**越权 / 不存在直接抛 4005**。

    ⚠️ 这一步必须在 `create_task` **之前**（design D13），理由与
    `TavilySearchProvider.__init__` 里校验 key 相同：用户该直接看到
    「这个库不能用」，而不是拿到一个 `task_id`、等几秒后看到一个注定失败的任务。

    `user_id` 只来自鉴权 —— 客户端只提供 `kb_id`。两者都由客户端给的话，
    越权就只是一个数字的事了。

    Args:
        session: 请求级会话。传了就用它（接口路径）；没传就自己开一个
            （服务层的其它调用点，如测试）。**服务层只在后台线程那一条路径上
            自开会话**，这里是例外，所以有显式分支而不是默默用全局工厂。
    """
    if kb_id is None:
        return None

    # 惰性 import：知识库关着的部署连 `kb_service` 都不该在出题链上被拉起
    # （它会拖进 `langchain_core.embeddings` 与仓库层）。
    from app.services import kb_service

    if session is not None:
        kb_service.require_owned_base(session, user_id=user_id, kb_id=kb_id)
    else:
        with _open_session() as probe:
            kb_service.require_owned_base(probe, user_id=user_id, kb_id=kb_id)
    return KbScope(user_id=user_id, kb_id=int(kb_id))


def _progress_reporter(task_id: str) -> Callable[[ToolProgress], None]:
    """把取材循环的进度写进「第一步」的 detail。

    取材可能跑十几秒，而进度条第一步必须能从「正在检索」变成「正在读取 2 个网页」——
    否则用户看到的是一个十几秒不动的界面。文案由后端给（§7.3），前端只渲染。
    """

    def report(progress: ToolProgress) -> None:
        _advance(task_id, STEP_RETRIEVE, status="running", detail=progress.detail)

    return report


def _gather_safely(provider: SearchProvider, request: SearchRequest, task_id: str) -> SearchOutcome:
    """取材，并把任何异常降级成「空资料」。

    契约上 `SearchProvider.gather()` **不允许抛异常**（见 `llm/search/base.py` 的模块
    docstring），但调用侧不能只靠契约：取材是出题的**增强项**，它炸一次不该让用户
    白等十几秒再看到一个失败任务 —— 那是把「少一点资料」升级成了「什么都没有」。

    配置错误（5000，未配 key）在 `get_search_provider` 那一步就被拦下了，所以这里
    还能抛出来的都是「取不到资料」，一律降级。

    注意 `step_name` 仍取 Provider 的判断：名字回答「本来打算做什么」，
    这次确实打算去读链接 / 去搜，只是没成 —— 详情会如实说「未取到可用资料」。
    """
    try:
        return provider.gather(request, on_progress=_progress_reporter(task_id))
    except Exception as exc:  # noqa: BLE001 - 取材失败不该拖垮出题
        logger.warning("取材失败，已降级为纯模型出题：provider=%s error=%r", provider.name, exc)
        return SearchOutcome(
            provider=provider.name,
            step_name=provider.initial_step(request).name,
            end_reason="error",
        )


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
# 题目配图（额度 + 生图段）
# -----------------------------------------------------------------------------
# 这一段的全部设计都围绕两条硬约束：
#
# 1. **生图失败绝不影响到手的题库**（需求 8 / design D8）。所以这里每一个
#    对外部世界的调用都被兜在段内，且配额收尾自己再兜一次 —— 配额出问题
#    也不许把一次成功的出题变成失败。
# 2. **配额必须收干净**：预扣之后无论走哪条出口（成功 / 失败 / 取消 /
#    提前返回 / 未预期异常），持有量都必须落成「结算」或「退还」二选一，
#    不允许出现「扣了但没人管」。
#
# 配额的三次操作各自开一个 `_open_session()`（后台线程没有请求级会话）。
# ⚠️ 每新增一个会在后台线程里写库的服务，都要记得加进 `conftest.db_scope`；
# 本模块已经在里面了。


def _reserve_image_quota(
    *, user_id: int, count: int, settings: Settings
) -> QuotaHold:
    """在建任务**之前**预扣（design D6）。

    Raises:
        AppError: 4290 当天额度不足（文案说明还剩几张、怎么继续）。
    """
    with _open_session() as session:
        return image_quota_service.reserve(
            session, user_id=user_id, count=count, settings=settings
        )


def _settle_image_quota(hold: QuotaHold, *, succeeded: int) -> None:
    """按实际成功张数结算。**自己兜住异常** —— 收尾失败不该把出题搞挂。"""
    try:
        with _open_session() as session:
            image_quota_service.settle(session, hold=hold, succeeded=succeeded)
    except Exception:  # noqa: BLE001
        logger.exception("配额结算失败（用户 %s，预扣 %s 张）", hold.user_id, hold.reserved)


def _release_image_quota(hold: QuotaHold) -> None:
    """全额退还。同样自己兜住异常。"""
    try:
        with _open_session() as session:
            image_quota_service.release(session, hold=hold)
    except Exception:  # noqa: BLE001
        logger.exception("配额退还失败（用户 %s，预扣 %s 张）", hold.user_id, hold.reserved)


def _generate_detail(question_count: int) -> str:
    """不配图时的第二步完成文案。

    单独抽成函数只为一件事：**接入配图后它与接入前必须一字不差**，
    而它在两处被拼（进行中 / 完成）。散着写就会出现「某个分支少了个空格」。
    """
    return f"已生成 {question_count} 道题"


def _image_selecting_detail(question_count: int) -> str:
    """配图段的第一步文案：正在判断哪几道题值得配图。

    单独一句话，而不是先显示「正在配图 0 / 总题数」再跳成「0 / 选中数」——
    那个分母中途会变小，看上去像进度回退了。
    """
    return f"已生成 {question_count} 道题 · 正在挑选值得配图的题目"


def _image_running_detail(question_count: int, done: int, total: int) -> str:
    """进行中的文案。`total` 是**要配图的题数**（判断结果），不是总题数。"""
    return f"已生成 {question_count} 道题 · 正在配图 {done} / {total}"


def _image_done_detail(question_count: int, outcome: ImageOutcome) -> str:
    """配图段的收尾文案。

    三种情形必须分开说，否则用户只能猜：

    - `REASON_NO_NEED`：判断认为**这几道题都不需要图**。说「配图 0 / 5」
      会像是 5 张全失败了，而这里根本没打算配。
    - `attempted == 0`：能力中途不可用了（没开始跑）。同理不能说成失败。
    - 其余：按**实际配了图的题数**报（分母是 `attempted`，不是总题数）——
      用户不关心「本来有 5 道题」，他关心「勾了配图的那几道拿到没有」。
    """
    if outcome.reason == image_flow.REASON_NO_NEED:
        return f"已生成 {question_count} 道题 · 没有需要配图的题"
    if outcome.attempted == 0:
        return f"已生成 {question_count} 道题 · 未生成配图"
    return f"已生成 {question_count} 道题 · 配图 {outcome.succeeded} / {outcome.attempted}"


def _image_progress(done: int, total: int) -> int:
    """把配图完成比例映射到第二步的进度区间（30 → 85）。"""
    if total <= 0:
        return _PROGRESS_GENERATE_DONE
    span = _PROGRESS_GENERATE_DONE - _PROGRESS_IMAGE_START
    return _PROGRESS_IMAGE_START + int(span * done / total)


def _select_image_targets(quiz: Quiz, *, settings: Settings) -> list[Question]:
    """挑出这次真要配图的题目（2026-09-26 新增，design D18）。

    判断本身在 `llm/image/selector` 里，且那一步**不抛异常**：
    判断失败 / 开关关着时它返回「全都配」，正是接入本功能之前的行为。
    这里只负责把那两种「全都配」的表示翻译成题目列表。
    """
    selection = image_select.select_for_images(quiz.questions, settings=settings)
    if selection.ids is None:
        return list(quiz.questions)
    return [question for question in quiz.questions if question.id in selection.ids]


def _render_images(
    quiz: Quiz, *, task_id: str, settings: Settings
) -> tuple[Quiz, ImageOutcome]:
    """给题目配上图，返回**带图的新题库**与生图段的结果。

    两步：**先判断哪几道值得配**（design D18），再对挑出来的那几道生图。
    判断认为一道都不需要时直接收尾，一张都不生成 —— 收尾文案必须
    说清这是「不需要」而不是「失败了」（见 `_image_done_detail`）。

    **这个函数不抛异常**：任何失败都降级成「这些题没有图」，题库照常返回。

    ⚠️ 这里对 `generate_for_questions` 再兜一层 try：它的契约是不抛异常，
    但「契约说不会抛」不等于「真不会抛」，而这一段跑在后台线程里 ——
    漏出去就是任务永远停在 running（前端一直转圈到超时）。
    """
    total = len(quiz.questions)
    _advance(
        task_id,
        STEP_GENERATE,
        status="running",
        detail=_image_selecting_detail(total),
        progress=_PROGRESS_IMAGE_START,
    )

    try:
        targets = _select_image_targets(quiz, settings=settings)
    except Exception:  # noqa: BLE001
        # 与下面生图段那一层同一个理由：契约说「不抛异常」不等于「真不会抛」，
        # 而这一段跑在后台线程里 —— 漏出去就是任务永远停在 running。
        # 兜底策略取 selector 自己的降级语义：回退「全部配图」。
        logger.exception("配图判断出现未预期异常，本次按全部配图处理")
        targets = list(quiz.questions)

    if not targets:
        logger.info("配图判断认为 %d 道题都不需要配图，跳过生图段", total)
        return quiz, ImageOutcome(
            urls={}, attempted=0, succeeded=0, reason=image_flow.REASON_NO_NEED
        )

    def report(done: int, count: int) -> None:
        _advance(
            task_id,
            STEP_GENERATE,
            status="running",
            detail=_image_running_detail(total, done, count),
            progress=_image_progress(done, count),
        )

    try:
        outcome = image_flow.generate_for_questions(
            targets, settings=settings, on_progress=report
        )
    except Exception:  # noqa: BLE001
        logger.exception("配图段出现未预期异常，本次不配图")
        return quiz, ImageOutcome(urls={}, attempted=0, succeeded=0)

    if not outcome.urls:
        return quiz, outcome

    # 按题目 id 回填（outcome.urls 的键就是题目 id，见 `llm/image` 的说明）。
    # 用 `model_copy` 而不是原地改：`Quiz` / `Question` 都是不可变的契约对象，
    # 原地改会让「谁在什么时候改了它」变得难查。
    questions = [
        question.model_copy(update={"image_url": outcome.urls.get(question.id)})
        if question.id in outcome.urls
        else question
        for question in quiz.questions
    ]
    return quiz.model_copy(update={"questions": questions}), outcome


# -----------------------------------------------------------------------------
# 后台出题
# -----------------------------------------------------------------------------
def run_quiz_generation(
    task_id: str,
    *,
    user_id: int,
    user_input: str,
    question_count: int,
    difficulty: str,
    settings: Settings | None = None,
    generate: Callable[..., Quiz] | None = None,
    search_provider: SearchProvider | None = None,
    search_request: SearchRequest | None = None,
    image_hold: QuotaHold | None = None,
) -> None:
    """后台出题主流程。**这个函数不抛异常** —— 任何失败都落到任务的 `failed` 状态上。

    Args:
        task_id: 已创建的任务。
        user_id: 卷轴归属。落库时写进 `quizzes.user_id`。
        user_input: 已清洗的输入。
        generate: 注入出题函数（测试用）；不传则用 `quiz_chain.generate_quiz`。
        search_provider: 注入检索 Provider（测试用）；不传则按配置取。
        search_request: 取材请求（链接 + 意愿）。不传则按 `user_input` 兜底组装 ——
            传进来才能保证「建任务时展示的第一步」与「真正取材时用的请求」是同一份。
        image_hold: 提交时预扣的配图额度凭据。`None` = 这次不要配图
            （行为与接入配图之前逐位一致）。非 `None` 时本函数**保证**在
            每个出口把它落成「结算」或「全额退还」二选一。
    """
    s = settings or get_settings()
    provider = search_provider or get_search_provider(s)
    request = search_request or _build_search_request(user_input, s)
    # 用 module 属性现取，这样测试 monkeypatch `quiz_chain.generate_quiz` 才会生效
    generate_quiz = generate or quiz_chain.generate_quiz

    image_result: ImageOutcome | None = None
    quota_closed = False

    def close_quota(*, succeeded: int | None) -> None:
        """收尾配额。`succeeded=None` 表示走退还。**幂等**（重复调用只生效一次）。"""
        nonlocal quota_closed
        if image_hold is None or quota_closed:
            return
        quota_closed = True
        if succeeded is None:
            _release_image_quota(image_hold)
        else:
            _settle_image_quota(image_hold, succeeded=succeeded)

    record = task_service.get_task_or_none(task_id)
    if record is None or task_service.is_finished(record.status):
        # 任务已过期或已被取消 —— 不要再开工，也不要覆盖任何东西
        logger.info("出题任务 %s 已结束或不存在，跳过执行", task_id)
        # 但预扣是真的扣过了：不退还的话用户会白丢一次额度
        close_quota(succeeded=None)
        return

    try:
        task_service.update_task(task_id, status="running", progress=5)

        # ---- 第一步：检索 / 理解输入 ----
        _advance(task_id, STEP_RETRIEVE, status="running", detail="正在解析你的学习需求", progress=8)
        outcome = _gather_safely(provider, request, task_id)
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
            progress=_PROGRESS_IMAGE_START,
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
            close_quota(succeeded=None)
            return

        # 概念数现在才真正知道，把第一步的详情修正为真值。
        # ⚠️ 用 `first_step()` 而不是自己拼字符串：它是「这一步的结果怎么说」的唯一出口 ——
        # 自己拼会把「取到了资料」这件事盖掉，只留下一句「已提炼 N 个核心概念」。
        concept_count = len(quiz.knowledge_points) or question_count
        _advance(
            task_id,
            STEP_RETRIEVE,
            status="done",
            detail=outcome.first_step(concept_count=concept_count).detail,
        )
        # ---- 第二步（续）：配图 ----
        # 用户在生成设置页勾了配图才会有 `image_hold`。没勾就整段跳过，
        # 连 detail 都不碰 —— 那条路径必须与接入配图之前逐位一致。
        if image_hold is not None:
            quiz, image_result = _render_images(quiz, task_id=task_id, settings=s)
            _advance(
                task_id,
                STEP_GENERATE,
                status="done",
                detail=_image_done_detail(len(quiz.questions), image_result),
                progress=_PROGRESS_GENERATE_DONE,
            )
        else:
            _advance(
                task_id,
                STEP_GENERATE,
                status="done",
                detail=_generate_detail(len(quiz.questions)),
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

        # ---- 落库 ----
        # 为什么放在「校验完成」之前：这一步是整条链上唯一会写数据库的动作，
        # 也是最可能失败的一步（库不可用、列超长）。放在这里，失败会如实
        # 反映在「校验题目结构」这一步上，而不是让界面显示「全部完成」
        # 却在轮询结果里找不到题库。
        #
        # 落库之后 `quiz.quiz_id` 与每道题的 `id` 都被改写成数据库主键的
        # 字符串形式（见 `quiz_repository` 的模块说明）。没有这一步，
        # 前端拿到的题库无法交卷 —— 结算需要按主键反查题目快照。
        quiz = _persist_quiz(
            user_id=user_id,
            quiz=quiz,
            difficulty=difficulty,
            search_state=outcome.search_state,
            references=collector.serialize_references(
                outcome.results, caps=ReferenceCaps.from_settings(s)
            ),
        )

        _advance(
            task_id,
            STEP_VALIDATE,
            status="done",
            detail=f"已校验通过 · 满分 {quiz.total_xp} XP",
            progress=_PROGRESS_DONE,
        )

        # 配额结算放在**任务真正成功之后**（design D6「任务成功后按实际成功张数结算」）。
        # 放在这里而不是生图刚结束：若这一步之后落库失败了，用户拿到的是
        # 一个失败的出题任务，按 D6 的口径应当**全额退还**，而不是为几张
        # 他根本看不到的图买单。
        close_quota(
            succeeded=image_result.succeeded if image_result is not None else 0
        )

        task_service.update_task(task_id, status="succeeded", quiz=quiz)

    except AppError as exc:
        logger.warning("出题任务 %s 失败：code=%s detail=%s", task_id, exc.code, exc.detail)
        close_quota(succeeded=None)
        _finish_failed(task_id, exc.code, exc.message)

    except Exception as exc:  # noqa: BLE001
        # 后台线程里的意外异常必须在这里被兜住。否则它会静默死在线程里，
        # 而任务永远停在 running —— 前端只能一直转圈到超时。
        logger.exception("出题任务 %s 出现未预期异常", task_id)
        close_quota(succeeded=None)
        _finish_failed(
            task_id,
            int(ErrorCode.INTERNAL_ERROR),
            DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
        )
        logger.debug("未预期异常详情：%r", exc)

    finally:
        # 兜底：将来若有人在上面插了一条新的提前返回，配额也不会漏在外面。
        # 已经结算/退还过时 `close_quota` 是空操作（幂等）。
        close_quota(succeeded=None)


# -----------------------------------------------------------------------------
# 落库
# -----------------------------------------------------------------------------
def _persist_quiz(
    *,
    user_id: int,
    quiz: Quiz,
    difficulty: str,
    search_state: str = "off",
    references: list[dict[str, str]] | None = None,
) -> Quiz:
    """把题库写进 `quizzes` + `questions`，返回 id 已回填的题库。

    **不要吞掉这里的异常**：落库失败必须让整个任务失败。返回一份没有数据库 id
    的题库看起来「出题成功了」，但用户在答题结束交卷时才会撞上一个无法解释的错误 ——
    那时他已经花了五分钟答题，而这次错误原本可以在十秒前就告诉他。

    这里用 `session_scope()` 而不是请求级会话：本函数运行在后台线程里。
    工厂是可替换的模块变量（`_open_session`），测试据此指向测试库。
    """
    with _open_session() as session:
        return quiz_repository.persist_quiz(
            session,
            user_id=user_id,
            quiz=quiz,
            difficulty=difficulty,
            search_state=search_state,
            references=references,
        )


# -----------------------------------------------------------------------------
# 提交入口
# -----------------------------------------------------------------------------
def submit_quiz_request(
    *,
    user_id: int,
    user_input: str,
    question_count: int,
    difficulty: str,
    settings: Settings | None = None,
    search_provider: SearchProvider | None = None,
    use_search: bool = True,
    kb_id: int | None = None,
    generate_images: bool = False,
    session: Session | None = None,
) -> QuizSubmission:
    """校验输入并创建出题任务（同步返回，不等出题）。

    **校验顺序是「先长度、后内容、最后库归属 / 额度」**：长度检查便宜且无需加载词表，
    而一段连 8 个字都不到的输入本来就该先提示「再多说一点」，
    不必走到敏感词判断；库归属与配图额度要查库，放在最后。

    Args:
        user_id: 任务的归属用户。任务表不再允许匿名（见 `task_service.get_task_for_user`）。
        kb_id: 本次出题要用的知识库。`None` = 不带库，行为与接入前逐位一致。
        generate_images: 要不要给题目配图。默认 `False` ⇒ 完全不碰配额表，
            行为与接入前逐位一致。
        session: 请求级会话；接口路径传入，用于 `kb_id` 的归属校验。

    Raises:
        AppError: 4001 内容过短 / 过长 / 命中敏感词或提示词注入；
            4005 `kb_id` 对应的库不存在或不属于该用户（**在建任务之前**）；
            4001 要了配图但能力不可用（开关关 / 缺百炼 key / 缺 COS 凭据）；
            4290 当天配图额度不足（**同样在建任务之前**）。
    """
    s = settings or get_settings()

    cleaned = validate_input(user_input)
    check_content(cleaned)

    scope = _resolve_kb_scope(kb_id, user_id=user_id, session=session)
    provider = search_provider or get_search_provider(s)
    request = _build_search_request(cleaned, s, use_search=use_search, kb=scope)

    hold: QuotaHold | None = None
    if generate_images:
        _require_image_capability(s)
        # 预扣放在建任务之前：额度不足时用户**立刻**知道，
        # 而不是建了任务、看十几秒进度条、最后收到一个注定失败的结局。
        hold = _reserve_image_quota(
            user_id=user_id, count=question_count, settings=s
        )

    try:
        record = task_service.create_task(
            "quiz",
            user_id=user_id,
            steps=_initial_steps(provider, request, question_count),
        )
    except Exception:
        # 建任务失败（进程内操作，正常不会）⇒ 预扣必须退回去，
        # 否则就变成「扣了额度、什么也没发生」。
        if hold is not None:
            _release_image_quota(hold)
        raise

    _submit(
        lambda: run_quiz_generation(
            record.task_id,
            user_id=user_id,
            user_input=cleaned,
            question_count=question_count,
            difficulty=difficulty,
            settings=s,
            search_provider=provider,
            search_request=request,
            image_hold=hold,
        )
    )

    return QuizSubmission(
        task_id=record.task_id,
        status=record.status,
        poll_interval_ms=s.quiz_task_poll_interval_ms,
        estimated_seconds=estimate_seconds(question_count),
    )


def _require_image_capability(settings: Settings) -> None:
    """要配图但能力不可用 ⇒ 4001 直接拒掉，**不默默忽略**。

    为什么是 4001 而不是别的码：本项目的约定是「4001 的提示语是给用户看的」
    （见 `api/v1/routes/quiz.py` 的注释与 `exceptions.py` 的码表）。

    为什么不默默忽略：用户以为自己开了配图，拿到题目才发现一张图都没有，
    而界面不会给任何解释 —— 那是比一句错误提示更差的结果。

    正常情况下前端**根本不会**显示这个开关（`/health` 下发的是派生能力），
    所以走到这里基本只有两种可能：老版本客户端，或者绕过前端直接调接口。
    """
    if settings.image_generation_available:
        return
    raise AppError(
        ErrorCode.INVALID_INPUT,
        "配图功能暂时不可用，关掉配图后仍可照常出题",
        detail=(
            "IMAGE_GENERATION_ENABLED="
            f"{settings.image_generation_enabled} "
            f"has_image_credentials={settings.has_image_credentials} "
            f"has_dashscope_key={bool(settings.dashscope_api_key)}"
        ),
    )



def shutdown_executor(wait: bool = False) -> None:
    """关闭后台执行器（进程退出或测试收尾时调用）。"""
    _executor.shutdown(wait=wait)


def get_task_for_polling(task_id: str, user_id: int) -> TaskRecord:
    """轮询入口的语义封装：**带归属校验**。

    不是自己的任务按「不存在」处理（4004），理由见 `task_service.get_task_for_user`。
    """
    return task_service.get_task_for_user(task_id, user_id)
