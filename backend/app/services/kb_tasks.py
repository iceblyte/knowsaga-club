"""解析任务的提交与收尾：一个有界线程池 + 一道不排队的闸门。

## 为什么独立成模块而不是塞进 `kb_service`

与 `quiz_service` / `report_service` 各自持有一个池是同一条理由：
**池是进程级资源，服务模块是业务逻辑**。混在一起之后，测试里替换
「任务怎么提交」这件事就得连业务模块一起动，而它恰好是唯一需要替身的地方。

顺带也让「解析池」与「出题池」在代码上就是两个东西 —— design 里那条
「解析不该排在出题任务后面等」因此不是一句约定，而是结构上做不到。

## 池满为什么**不排队**

`ThreadPoolExecutor` 的默认行为是「超过并发数就进无界队列」，于是
「上传成功」之后用户会挂着等几分钟，而且他完全看不出来前面排了多少活儿。
解析是一次可以重试的操作（原文件还在盘上），所以这里用一道
`BoundedSemaphore` 做闸门：**拿不到就直接说失败**，让用户点一下重试。
线程数与闸门数取同一个值，保证「在跑的任务数」永远不超过配置。

## 为什么提交前必须 `commit`

解析线程用**另一个连接**读那一行文档。没提交的话它读到的是 `None`，
于是安静地什么都不做 —— 上传界面永远停在「等待解析」。这条约束在
`kb_service.upload_document()` 里落实（先 `commit` 再提交），
`test_kb_service.py::test_parsing_state_is_visible_mid_flight` 盯着它。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

#: 当前池与闸门；`shutdown()` 之后置空，下次提交按新配置重建。
_pool: ThreadPoolExecutor | None = None
_gate: threading.BoundedSemaphore | None = None
_workers: int = 0


def _ensure(workers: int) -> tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    """懒建池与闸门；并发数变了就重建。

    允许「按配置重建」而不是硬记一个值：`kb_parse_workers` 是配置项，
    测试里会把它改成 1 来验池满，而模块级单例若认死了第一次的值，
    那种用例就只能靠 monkeypatch 整块逻辑来造 —— 那验的是替身，不是实现。
    """
    global _pool, _gate, _workers
    resolved = max(1, int(workers))
    if _pool is None or _workers != resolved:
        if _pool is not None:
            _pool.shutdown(wait=False)
        _pool = ThreadPoolExecutor(max_workers=resolved, thread_name_prefix="kb-parse")
        _gate = threading.BoundedSemaphore(resolved)
        _workers = resolved
        logger.info("知识库解析池就绪：workers=%s", resolved)
    assert _gate is not None
    return _pool, _gate


def submit(fn: Callable[[], None], *, workers: int) -> bool:
    """提交一个解析任务。

    Returns:
        `True` 已受理；`False` **池满，未受理**（调用方应把该文档判为失败，
        并给出一句「稍后重试」的提示）。

    ⚠️ 闸门必须在**提交之前**拿到：等池自己排队的话，队列深度是无界的，
    而「池满」这件事就再也观察不到了。
    """
    pool, gate = _ensure(workers)
    if not gate.acquire(blocking=False):
        logger.warning("知识库解析池已满（workers=%s），拒绝本次提交", workers)
        return False

    def _runner() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - 兜底：跑在裸线程里，抛出会静默消失
            logger.exception("知识库解析任务出现未预期异常")
        finally:
            gate.release()

    pool.submit(_runner)
    return True


def shutdown(wait: bool = False) -> None:
    """关闭池并丢弃引用（下次提交会重建）。

    `wait=False` 是默认值：进程退出或测试收尾时不该被一个卡住的上游请求
    拖住 —— 那些线程本来就可能挂在没有超时的网络调用上（见 `embedding.py`）。
    """
    global _pool, _gate, _workers
    if _pool is not None:
        _pool.shutdown(wait=wait)
    _pool = None
    _gate = None
    _workers = 0
