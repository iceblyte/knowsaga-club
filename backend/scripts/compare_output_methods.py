#!/usr/bin/env python
"""对比两种结构化输出通道（function_calling / json_mode）的**字段完整率**。

用法（在 backend/ 目录下）：

    .venv/Scripts/python.exe scripts/compare_output_methods.py
    .venv/Scripts/python.exe scripts/compare_output_methods.py --count 8

## 为什么需要这个脚本

Phase 1.14 抽验（10 次真实出题）暴露了一个数据：

    6/10 首轮 function_calling 成功，4/10 失败，失败原因完全相同 ——
    `questions.N.knowledge_point Field required` + `questions.N.difficulty Field required`

也就是说 `function_calling` 通道下，模型**系统性地省略**每道题的 `knowledge_point`
与 `difficulty`（它会把知识点放在顶层的 `knowledge_points` 里，但不在每道题里重复）。
失败本身能被降级通道救回来（最终 10/10 可渲染），但让 40% 的请求依赖重试有三个代价：
平均耗时翻倍、API 成本翻倍、以及降级通道一旦也退化就彻底失败。

所以这里把「哪种通道更听话」变成一个**可测量**的问题，而不是靠印象选默认值。
它不进 pytest —— 和 Phase 1.14 的抽验同理，它的价值就在于真实调用的不确定性。

## 实测结果与后续决定（2026-09-16）

`--count 6` 一轮的实测：

```
function_calling   4/6 = 67%   （失败 2 次，均为「空响应」）
json_mode          6/6 = 100%
```

注意失败形态与最初抽验时不同：抽验时 `function_calling` 报的是「缺
`knowledge_point`/`difficulty` 字段」，这次是空响应。同一通道两种坏法，
说明它整体上就是更不稳定 —— 结论不变，甚至更强。

据此把 `STRUCTURED_OUTPUT_PRIMARY` 调换为 `json_mode`、降级通道改为
`function_calling`（见 `app/core/config.py`）。保留降级而不是删掉，是因为两者
**失效原因不同**：若上游某天不再支持 `response_format=json_object`，只有换通道能救。

退出码：无论结果如何都返回 0；这是测量工具，不是验收工具。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.llm.langchain_factory import build_structured_llm  # noqa: E402
from app.llm.output_schemas import QuizDraft  # noqa: E402
from app.prompts.quiz_prompt import build_quiz_prompt  # noqa: E402

TOPICS = [
    "我想学习什么是 RAG，以及它和传统搜索有什么区别",
    "椭圆曲线加密为什么比 RSA 更难破解",
    "光合作用的光反应和暗反应分别在做什么",
    "TCP 三次握手为什么不能是两次",
    "明朝一条鞭法改革解决了什么问题",
    "复利和单利在长期投资里的差距有多大",
    "什么是注意力机制，它解决了什么问题",
    "为什么会有通货膨胀，它对普通人意味着什么",
    "分布式系统里的 CAP 定理到底在说什么",
    "免疫系统是怎么记住曾经遇到过的病毒的",
]

METHODS = ("function_calling", "json_mode")


def probe_once(method: str, topic: str, *, count: int = 5) -> tuple[bool, str]:
    """发一次真实请求，返回 (是否通过 schema 校验, 失败摘要)。"""
    settings = get_settings()
    prompt = build_quiz_prompt().invoke(
        {
            "user_input": topic,
            "question_count": count,
            "difficulty": "mixed",
            "reference": "",
        }
    )
    llm = build_structured_llm(
        QuizDraft, "quiz", method=method, include_raw=True, settings=settings
    )
    try:
        result = llm.invoke(prompt)
    except Exception as exc:  # noqa: BLE001 — 调用异常也算这一次失败
        return False, f"调用异常 {type(exc).__name__}"

    if result.get("parsing_error") is not None:
        return False, _summarize_error(str(result["parsing_error"]))
    if result.get("parsed") is None:
        return False, "空响应"
    return True, ""


def _summarize_error(text: str) -> str:
    """把 pydantic 的长错误压成「缺了哪些字段」。"""
    missing: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if "Field required" in line:
            continue
        # 形如 questions.0.knowledge_point
        if line.startswith("questions."):
            field = line.split(".")[-1]
            if field not in missing:
                missing.append(field)
    if missing:
        return "缺字段：" + "、".join(missing)
    return text.splitlines()[0][:80] if text else "未知错误"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6, help="每种通道的请求次数，默认 6")
    args = parser.parse_args()

    settings = get_settings()
    print("=" * 78)
    print("结构化输出通道对比 · 字段完整率")
    print("=" * 78)
    print(f"  模型    : {settings.deepseek_model}")
    print(f"  思考模式: {'开启' if settings.deepseek_thinking else '关闭'}")
    print(f"  当前配置: {settings.structured_output_primary} → {settings.structured_output_fallback}")
    print(f"  每种通道: {args.count} 次")
    print("=" * 78)

    if not settings.has_deepseek_key:
        print("[x] 未配置 DEEPSEEK_API_KEY")
        return 0

    summary: dict[str, tuple[int, int]] = {}

    for method in METHODS:
        print(f"\n--- {method} ---")
        ok = 0
        reasons: dict[str, int] = {}
        for index in range(args.count):
            topic = TOPICS[index % len(TOPICS)]
            passed, reason = probe_once(method, topic)
            if passed:
                ok += 1
                print(f"  [{index + 1:2}/{args.count}] ✅ 通过")
            else:
                reasons[reason] = reasons.get(reason, 0) + 1
                print(f"  [{index + 1:2}/{args.count}] ❌ {reason}")
        summary[method] = (ok, args.count)
        if reasons:
            for reason, times in sorted(reasons.items(), key=lambda kv: -kv[1]):
                print(f"        ×{times}  {reason}")

    print()
    print("=" * 78)
    print("结论")
    print("=" * 78)
    for method, (ok, total) in summary.items():
        print(f"  {method:<18} 一次通过 {ok}/{total} = {ok / total:.0%}")
    ranked = sorted(summary.items(), key=lambda kv: -kv[1][0])
    if len(ranked) == 2:
        best, (best_ok, _) = ranked[0]
        worst, (worst_ok, _) = ranked[1]
        if best_ok > worst_ok:
            mark = "（= 当前配置）" if best == settings.structured_output_primary else ""
            print(f"\n  → 建议把 STRUCTURED_OUTPUT_PRIMARY 设为 {best} {mark}".rstrip())
        elif best_ok == worst_ok:
            print(
                f"\n  → 两者一次通过率相同；保持当前首选 "
                f"{settings.structured_output_primary}（比较脚本不做决定）"
            )
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
