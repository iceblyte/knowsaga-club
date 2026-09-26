"""题目配图的生成编排（生图 → 转存 → 给出永久地址）。

## 契约：**这个包对外只做一件事，且绝不抛异常**

`generate_for_questions()` 是 `quiz_service` 出题链上唯一调用本包的地方。
它的契约与 `llm/search/base.SearchProvider.gather()` 同源：

- **不抛异常**：任何失败都降级成「这道题没有配图」，题目照常返回（需求 8 / design D8）。
- **不阻塞落库**：总预算到了就放弃剩余未生成的图，直接收尾。
- **不谎报**：返回值里带 `succeeded` / `attempted` / `reason`，
  调用方据此把真相写进进度详情，而不是一律说「配图已生成」。

## 并发模型

一题一次调用（`n=1`），由一个**有界**线程池并发跑（见 `client.py` 模块头：
「单次 6 张」与「每道题各自的图」是互斥的）。池大小取 `IMAGE_MAX_WORKERS`，
上限 8 是一道防呆 —— 配置写 0 或写 1000 都不该把进程搞垮。

单张的超时由 `client` 那层用 HTTP 超时断（`request_timeout`）；整段的超时由本层
的总预算断（`as_completed(timeout=budget)`）。两者是不同粒度，都需要。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from uuid import uuid4

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.image import client, store
from app.llm.image import prompt as prompt_builder
from app.models.quiz import Question

logger = get_logger(__name__)

#: 并发上限防呆（配置写错也不至于把进程打穿）
_MAX_WORKERS_CAP = 8

_pool: ThreadPoolExecutor | None = None


def get_pool(settings: Settings) -> ThreadPoolExecutor:
    """模块级线程池（懒建）。

    与 `quiz_service._executor`、`kb/embedding.get_embed_pool()` 同一个理由：
    **必须有界**，且不按请求重建（重建会让超时的线程越积越多）。
    池大小在建池时定下，之后不再改 —— `ThreadPoolExecutor` 也没法缩容。
    """
    global _pool
    if _pool is None:
        workers = max(1, min(int(settings.image_max_workers or 1), _MAX_WORKERS_CAP))
        _pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quiz-image")
    return _pool


def shutdown_pool(wait: bool = False) -> None:
    """关闭线程池（进程退出或测试收尾时调用）。"""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=wait)
        _pool = None


#: 调用方用来把「本段发生了什么」说给用户看的取值。
#: `""` = 全部成功；其余四种都表示「有题没拿到图」。
REASON_DONE = ""
REASON_DISABLED = "disabled"
REASON_BUDGET = "budget"
REASON_PARTIAL = "partial"
REASON_ERROR = "error"


@dataclass(frozen=True)
class ImageOutcome:
    """生图段的结果（**不是**异常）。

    `urls` 的键是题目的 `id`（题库内唯一，见 `Quiz._validate_question_ids`）——
    调用方按 id 回填，不必关心顺序。
    """

    urls: dict[str, str]
    attempted: int
    succeeded: int
    reason: str = REASON_DONE

    @property
    def complete(self) -> bool:
        """是否「要多少给多少」。能力未启用时不算 complete（一道都没要）。"""
        return self.reason == REASON_DONE and self.attempted > 0


def _render_one(*, question: Question, seq: int, run_token: str, settings: Settings) -> str:
    """生成一道题的配图并转存，返回**永久**地址。

    三步：构建提示词 → 调上游拿临时链接 → 下载并传上对象存储。
    任一步抛 `ImageGenError` / `ImageStoreError`，由 `generate_for_questions` 捕获。

    ⚠️ 这个函数是测试的替身点之一（另一个是 `client._invoke_call` / `store._build_client`）。
    """
    prompt = prompt_builder.build_prompt(question)
    temporary_url = client.generate_image_url(prompt, settings)
    data, content_type = client.download_image(
        temporary_url,
        max_bytes=settings.image_download_max_bytes,
        timeout=float(settings.image_timeout_seconds),
    )
    key = store.build_object_key(
        run_token=run_token,
        seq=seq,
        ext=client.extension_for(content_type),
    )
    return store.upload_image(data, key=key, content_type=content_type, settings=settings)


def generate_for_questions(
    questions: Sequence[Question],
    *,
    settings: Settings,
    on_progress: Callable[[int, int], None] | None = None,
) -> ImageOutcome:
    """为一批题目生成配图。**这个函数不抛异常**（见模块头的契约）。

    Args:
        questions: 本次生成的题目（顺序即题序，用于对象键的 `seq`）。
        settings: 配置。`image_generation_available` 为假时**一道都不跑**，
            直接返回 `REASON_DISABLED` —— 上层在真正调用之前就该拦下这种情况，
            这里是第二道闸门（防止「开关关着却悄悄生了一堆图」）。
        on_progress: `(已完成道数, 总道数)` 回调，用来推进度。**不保证每个下标都回调**
            （超预算时后面的不会回调），但保证递增。

    Returns:
        `ImageOutcome`。`urls` 里没有的题目就是「这次没拿到图」。
    """
    total = len(questions)
    if total == 0:
        return ImageOutcome(urls={}, attempted=0, succeeded=0, reason=REASON_DONE)

    if not settings.image_generation_available:
        logger.info(
            "配图能力对外不可用（开关关或凭据不齐），跳过全部生图：enabled=%s",
            settings.image_generation_enabled,
        )
        return ImageOutcome(urls={}, attempted=0, succeeded=0, reason=REASON_DISABLED)

    run_token = uuid4().hex[:12]
    budget = max(0.0, float(settings.image_budget_seconds))
    pool = get_pool(settings)

    futures = {
        pool.submit(
            _render_one,
            question=question,
            seq=index + 1,
            run_token=run_token,
            settings=settings,
        ): question
        for index, question in enumerate(questions)
    }

    urls: dict[str, str] = {}
    succeeded = 0
    done = 0
    failed = 0
    aborted = False

    try:
        for future in as_completed(futures, timeout=budget):
            question = futures[future]
            done += 1
            try:
                url = future.result()
            except Exception as exc:  # noqa: BLE001 - 单张失败只丢这张（design D8）
                failed += 1
                logger.warning(
                    "第 %s 题的配图生成失败，本题将不带图：%r", question.id, exc
                )
            else:
                if url:
                    urls[question.id] = url
                    succeeded += 1
                else:
                    failed += 1
            if on_progress is not None:
                on_progress(done, total)
    except FuturesTimeout:
        # 总预算耗尽：剩下的连试都不试，直接收尾（宁可少几张图，也不让界面空转）
        aborted = True
        logger.warning(
            "配图总预算 %.0fs 已耗尽，放弃剩余未生成的图片（成功 %d / 共 %d）",
            budget,
            succeeded,
            total,
        )
    finally:
        # 还没跑完的一律取消（已在跑的那几张会自然结束，结果被丢弃）
        for future in futures:
            future.cancel()

    if aborted:
        reason = REASON_BUDGET
    elif succeeded == 0:
        reason = REASON_ERROR
    elif failed:
        reason = REASON_PARTIAL
    else:
        reason = REASON_DONE

    logger.info(
        "配图段结束：成功 %d / 共 %d（尝试 %d），reason=%s",
        succeeded,
        total,
        done,
        reason,
    )
    return ImageOutcome(urls=urls, attempted=done, succeeded=succeeded, reason=reason)


__all__ = [
    "REASON_BUDGET",
    "REASON_DISABLED",
    "REASON_DONE",
    "REASON_ERROR",
    "REASON_PARTIAL",
    "ImageOutcome",
    "generate_for_questions",
    "get_pool",
    "shutdown_pool",
]
