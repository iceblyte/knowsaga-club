"""手动探针：`z-image-turbo` 到底接受哪些参数？（**会发真实请求，不进 pytest**）

## 为什么需要它

`qwen-image-2.0` 与 `z-image-turbo` **同一个 API 家族**（都是
`POST /services/aigc/multimodal-generation/generation`，都走
`MultiModalConversation.call`），**但参数集不重合**。官方《Z-Image API 参考》
只文档化了 `parameters` 里的三个字段：

    size / prompt_extend / seed

而 `app/llm/image/client.py` 当前**正在发**这四样：
`n`、`watermark`、`negative_prompt`、`result_format`。
其中 `result_format="message"` 是拿 `output.choices[0].message.content[0].image`
这条路径的前提 —— z-image 的响应**本来就是**这个形状。

官方错误示例恰好是：

    {"code": "InvalidParameter", "message": "num_images_per_prompt must be 1"}

⇒ **多传参数是可能 400 的**，不能靠「应该会被忽略」蒙。这属于项目红线 7
「涉及外部服务的取值组合约束必须真跑一次端到端」。

## 用法（在 backend/ 下，用项目 venv）

    ./.venv/Scripts/python.exe scripts/probe_z_image_params.py

读根 `.env` 的 `DASHSCOPE_API_KEY`。**不会打印密钥**。会真的消耗几次生图额度。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402

PROMPT = "一只坐着的橘黄色的猫，表情愉悦，活泼可爱，逼真准确"

#: (用例名, size, 额外参数) —— 依次隔离「文档内参数」与「我们正在发的额外参数」。
CASES: tuple[tuple[str, str, dict], ...] = (
    ("A 仅文档内参数", "1024*1024", {}),
    ("B 加上我们正在发的 4 个参数", "1024*1024", {
        "n": 1,
        "watermark": False,
        "negative_prompt": "文字, 汉字, 字母, 水印, 标志, 低质量, 模糊",
        "result_format": "message",
    }),
    ("C 仅文档内参数 + 当前默认尺寸", "512*512", {}),
)

#: 用**真实提示词构建器**产出的提示词再打一发：验证出题链那一段（多行约束文本 +
#: 长度贴近 800 上限）在 z-image 侧也能通，而不是只验证了一句玩具提示词。
_REAL_PROMPT = None


def _real_prompt() -> str:
    """用 `app/llm/image/prompt.build_prompt` 造一条真实形态的提示词。"""
    global _REAL_PROMPT
    if _REAL_PROMPT is None:
        from types import SimpleNamespace

        from app.llm.image import prompt as prompt_builder

        question = SimpleNamespace(
            stem="下面关于咖啡豆烘焙的说法，哪一项是正确的？",
            knowledge_point="咖啡豆烘焙温度区间",
            options=[
                SimpleNamespace(text="烘焙温度越低酸味越重"),
                SimpleNamespace(text="一爆通常发生在 196°C 到 205°C"),
                SimpleNamespace(text="深烘的咖啡因含量一定更高"),
            ],
        )
        _REAL_PROMPT = prompt_builder.build_prompt(question)  # type: ignore[arg-type]
    return _REAL_PROMPT


def _describe_image_url(output: object) -> str:
    """按 client.parse_image_url 的同一路径取图，失败也不抛（探针要能继续跑）。"""
    try:
        content = output["choices"][0]["message"]["content"]  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001
        return f"<取不到 content: {type(exc).__name__}: {exc}>"
    for element in content if isinstance(content, list) else []:
        if isinstance(element, dict) and isinstance(element.get("image"), str):
            url = element["image"]
            return url[:72] + "…" if len(url) > 72 else url
    return f"<content 里没有 image：{content!r}>"


def main() -> int:
    settings = get_settings()
    if not settings.dashscope_api_key.strip():
        print("[FATAL] .env 里没有 DASHSCOPE_API_KEY，无法实测。")
        return 2

    from dashscope import MultiModalConversation

    key = settings.dashscope_api_key.strip()
    print(f"模型 = z-image-turbo   密钥 = 已配置（{len(key)} 字符，不回显）\n")

    failures = 0
    for name, size, extra in CASES:
        kwargs = {
            "model": "z-image-turbo",
            "messages": [{"role": "user", "content": [{"text": PROMPT}]}],
            "size": size,
            "prompt_extend": False,
            **extra,
        }
        print(f"--- {name} | size={size} | extra={sorted(extra) or '（无）'} ---")
        started = time.monotonic()
        try:
            response = MultiModalConversation.call(api_key=key, request_timeout=60, **kwargs)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ✗ 抛异常：{type(exc).__name__}: {exc}")
            print(f"  耗时 {time.monotonic() - started:.2f}s\n")
            continue

        elapsed = time.monotonic() - started
        status = getattr(response, "status_code", None)
        code = getattr(response, "code", "")
        message = getattr(response, "message", "")
        print(f"  status_code = {status}   code = {code!r}   message = {message!r}")
        print(f"  耗时 {elapsed:.2f}s")
        if status == 200:
            output = getattr(response, "output", None)
            usage = getattr(response, "usage", None)
            print(f"  image = {_describe_image_url(output)}")
            if isinstance(usage, dict):
                print(f"  usage = {usage}")
        else:
            failures += 1
        print()

    # ---- 用例 D：真实提示词（出题链那一段的实际形态）----
    # kwargs 刻意与 `client.generate_image_url` 的调用**逐项对齐**（含那些
    # 只存在于 qwen 文档、不确定 z-image 是否认的字段），这样 D 通过就等于
    # 「换模型后出题链那一段真能跑」。
    real = _real_prompt()
    print(f"--- D 真实提示词 | 长度={len(real)} 字符（上限 800）| size={settings.image_size} ---")
    started = time.monotonic()
    try:
        response = MultiModalConversation.call(
            api_key=key,
            request_timeout=60,
            model="z-image-turbo",
            messages=[{"role": "user", "content": [{"text": real}]}],
            size=settings.image_size,
            prompt_extend=settings.image_prompt_extend,
            watermark=settings.image_watermark,
            negative_prompt=(settings.image_negative_prompt or "").strip() or None,
            result_format="message",
            n=1,
        )
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print(f"  ✗ 抛异常：{type(exc).__name__}: {exc}")
    else:
        status = getattr(response, "status_code", None)
        print(f"  status_code = {status}   code = {getattr(response, 'code', '')!r}"
              f"   message = {getattr(response, 'message', '')!r}")
        print(f"  耗时 {time.monotonic() - started:.2f}s")
        if status == 200:
            print(f"  image = {_describe_image_url(getattr(response, 'output', None))}")
        else:
            failures += 1
    print()

    print("=" * 68)
    print(f"失败用例数 = {failures} / {len(CASES) + 1}")
    print("判读：")
    print("  · A 成功 ⇒ 模型与提示词形态可用（messages + text 单元素）。")
    print("  · B 成功 ⇒ 当前那几个额外参数**不会**把请求打挂，换模型只改配置即可。")
    print("  · B 失败而 A 成功 ⇒ **必须**把 client.py 砍到只剩文档内参数。")
    print("  · C 成功 ⇒ 现有默认尺寸 512*512 被接受（但它贴着总像素下限）。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
