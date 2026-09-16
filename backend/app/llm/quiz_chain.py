"""出题链：把一次学习需求变成一份通过校验的 `Quiz`。

## 这条链要解决的真实问题

DeepSeek 官方明确说明了 JSON Output **偶发返回空内容**。对一个「点一下就等着出题」的
产品来说，「偶发」等于「每次发布都会有人踩到」。所以出题链的核心不是调用模型，
而是**把每一次失败都变成可以继续尝试的下一步**，直到要么拿到合格题库、要么明确报错。

## 兜底阶梯

```
第 1 次  主通道   STRUCTURED_OUTPUT_PRIMARY  （默认 json_mode）
第 2 次  降级通道 STRUCTURED_OUTPUT_FALLBACK （默认 function_calling）
第 3 次  主通道   ┐
第 4 次  降级通道 ┘ 共 2 + QUIZ_MAX_RETRIES 次
```

两个通道**交替**而不是「先用主通道连撞三次」：空响应是瞬时的（换不换通道都一样），
而通道不兼容只有换通道能救回来 —— 交替在最坏情况下不亏，在最好情况下快得多。
完整理由见 `_attempt_plan` 的文档字符串。

主通道为什么是 `json_mode` 而不是 `function_calling`：实测一次通过率 100% vs 67%，
且 `function_calling` 的失败形态是「模型系统性省略每题的 `knowledge_point`/`difficulty`」
（嵌套字段在工具调用参数里更容易被省略）。量化过程见
`backend/scripts/compare_output_methods.py` 与 `docs/MVP开发计划.md` §2.4.1。

任何一次尝试只要「拿到通过校验的草稿」就立刻返回；全部失败才抛 5001。
此外还有一道**总时间预算**（`QUIZ_GENERATION_BUDGET_SECONDS`）：
越过预算就不再发起剩余尝试 —— 快速失败比让用户干等更友好。

## 关于「确定性模板」这一级

`docs/方案设计文档.md` 里描述过五级兜底，最后一级是「确定性模板」。
这一级**属于报告链，不属于出题链**，因此这里没有实现，原因有两条：

1. 报告是**对已知数据的复述**（正确率、XP、金币都是确定性的），
   AI 只负责把它讲成人话，所以模板降级后仍然是一份真话。
2. 题库是**纯生成内容**。用模板拼出来的题，本质是编造的学习材料 ——
   用户无法分辨它与 AI 出的题有什么区别，这比直接报错「出题失败，请重试」有害得多。

所以出题链停在 5001，把选择权交回用户。这条判断记在 `docs/MVP开发计划.md` 的风险对策里。

## 为什么不直接信任 `parsed`

即使 `with_structured_output` 返回了对象，也要再过一遍 `QuizDraft` 的校验
（题量 3–5、answer ⊆ options 等）。质量闸门只有一道，就在 `QuizDraft`/`Question` 的
Pydantic 校验器里 —— 脏数据绝不外传（§11）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ai_generation_failed
from app.core.logging import get_logger
from app.llm.langchain_factory import build_structured_llm
from app.llm.output_schemas import QuizDraft, draft_to_quiz
from app.models.quiz import Quiz
from app.prompts.quiz_prompt import QUIZ_MAX_QUESTIONS, build_quiz_prompt

logger = get_logger(__name__)

#: 可替换的时钟，便于测试时间预算而不真的等待
_clock: Callable[[], float] = time.monotonic

#: `method` -> 可供 invoke 的 runnable
LlmFactory = Callable[[str], Any]

# 失败原因（写日志用，不对外返回）
REASON_EMPTY = "empty_response"
REASON_MAPPING = "schema_mapping_failed"
REASON_INVALID = "invalid_draft"
REASON_INVOKE = "invoke_error"
REASON_BUDGET = "budget_exhausted"
REASON_SHAPE = "unexpected_output_shape"


@dataclass(frozen=True)
class AttemptFailure:
    """一次失败尝试的归档。"""

    method: str
    reason: str
    detail: str = ""


def _attempt_plan(settings: Settings) -> list[str]:
    """按配置排出完整尝试顺序：**主通道与降级通道交替**。

    ```
    retries=2（默认）→ [primary, fallback, primary, fallback]   共 4 次
    retries=0        → [primary, fallback]                      共 2 次
    ```

    为什么交替，而不是「先连撞 3 次主通道再降级」：

    - 如果失败原因是**通道不兼容**（例如上游某天又不支持 tool_choice），
      同一条通道重试多少次都不会成功，只有换通道能救 —— 交替能立刻覆盖这种情况；
    - 如果失败原因是**瞬时**的（空响应），换不换通道成功概率一样，
      交替并不会变差。

    也就是说，交替在最坏情况下不亏，在最好情况下显著更快。
    """
    primary = settings.structured_output_primary
    fallback = settings.structured_output_fallback

    total = 2 + max(0, settings.quiz_max_retries)
    return [primary if index % 2 == 0 else fallback for index in range(total)]


def _describe_raw(raw: Any) -> str:
    """把原始返回压成一行可读的诊断信息（不打全量内容，避免日志炸掉）。"""
    if raw is None:
        return "raw=None"
    content = getattr(raw, "content", None)
    tool_calls = getattr(raw, "tool_calls", None)

    if isinstance(content, str):
        content_desc = f"content_len={len(content)}"
    elif content:
        content_desc = f"content_blocks={len(content)}"
    else:
        content_desc = "content_empty"

    return f"{content_desc} tool_calls={len(tool_calls) if tool_calls else 0}"


def _classify(method: str, result: Any) -> tuple[QuizDraft | None, AttemptFailure | None]:
    """把一次 invoke 的返回值判定为「合格草稿」或「一次失败」。"""
    if not isinstance(result, dict):
        return None, AttemptFailure(method, REASON_SHAPE, f"type={type(result).__name__}")

    parsing_error = result.get("parsing_error")
    if parsing_error is not None:
        return None, AttemptFailure(method, REASON_MAPPING, str(parsing_error)[:200])

    parsed = result.get("parsed")
    if parsed is None:
        return None, AttemptFailure(method, REASON_EMPTY, _describe_raw(result.get("raw")))

    try:
        draft = parsed if isinstance(parsed, QuizDraft) else QuizDraft.model_validate(parsed)
    except ValidationError as exc:
        # 字段缺失 / 题量越界 / 答案不在选项里 —— 全部走这里
        return None, AttemptFailure(method, REASON_INVALID, str(exc)[:200])

    return draft, None


def generate_quiz(
    *,
    user_input: str,
    question_count: int = QUIZ_MAX_QUESTIONS,
    difficulty: str = "mixed",
    reference: str = "",
    settings: Settings | None = None,
    llm_factory: LlmFactory | None = None,
) -> Quiz:
    """生成一份题库；所有尝试都失败时抛 `AppError(5001)`。

    Args:
        user_input: **已清洗**的用户输入（调用方负责 `validate_input` + `check_content`）。
        question_count: 期望题量，3–5。
        difficulty: `easy` / `medium` / `hard` / `mixed`。
        reference: 检索到的参考资料；未联网时传空串。
        settings: 注入配置（测试用）。
        llm_factory: 注入 runnable 构造器（测试用）。签名 `(method) -> runnable`。

    Raises:
        AppError: code=5001，所有尝试均未产出合格题库或已越过时间预算。
    """
    s = settings or get_settings()
    factory: LlmFactory = llm_factory or (
        lambda method: build_structured_llm(
            QuizDraft, "quiz", method=method, include_raw=True, settings=s
        )
    )

    prompt = build_quiz_prompt().invoke(
        {
            "user_input": user_input,
            "question_count": question_count,
            "difficulty": difficulty,
            "reference": reference or "",
        }
    )

    plan = _attempt_plan(s)
    started_at = _clock()
    failures: list[AttemptFailure] = []

    for index, method in enumerate(plan):
        # 第一次尝试永远放行：预算是「早点放弃」，不是「根本别试」
        if index:
            elapsed = _clock() - started_at
            if elapsed >= s.quiz_generation_budget_seconds:
                failures.append(
                    AttemptFailure(method, REASON_BUDGET, f"elapsed={elapsed:.1f}s")
                )
                logger.warning(
                    "出题链：已用时 %.1fs，越过 %ss 预算，放弃剩余 %d 次尝试",
                    elapsed,
                    s.quiz_generation_budget_seconds,
                    len(plan) - index,
                )
                break

        try:
            result = factory(method).invoke(prompt)
        except AppError:
            # 业务异常（未配置 Key 等）本身就带着准确原因，继续重试只会掩盖它
            raise
        except Exception as exc:  # noqa: BLE001 — 网络/上游异常一律算作一次可重试的失败
            failures.append(AttemptFailure(method, REASON_INVOKE, repr(exc)[:200]))
            logger.warning("出题链：第 %d 次尝试（%s）调用异常：%s", index + 1, method, exc)
            continue

        draft, failure = _classify(method, result)
        if draft is None:
            failures.append(failure)  # type: ignore[arg-type]
            logger.warning(
                "出题链：第 %d 次尝试（%s）失败 reason=%s detail=%s",
                index + 1,
                method,
                failure.reason,  # type: ignore[union-attr]
                failure.detail,  # type: ignore[union-attr]
            )
            continue

        logger.info("出题链：第 %d 次尝试（%s）成功，题量 %d", index + 1, method, len(draft.questions))
        return draft_to_quiz(draft, user_input=user_input)

    # 全部失败：把每一次的原因压进 detail，日志里能直接看出是哪一环出的问题
    summary = "; ".join(f"{f.method}:{f.reason}" for f in failures)
    logger.error("出题链彻底失败（共 %d 次尝试）：%s", len(failures), summary)
    raise ai_generation_failed(detail=f"attempts={len(failures)} failures=[{summary}]")
