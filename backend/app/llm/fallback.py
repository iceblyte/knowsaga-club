"""结构化输出的兜底阶梯 —— 出题链与报告链**共用**。

## 为什么抽出来

「主通道与降级通道交替重试 + 总时间预算」这套阶梯，是两条链**唯一正确的做法**，
而不是两处可以各自发挥的实现细节：

- 交替的原因（通道不兼容同通道重试无用、瞬时失败换通道不亏）与链路无关；
- 预算的原因（快速失败比让用户干等更友好）也与链路无关；
- 分类失败原因（空响应 / 映射失败 / 结构非法）的方式更是完全一样的。

如果两条链各写一份，最可能的结局是：某天有人把出题链的阶梯调好了
（比如把交替改成「先撞两次主通道」），报告链**静默地**停在旧行为上 ——
而这种差异只会在线上偶发失败率变化时才被发现。

所以这里只放「与链路无关」的部分。链路的差异（用哪个 Schema、失败后是报错
还是降级成模板、Prompt 怎么渲染）留在各自的链里。

## 四级失败原因

| 原因 | 含义 | 能不能靠重试救回来 |
|---|---|---|
| `empty_response` | 模型返回了但内容为空（DeepSeek 官方已知问题） | 能，换不换通道都一样 |
| `schema_mapping_failed` | 返回了内容但结构化解析失败（常见于被 ``` 围栏包裹） | 能，换通道把握更大 |
| `invalid_draft` | 解析成功但没通过 Pydantic 校验（字段缺失 / 越界） | 能，模型每次输出不完全一样 |
| `invoke_error` | 调用本身抛异常（网络 / 上游 5xx） | 能，但受总预算约束 |
| `budget_exhausted` | 越过总时间预算，主动放弃 | 不能 —— 这是放弃本身 |
| `unexpected_output_shape` | `with_structured_output` 返回了非 dict（框架版本变化） | 大概率不能，但值得试 |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

# 失败原因（写日志用，不对外返回）
REASON_EMPTY = "empty_response"
REASON_MAPPING = "schema_mapping_failed"
REASON_INVALID = "invalid_draft"
REASON_INVOKE = "invoke_error"
REASON_BUDGET = "budget_exhausted"
REASON_SHAPE = "unexpected_output_shape"

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class AttemptFailure:
    """一次失败尝试的归档。`reason` 取值见模块说明的表。"""

    method: str
    reason: str
    detail: str = ""


def attempt_plan(primary: str, fallback: str, retries: int) -> list[str]:
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

    也就是说，交替在最坏情况下不亏，在最好情况下显著快得多。
    """
    total = 2 + max(0, retries)
    return [primary if index % 2 == 0 else fallback for index in range(total)]


def describe_raw(raw: Any) -> str:
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


def classify_result(
    method: str, result: Any, model_cls: type[ModelT]
) -> tuple[ModelT | None, AttemptFailure | None]:
    """把一次 invoke 的返回值判定为「合格草稿」或「一次失败」。

    Args:
        method: 本次用的通道（只用于归档失败原因）。
        result: `with_structured_output(..., include_raw=True)` 的返回值。
        model_cls: 期望的 Pydantic 模型类。

    Returns:
        `(草稿, None)` 或 `(None, 失败归档)`，二者恰有一个非空。
    """
    if not isinstance(result, dict):
        return None, AttemptFailure(method, REASON_SHAPE, f"type={type(result).__name__}")

    parsing_error = result.get("parsing_error")
    if parsing_error is not None:
        return None, AttemptFailure(method, REASON_MAPPING, str(parsing_error)[:200])

    parsed = result.get("parsed")
    if parsed is None:
        return None, AttemptFailure(method, REASON_EMPTY, describe_raw(result.get("raw")))

    try:
        draft = parsed if isinstance(parsed, model_cls) else model_cls.model_validate(parsed)
    except ValidationError as exc:
        return None, AttemptFailure(method, REASON_INVALID, str(exc)[:200])

    return draft, None


def summarize_failures(failures: list[AttemptFailure]) -> str:
    """把失败清单压成一行，供日志与异常 detail 使用。"""
    return "; ".join(f"{f.method}:{f.reason}" for f in failures)
