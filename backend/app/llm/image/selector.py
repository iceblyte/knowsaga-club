"""配图判断：决定这次**哪几道题**值得配图（`add-question-image-generation` 第 18 组）。

## 为什么要有这一步

配图逐张计费。一套 5 道题里往往有 2–3 道是抽象概念、纯逻辑或文字表述题，
画出来的东西对理解没有增益 —— 2026-09-26 的人眼验收里，抽象题被画成了
花、枫叶、灯泡（证据 `docs/image-chain-evidence-2026-09-26.txt`）。
所以生图之前先让模型挑一遍，只给挑中的题花钱。

## 契约：**不抛异常，且失败时回退到「全都配」**

调用方是 `quiz_service._render_images`，跑在后台线程里 —— 抛出去就是任务
永远停在 running（前端一直转圈）。所以这里的每一条路径都返回结果：

| 情形 | 返回值 | 结果 |
|---|---|---|
| 开关关着 | `ids=None`，`reason=disabled` | 全部配图（回到接入本功能之前的行为） |
| 判断成功 | `ids=frozenset({...})`，`reason=judged` | 只给这些题配图（可能是**空集**） |
| 判断没成（空响应 / 解析失败 / 超时 / 没 Key） | `ids=None`，`reason=fallback` | 全部配图 |

⚠️ **`ids=None` 与 `ids=frozenset()` 是两个不同的意思**：
前者是「没判成，全都配」，后者是「模型明确说都不需要」。
把两者混成一个值，「判断器故障」就会静默表现成「用户一张图都没有」——
那正是 `tests/test_image_select.py` 第一条硬契约要防的。

## 为什么只调一次、不重试

出题链有一套「主 / 降级通道交替重试」的阶梯（`llm/fallback.py`），这里**不用**：
判断失败的代价只是「回到现状的成本」（全都配），不是故障。为它加一轮重试
就得多等一个 timeout，而收益（少花几张图的钱）远小于让用户多等十几秒。
若线上发现判断成功率长期偏低，`reason=fallback` 的 WARNING 日志会暴露它，
那时再加重试不迟（属独立优化，见 design D18）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm import fallback
from app.llm.langchain_factory import build_structured_llm
from app.llm.output_schemas import ImageSelectionDraft
from app.models.quiz import Question
from app.prompts.image_select_prompt import (
    build_image_select_prompt,
    format_question_list,
)

logger = get_logger(__name__)

#: 判断成功。
REASON_JUDGED = "judged"
#: 开关关着，**没有**判断（等于「全都配」）。
REASON_DISABLED = "disabled"
#: 判断没成，回退为「全都配」（见模块头第二条契约）。
REASON_FALLBACK = "fallback"

#: 判断的输出很短（一个题号数组），用不着出题链那份 4096 的 token 预算。
#: 给 512 留足余量，同时避免模型被诱导去展开解释。
_MAX_SELECT_TOKENS = 512

#: 判断应当**确定性**，不欢迎发挥。
_TEMPERATURE = 0.0

#: 造一个可 invoke 的 runnable。测试用它注入替身（唯一的外部依赖点）。
LlmFactory = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class ImageSelection:
    """一次判断的结果。

    `ids` 为 `None` 表示「全都配」（没判成或开关关着）；
    为 `frozenset()` 表示「模型说都不需要」。
    """

    ids: frozenset[str] | None
    reason: str
    detail: str = ""

    @property
    def selects_all(self) -> bool:
        """是否「全都配」——即**没有**得到一份有效的选题结果。"""
        return self.ids is None


def _default_factory(settings: Settings) -> LlmFactory:
    """按配置造真实的结构化输出 runnable（出题的 DeepSeek，同一个 Key）。"""

    def _build() -> Any:  # noqa: ANN401 - langchain runnable
        return build_structured_llm(
            ImageSelectionDraft,
            "quiz",
            method=settings.structured_output_primary,  # type: ignore[arg-type]
            settings=settings,
            include_raw=True,  # `fallback.classify_result` 需要 parsed/raw/parsing_error
            temperature=_TEMPERATURE,
            max_completion_tokens=_MAX_SELECT_TOKENS,
            timeout=float(settings.image_select_timeout_seconds),
        )

    return _build


def select_for_images(
    questions: Sequence[Question],
    *,
    settings: Settings,
    llm_factory: LlmFactory | None = None,
) -> ImageSelection:
    """判断这批题里哪些值得配图。**不抛异常**（见模块头契约）。

    Args:
        questions: 已出好、待配图的题目。
        settings: 配置。`image_select_enabled` 为假时直接返回「全都配」。
        llm_factory: 注入模型构造器（测试用）。签名 `() -> runnable`。

    Returns:
        `ImageSelection`。`ids` 为 `None` 表示「全都配」，否则是选中的题号集合。
    """
    if not questions:
        return ImageSelection(ids=frozenset(), reason=REASON_JUDGED, detail="no_questions")

    if not settings.image_select_enabled:
        logger.info("配图判断已关闭（IMAGE_SELECT_ENABLED=false），本次全部配图")
        return ImageSelection(ids=None, reason=REASON_DISABLED)

    known_ids = {question.id for question in questions}

    try:
        factory = llm_factory or _default_factory(settings)
        prompt = build_image_select_prompt().invoke(
            {"question_list": format_question_list(questions)}
        )
        result = factory().invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - 判断失败必须降级，不能冒泡到后台线程
        logger.warning(
            "配图判断调用失败，本次回退为全部配图（%d 道题）：%r",
            len(known_ids),
            exc,
        )
        return ImageSelection(ids=None, reason=REASON_FALLBACK, detail=repr(exc)[:200])

    draft, failure = fallback.classify_result(
        settings.structured_output_primary, result, ImageSelectionDraft
    )
    if draft is None:
        logger.warning(
            "配图判断未通过校验（%s: %s），本次回退为全部配图（%d 道题）",
            failure.reason,  # type: ignore[union-attr]
            failure.detail,  # type: ignore[union-attr]
            len(known_ids),
        )
        return ImageSelection(
            ids=None,
            reason=REASON_FALLBACK,
            detail=f"{failure.reason}: {failure.detail}",  # type: ignore[union-attr]
        )

    # 模型编出来的题号一律丢掉：留着的话上层会去找一道不存在的题
    selected = {
        str(raw).strip()
        for raw in draft.ids
        if str(raw).strip() in known_ids
    }
    dropped = len({str(raw).strip() for raw in draft.ids}) - len(selected)
    if dropped:
        logger.warning("配图判断给出了 %d 个不在清单里的题号，已忽略", dropped)

    logger.info(
        "配图判断完成：选中 %d / %d 道（%s）",
        len(selected),
        len(known_ids),
        ", ".join(sorted(selected)) or "一道都不需要",
    )
    return ImageSelection(
        ids=frozenset(selected),
        reason=REASON_JUDGED,
        detail=f"selected={len(selected)}/{len(known_ids)}",
    )


__all__ = [
    "REASON_DISABLED",
    "REASON_FALLBACK",
    "REASON_JUDGED",
    "ImageSelection",
    "LlmFactory",
    "select_for_images",
]
