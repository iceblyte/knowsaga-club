"""生图并发编排（`add-question-image-generation` 第 3 组）。

**这一组守的是降级契约（design D8）**：`generate_for_questions()` 不抛异常、
部分失败只丢图、总预算到了就收尾。它是「生图不拖垮出题」这句话的实现点 ——
所以每一条都要被钉住，而不是靠「应该不会出问题」。
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from app.llm import image
from app.models.quiz import Question

from tests.conftest import SAMPLE_QUESTIONS


@pytest.fixture(autouse=True)
def _pool_guard():  # noqa: ANN201
    """每条用例后关掉生图池。

    池是**进程内全局状态**，而「预算超时」那条用例会留下仍在 sleep 的线程 ——
    不收尾的话它们会飘到后面的用例里，制造难以定位的偶发失败。
    """
    yield
    image.shutdown_pool(wait=True)


def _questions(count: int = 3) -> list[Question]:
    return [Question.model_validate(payload) for payload in SAMPLE_QUESTIONS[:count]]


class _Renderer:
    """`image._render_one` 的替身：可配置成功 / 失败 / 慢。"""

    def __init__(
        self,
        *,
        fail_on: set[str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.calls: list[str] = []
        self._fail_on = fail_on or set()
        self._delay = delay
        self._lock = threading.Lock()

    def __call__(self, *, question: Question, seq: int, run_token: str, settings: Any) -> str:
        with self._lock:
            self.calls.append(question.id)
        if self._delay:
            time.sleep(self._delay)
        if question.id in self._fail_on:
            raise RuntimeError("upstream exploded")
        return f"https://img.example.com/questions/{run_token}/{seq}.jpg"


def _install(monkeypatch: pytest.MonkeyPatch, renderer: _Renderer) -> _Renderer:
    monkeypatch.setattr(image, "_render_one", renderer)
    return renderer


# ---------------------------------------------------------------- 正常路径
def test_all_succeed(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = image_env()
    questions = _questions(3)
    renderer = _install(monkeypatch, _Renderer())

    outcome = image.generate_for_questions(questions, settings=settings)

    assert outcome.reason == image.REASON_DONE
    assert outcome.complete is True
    assert outcome.succeeded == 3
    assert outcome.attempted == 3
    assert set(outcome.urls) == {q.id for q in questions}
    assert len(renderer.calls) == 3


def test_progress_is_reported(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = image_env()
    questions = _questions(3)
    _install(monkeypatch, _Renderer())
    seen: list[tuple[int, int]] = []

    image.generate_for_questions(
        questions, settings=settings, on_progress=lambda done, total: seen.append((done, total))
    )

    assert [done for done, _ in seen] == [1, 2, 3]
    assert {total for _, total in seen} == {3}


def test_empty_questions_returns_clean_outcome(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = image_env()
    renderer = _install(monkeypatch, _Renderer())

    outcome = image.generate_for_questions([], settings=settings)

    assert outcome.urls == {}
    assert outcome.attempted == 0
    assert outcome.reason == image.REASON_DONE
    assert renderer.calls == []


# ---------------------------------------------------------------- 降级
def test_partial_failure_keeps_the_rest(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """部分失败：只有那几道题没图，其余照常带图，且**不抛异常**。"""
    settings = image_env()
    questions = _questions(3)
    renderer = _install(monkeypatch, _Renderer(fail_on={questions[1].id}))

    outcome = image.generate_for_questions(questions, settings=settings)

    assert len(renderer.calls) == 3, "失败的题也要真的尝试过"
    assert outcome.succeeded == 2
    assert outcome.attempted == 3
    assert questions[1].id not in outcome.urls
    assert outcome.reason == image.REASON_PARTIAL
    assert outcome.complete is False


def test_total_failure_is_not_an_exception(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """全部失败：题目照常（一道图都没有），而不是把出题任务搞失败。"""
    settings = image_env()
    questions = _questions(3)
    _install(monkeypatch, _Renderer(fail_on={q.id for q in questions}))

    outcome = image.generate_for_questions(questions, settings=settings)

    assert outcome.urls == {}
    assert outcome.succeeded == 0
    assert outcome.attempted == 3
    assert outcome.reason == image.REASON_ERROR


def test_budget_aborts_remaining(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """总预算耗尽 ⇒ 放弃剩余、立刻返回，而不是把界面按住等图片。

    ⚠️ 这里**显式**要 3 个 worker：用例断言「三道题都提交了」，
    而那要求池能同时装下这三道题 —— 池小于题量时排队的那些压根不会开始跑，
    `renderer.calls` 自然少于 3（这条断言曾经隐性依赖本机 `.env` 的取值而红过）。
    """
    settings = image_env(IMAGE_MAX_WORKERS="3").model_copy(update={"image_budget_seconds": 0})
    questions = _questions(3)
    renderer = _install(monkeypatch, _Renderer(delay=0.3))

    started = time.monotonic()
    outcome = image.generate_for_questions(questions, settings=settings)
    elapsed = time.monotonic() - started

    assert outcome.reason == image.REASON_BUDGET
    assert outcome.complete is False
    assert outcome.succeeded == 0
    # 预算为 0 时必须立刻返回，绝不等 3×0.3 秒
    assert elapsed < 0.25, f"超预算后没有及时收尾，耗时 {elapsed:.3f}s"
    assert len(renderer.calls) == 3, "三道题都提交了（只是结果被放弃）"


# ---------------------------------------------------------------- 闸门
def test_disabled_never_calls_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    """能力不可用时**一道都不跑**，且不构造客户端。

    这是第二道闸门：上层本就不该在不可用时调用这里，
    但真调了也必须什么都不做（防止「开关关着却悄悄生了一堆图」）。
    """
    from app.core.config import Settings

    settings = Settings(_env_file=None)  # 默认：开关关、无凭据
    assert settings.image_generation_available is False

    renderer = _install(monkeypatch, _Renderer())
    outcome = image.generate_for_questions(_questions(3), settings=settings)

    assert renderer.calls == []
    assert outcome.reason == image.REASON_DISABLED
    assert outcome.attempted == 0
    assert outcome.urls == {}
    assert outcome.complete is False


def test_configured_but_credentials_missing_is_still_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开关开着但凭据不全 ⇒ 同样一道都不跑（不能只信开关）。"""
    from app.core.config import Settings

    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("COS_REGION", "")
    monkeypatch.setenv("COS_BUCKET", "")
    settings = Settings(_env_file=None)

    renderer = _install(monkeypatch, _Renderer())
    outcome = image.generate_for_questions(_questions(3), settings=settings)

    assert renderer.calls == []
    assert outcome.reason == image.REASON_DISABLED


def test_concurrency_is_bounded(image_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """同时在跑的线程数不超过 `IMAGE_MAX_WORKERS`。

    上限是硬要求（与 `quiz_service._executor` 同一条理由）：无界并发会把进程打穿，
    而上游生图是慢调用，几个请求就能堆满线程。
    """
    settings = image_env(IMAGE_MAX_WORKERS="2")
    questions = _questions(3)

    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    def slow_render(*, question: Question, seq: int, run_token: str, settings: Any) -> str:
        with lock:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
        time.sleep(0.15)
        with lock:
            state["current"] -= 1
        return f"https://img.example.com/{seq}.jpg"

    monkeypatch.setattr(image, "_render_one", slow_render)
    outcome = image.generate_for_questions(questions, settings=settings)

    assert outcome.succeeded == 3
    assert state["peak"] <= 2, f"并发峰值 {state['peak']} 超过了配置的 2"
