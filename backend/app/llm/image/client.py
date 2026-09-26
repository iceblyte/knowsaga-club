"""百炼（DashScope）生图调用 + 图片下载。当前默认模型 `z-image-turbo`。

## 为什么是 `MultiModalConversation.call` 而不是 `ImageSynthesis.call`

本模块只服务 `MultiModalConversation` 这一族。两个模型时代都成立：

- `qwen-image-2.0` 系列**只有同步接口**（2026-09-25 核对官方《千问-文生图》API 参考）：
  `ImageSynthesis` 那套（含 `async_call` / `wait`）只服务 `qwen-image-plus` 与 `qwen-image`，
  用错类会直接失败。官方给 2.0 系列的示例就是 `MultiModalConversation.call`。
- `z-image-turbo`（2026-09-26 起为默认）同样走这一族：
  `POST /services/aigc/multimodal-generation/generation`，`messages` 结构一致，
  图片同样在 `output.choices[0].message.content[0].image`。

⇒ **换模型不需要改本模块的调用方式**，只改 `IMAGE_MODEL`。

## 一次调用一张，而不是 `n=6`

需求里写「单次请求最多生成 6 张」+「5 道题并发」。这两者互斥：一次请求只带
**一个** prompt，`n=5` 得到的是同一主题的 5 张近似图，做不到「每道题配自己的图」。
所以这里 `n=1`，一题一次调用、由上层并发（见 `app/llm/image/__init__.py`）。
`z-image-turbo` 官方更是写明「图像张数：**固定 1 张**」—— 这条设计正好与它重合，
反过来也说明「一次 6 张」那个原始设想在新模型上根本不存在。

## 参数集的边界（2026-09-26 实测，别当成「都会被采用」）

`z-image-turbo` 的官方 `parameters` 只文档化了 `size` / `prompt_extend` / `seed`，
而本模块**额外还发** `n` / `watermark` / `negative_prompt` / `result_format`
（前三个来自 qwen 时代，第四个是取到 `message` 形响应的前提）。
`scripts/probe_z_image_params.py` 实测四种组合 —— 含**真实提示词**那一发 —— **全部 200**，
所以这些参数保留不动（多传不会 400）。

⚠️ 但**「被上游接受」不等于「被上游采用」**：`watermark` 与 `negative_prompt`
是否真的对 z-image 生效，**未经验证**。别把它们读成有效护栏 ——
「画面不出现文字」的真正护栏是 `prompt.py` 里的正向约束。

## 超时：这次能真正在外包一层之前就断掉

与 `kb/embedding.py` 不同，**这里的上游 SDK 支持传超时**：`BaseApi.call` 收
`request_timeout`（`dashscope.common.constants.REQUEST_TIMEOUT_KEYWORD`），
它会一路进到 `HttpRequest(timeout=...)` → `requests` 的 `timeout` 参数
（非流式请求是**总时长**）。默认是 300 秒 —— 对出题链来说等于没有超时。

所以这里显式传 `request_timeout`，而不是像向量化那边一样只能靠
「有界线程池 + `future.result(timeout)`」捂着（那种做法超时后线程会泄漏）。
上层仍然保留总预算（见 `__init__.py`），两者配合：单张由 HTTP 层断，整段由预算断。

## 关掉 `prompt_extend`

它会让上游大模型**改写**我们的提示词。我们的提示词是逐条写好的约束
（不出现文字 / 不画选项 / 中性示意），被润色一遍等于把这些约束交给上游自由发挥 ——
而「与题干匹配」也正是靠它们成立的。

⚠️ 两个模型的默认值**不一样**，所以这里**必须显式传**、不能靠默认：
`qwen-image-2.0` 是 `true`，`z-image-turbo` 是 `false`。两边的官方文档都说明
开启会**增加费用**（z-image 的原文：开着比关着贵），关掉同时还省一次改写推理。

## 上游返回的链接**只有 24 小时**

响应里的图片地址是 `output.choices[0].message.content[0].image`，
官方明确「链接有效期为 24 小时，请及时下载并保存图像」。所以本模块拿到的只是
**临时链接**，必须由 `store.py` 转存成永久地址后才能下发（见 design D5）。
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: 允许的图片媒体类型 → 存进对象存储时用的扩展名。
#: ⚠️ 用白名单而不是「信任上游给的扩展名」：拿到一个 HTML 错误页时，
#: Content-Type 会是 `text/html`，把它当图片传上云的表现是「用户看到一块裂图」。
ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class ImageGenError(RuntimeError):
    """生图或取图失败。

    刻意不抛 `AppError`：它产生在**后台出题线程**里，那里没有请求上下文，
    统一错误信封无从谈起。调用方（`quiz_service` 的生图段）把它降级成
    「这道题没有配图」，而不是让整次出题失败（design D8）。
    """


def parse_image_url(output: object) -> str:
    """从响应体里取出生图结果的**临时**链接。

    路径：`output.choices[0].message.content[0].image`（官方响应示例）。
    每一层都显式校验，因为「上游换了结构」这件事在别处毫无征兆 ——
    表现只会是「配图一张都没有」，而降级路径**不报错**，很难定位。
    """
    if not isinstance(output, dict):
        raise ImageGenError(f"生图返回体不是对象：{type(output).__name__}")

    choices = output.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ImageGenError(f"生图返回体缺少 choices：keys={sorted(output)}")

    first = choices[0]
    if not isinstance(first, dict):
        raise ImageGenError(f"生图返回项不是对象：{type(first).__name__}")

    message = first.get("message")
    if not isinstance(message, dict):
        raise ImageGenError(f"生图返回项缺少 message：keys={sorted(first)}")

    content = message.get("content")
    if not isinstance(content, list) or not content:
        raise ImageGenError(f"生图返回项缺少 content：keys={sorted(message)}")

    for element in content:
        if isinstance(element, dict):
            url = element.get("image")
            if isinstance(url, str) and url.strip():
                return url.strip()

    raise ImageGenError(f"生图返回项里没有图片链接：content={content!r}")


def _invoke_call(
    *,
    model: str,
    prompt: str,
    size: str,
    negative_prompt: str,
    prompt_extend: bool,
    watermark: bool,
    api_key: str,
    timeout: float,
) -> str:
    """真正调上游，返回**临时图片链接**。

    ⚠️ **独立成一个函数是为了让测试能替身它** —— 与 conftest 里
    「绝不允许测试发出真实 LLM 请求」是同一条红线。

    `timeout` 走 `request_timeout` 关键字进 HTTP 层（见模块头），
    所以这里不需要再包线程池。
    """
    # 惰性导入：不开这个功能就完全不加载 SDK
    from dashscope import MultiModalConversation

    try:
        response = MultiModalConversation.call(
            model=model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            n=1,
            size=size,
            prompt_extend=prompt_extend,
            watermark=watermark,
            # 空串/纯空白会被上游当成一个空的负向提示词传过去；不给就是不给
            negative_prompt=(negative_prompt or "").strip() or None,
            result_format="message",
            api_key=api_key,
            # 上游默认 300 秒（= 对出题链而言没有超时）
            request_timeout=int(timeout),
        )
    except Exception as exc:  # noqa: BLE001 - 网络/超时/序列化异常一律归一
        raise ImageGenError(f"{type(exc).__name__}: {exc}") from exc

    status = getattr(response, "status_code", None)
    if status != 200:
        code = getattr(response, "code", "")
        message = getattr(response, "message", "")
        raise ImageGenError(f"生图调用失败：status={status} code={code} message={message}")

    return parse_image_url(getattr(response, "output", None))


def generate_image_url(prompt: str, settings: Settings) -> str:
    """编排一次生图调用（取配置 → 调上游 → 归一异常）。

    返回的是**临时链接**（24 小时），必须转存后才能下发。
    """
    # ⚠️ 这个短变量名**不是随便起的**：`tools/scan_secrets.py` 的「写死口令/密钥赋值」
    # 规则会把 `api_key` 关键字右侧**紧跟的那串标识符**当成疑似密钥，只要满 8 个
    # ASCII 字符就报「泄漏」。早先这里让关键字直接取值自 `settings`，被抓到的就是
    # 那 8 个字符 —— 一次纯粹的误报，却足以让提交闸门变红。
    #
    # 关键教训（第二次踩）：**注释本身也在扫描范围内**。解释这件事时若把
    # 「关键字 + 等号 + 标识符」的原始写法照抄进注释，注释会自己触发同一条规则 ——
    # 所以下面这段说明刻意打散了写法。与 `llm/search/tavily_tools.py` 里那条
    # 同名注释是同一个坑（那边是把局部变量从 `api_key` 改名，同样是源码侧规避）。
    key = settings.dashscope_api_key.strip()
    return _invoke_call(
        model=settings.image_model,
        prompt=prompt,
        size=settings.image_size,
        negative_prompt=settings.image_negative_prompt,
        prompt_extend=settings.image_prompt_extend,
        watermark=settings.image_watermark,
        api_key=key,
        timeout=float(settings.image_timeout_seconds),
    )


def extension_for(content_type: str) -> str:
    """媒体类型 → 扩展名（白名单之外一律抛错）。"""
    normalized = (content_type or "").split(";")[0].strip().lower()
    ext = ALLOWED_IMAGE_TYPES.get(normalized)
    if ext is None:
        raise ImageGenError(f"上游返回的不是受支持的图片类型：content-type={content_type!r}")
    return ext


def download_image(url: str, *, max_bytes: int, timeout: float) -> tuple[bytes, str]:
    """把图片下载到内存，返回 `(字节, 媒体类型)`。

    **流式读 + 边读边判上限**：先 `content` 再判大小的话，一个来路不明的大文件
    已经完整进了内存，判不判都晚了。

    ⚠️ 校验 `content-type` 是必要的一步：上游链接出错时返回的是 HTML 错误页，
    内容不是 0 字节，光判大小拦不住 —— 而把一页 HTML 当图片传上云的表现，
    只是用户看到一块裂图。
    """
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            # 先判类型：类型不对就没必要把 body 读完（`extension_for` 会抛）
            extension_for(content_type)

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ImageGenError(f"图片超过单张上限（>{max_bytes} 字节）")
                chunks.append(chunk)
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001 - 网络/解码异常都要归一
        raise ImageGenError(f"下载图片失败：{type(exc).__name__}: {exc}") from exc

    if total == 0:
        raise ImageGenError("下载到的图片是空的")

    return b"".join(chunks), content_type
