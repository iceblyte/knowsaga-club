"""ChatOpenAI 工厂：统一构造指向 DeepSeek 的 LLM 实例。

⚠️ 三个必须遵守的坑（均为实测确认，见 docs/MVP开发计划.md §2.4.1）：

1. **必须显式关闭思考模式**。`deepseek-flash` 默认开启思考，会导致：
   - `content` 为空（推理 token 挤占 `max_completion_tokens`）
   - 强制 `tool_choice` 时直接 HTTP 400
   关闭方式：`extra_body={"thinking": {"type": "disabled"}}`

2. **`max_tokens` 参数已改名为 `max_completion_tokens`**（langchain-openai 1.6.2 实测，
   签名中已无 `max_tokens`）。写错会抛 TypeError。

3. **`with_structured_output()` 的 `method` 默认是 `json_schema`**，而 DeepSeek 不支持
   json_schema（会返回 400 `This response_format type is unavailable now`）。
   因此调用处**必须显式传 `method`**（`"json_mode"` 或 `"function_calling"`），
   或用本文件的 `build_structured_llm()` 让它按 `.env` 的配置补齐。
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings
from app.core.exceptions import ai_generation_failed
from app.core.logging import get_logger

logger = get_logger(__name__)

ChainName = Literal["quiz", "report"]


def build_chat_model(
    chain: ChainName = "quiz",
    *,
    settings: Settings | None = None,
    model: str | None = None,
    use_pro_model: bool = False,
    **overrides: Any,
) -> ChatOpenAI:
    """构造一个指向 DeepSeek 的 `ChatOpenAI`。

    Args:
        chain: 用于挑选该链路的温度/超时/token 预算。
        settings: 注入配置（测试用）；默认取全局单例。
        model: 显式指定模型名，优先级最高。
        use_pro_model: 为 True 时用 `DEEPSEEK_MODEL_PRO`（强推理档）。
        **overrides: 覆盖任意 ChatOpenAI 参数，供测试或特殊场景使用。

    Raises:
        AppError(5001): 未配置 API Key 时提前失败，避免发出必然失败的请求。
    """
    s = settings or get_settings()

    if not s.has_deepseek_key:
        raise ai_generation_failed("未配置 DEEPSEEK_API_KEY，无法调用大模型")

    if model is None:
        model = s.deepseek_model_pro if use_pro_model else s.deepseek_model

    if chain == "quiz":
        temperature, top_p = s.quiz_temperature, s.quiz_top_p
        timeout, max_retries = s.quiz_timeout_seconds, s.quiz_max_retries
        max_tokens = s.quiz_max_tokens
    else:
        temperature, top_p = s.report_temperature, s.report_top_p
        timeout, max_retries = s.report_timeout_seconds, s.report_max_retries
        max_tokens = s.report_max_tokens

    params: dict[str, Any] = {
        "model": model,
        "api_key": s.deepseek_api_key,
        "base_url": s.effective_base_url,
        "temperature": temperature,
        "top_p": top_p,
        "timeout": timeout,
        "max_retries": max_retries,
        # 注意：1.6.2 里没有 max_tokens，必须用 max_completion_tokens
        "max_completion_tokens": max_tokens,
        # 关闭思考模式（默认开启会导致空响应 / tool_choice 400）
        "extra_body": {"thinking": {"type": "enabled" if s.deepseek_thinking else "disabled"}},
    }

    # 仅在思考模式开启时才有意义的参数
    if s.deepseek_thinking:
        params["reasoning_effort"] = s.deepseek_reasoning_effort

    params.update(overrides)

    logger.debug("构造 LLM: chain=%s model=%s thinking=%s", chain, model, s.deepseek_thinking)
    return ChatOpenAI(**params)


def build_structured_llm(
    schema: Any,
    chain: ChainName = "quiz",
    *,
    method: Literal["function_calling", "json_mode"] | None = None,
    settings: Settings | None = None,
    use_pro_model: bool = False,
    include_raw: bool = False,
    **kwargs: Any,
):
    """构造带结构化输出的 LLM。

    **不传 `method` 时按 `.env` 的 `STRUCTURED_OUTPUT_PRIMARY` 走（当前为 `json_mode`）**。
    无论哪条通道都绝不能落到 langchain-openai 的默认值 `json_schema` ——
    DeepSeek 不支持它，会直接 400。

    Args:
        schema: Pydantic 模型类。
        method: 结构化输出方式；不传则用 `.env` 的 `STRUCTURED_OUTPUT_PRIMARY`。
        include_raw: 传 True 可拿到 `{"raw": AIMessage, "parsed": Model, "parsing_error": ...}`，
                     便于调试空响应与解析失败（审查链会用到）。
    """
    s = settings or get_settings()
    resolved = method or s.structured_output_primary  # type: ignore[assignment]

    if resolved == "json_schema":
        # 显式拦截，避免误用导致必然失败
        raise ValueError(
            "DeepSeek 不支持 method='json_schema'，请使用 'function_calling' 或 'json_mode'"
        )

    llm = build_chat_model(chain, settings=s, use_pro_model=use_pro_model, **kwargs)

    if resolved == "json_mode":
        # json_mode 要求 prompt 中出现 "json" 字样（官方硬性要求）
        return llm.with_structured_output(schema, method="json_mode", include_raw=include_raw)

    return llm.with_structured_output(
        schema, method="function_calling", include_raw=include_raw
    )
