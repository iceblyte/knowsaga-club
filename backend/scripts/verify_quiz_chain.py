#!/usr/bin/env python
"""Phase 1.14 · 真实 API 抽验：连续出题 10 次，统计可直接渲染的比例。

用法（在 backend/ 目录下）：

    .venv/Scripts/python.exe scripts/verify_quiz_chain.py
    .venv/Scripts/python.exe scripts/verify_quiz_chain.py --count 5
    .venv/Scripts/python.exe scripts/verify_quiz_chain.py --verbose

## 为什么它不在 pytest 里

§10 的策略写得很清楚：**pytest 里 LLM 调用一律 mock**，保证确定性与速度。
而这个脚本的全部价值恰恰在于它的**不确定性** —— 它要暴露的就是真实模型的抖动：
空响应率、耗时分布、题型比例是否听话、有没有 Markdown 围栏漏出来。
把它塞进 pytest 会让 CI 随机变红，而随机变红的测试最后一定会被跳过。

## 「可渲染」是怎么判定的

不是「没抛异常」就算过 —— 那只是最低门槛。一份题库要真的能渲染到「挑战副本」页，
还需要满足若干**界面上看得见**的条件，比如判断题必须恰好两个选项、
题干不能是空字符串、选项文字不能长到把卡片撑破。这些条件 Pydantic 层不一定管，
但对界面是硬要求，所以在这里单独判。

退出码：可渲染比例 < 80% 时返回 1（§5 Phase 1 的验收线）。
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from pathlib import Path

# 允许直接以脚本方式运行（把 backend/ 加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.llm.quiz_chain import generate_quiz  # noqa: E402
from app.models.quiz import Quiz  # noqa: E402

# 10 个互不相同的主题，避免「同一主题重复出题」掩盖多样性问题
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

# 界面上看得见、Pydantic 不一定管的硬要求
MIN_STEM_LEN = 6
MIN_EXPLANATION_LEN = 10
MAX_OPTION_CHARS = 60
MAX_TITLE_CHARS = 24

_FENCE = re.compile(r"```")
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)


def check_renderable(quiz: Quiz) -> list[str]:
    """返回「不可渲染」的原因列表；空列表表示可以直接上屏。"""
    problems: list[str] = []

    if len(quiz.title) > MAX_TITLE_CHARS:
        problems.append(f"标题过长({len(quiz.title)}字)")
    if _FENCE.search(quiz.title) or _FENCE.search(quiz.summary):
        problems.append("标题/摘要里漏出 Markdown 围栏")
    if _MARKDOWN_HEADING.search(quiz.summary):
        problems.append("摘要里漏出 Markdown 标题")

    for question in quiz.questions:
        tag = question.id

        if len(question.stem) < MIN_STEM_LEN:
            problems.append(f"{tag} 题干过短")
        if _FENCE.search(question.stem):
            problems.append(f"{tag} 题干漏出 Markdown 围栏")
        if len(question.explanation) < MIN_EXPLANATION_LEN:
            problems.append(f"{tag} 讲解过短")

        if question.type == "judge":
            if len(question.options) != 2:
                problems.append(f"{tag} 判断题选项数不是 2")
            if {o.key for o in question.options} != {"T", "F"}:
                problems.append(f"{tag} 判断题选项键不是 T/F")
        else:
            if not (3 <= len(question.options) <= 5):
                problems.append(f"{tag} 选项数越界({len(question.options)})")

        for option in question.options:
            if not option.text.strip():
                problems.append(f"{tag} 存在空选项")
            if len(option.text) > MAX_OPTION_CHARS:
                problems.append(f"{tag} 选项文字过长({len(option.text)}字)")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10, help="抽验次数，默认 10")
    parser.add_argument("--verbose", action="store_true", help="打印每题题干摘要")
    parser.add_argument("--threshold", type=float, default=0.8, help="验收线，默认 0.8")
    args = parser.parse_args()

    settings = get_settings()

    print("=" * 78)
    print("Phase 1.14 · 真实出题链抽验")
    print("=" * 78)
    print(f"  模型        : {settings.deepseek_model}")
    print(f"  base_url    : {settings.effective_base_url}")
    print(f"  思考模式    : {'开启' if settings.deepseek_thinking else '关闭'}")
    print(f"  主/降级通道 : {settings.structured_output_primary} → {settings.structured_output_fallback}")
    print(f"  时间预算    : {settings.quiz_generation_budget_seconds}s")
    print(f"  抽验次数    : {args.count}")
    print("=" * 78)

    if not settings.has_deepseek_key:
        print("[x] 未配置 DEEPSEEK_API_KEY，无法抽验。")
        return 1

    ok_count = 0
    durations: list[float] = []
    rows: list[tuple[int, str, str, str, str]] = []
    mix_matches = 0

    for index in range(args.count):
        topic = TOPICS[index % len(TOPICS)]
        started = time.perf_counter()
        try:
            quiz = generate_quiz(
                user_input=topic,
                question_count=5,
                difficulty="mixed",
                settings=settings,
            )
        except AppError as exc:
            elapsed = time.perf_counter() - started
            durations.append(elapsed)
            rows.append((index + 1, f"{elapsed:6.1f}s", "❌", f"失败 code={exc.code}", topic[:18]))
            print(f"[{index + 1:2}/{args.count}] ❌ {elapsed:6.1f}s  code={exc.code} {exc.message}")
            continue

        elapsed = time.perf_counter() - started
        durations.append(elapsed)

        problems = check_renderable(quiz)
        if problems:
            rows.append((index + 1, f"{elapsed:6.1f}s", "⚠️", "；".join(problems[:2]), topic[:18]))
            print(f"[{index + 1:2}/{args.count}] ⚠️ {elapsed:6.1f}s  {problems[0]}")
        else:
            ok_count += 1
            rows.append(
                (index + 1, f"{elapsed:6.1f}s", "✅", quiz.question_stats.summary_text(), topic[:18])
            )
            print(
                f"[{index + 1:2}/{args.count}] ✅ {elapsed:6.1f}s  "
                f"{len(quiz.questions)} 题 · {quiz.question_stats.summary_text()} · "
                f"满分 {quiz.total_xp} XP"
            )

        # 题型比例是否听话（Prompt 要求 3 单选 + 1 多选 + 1 判断）
        stats = quiz.question_stats
        if (stats.single, stats.multiple, stats.judge) == (3, 1, 1):
            mix_matches += 1

        if args.verbose:
            for question in quiz.questions:
                print(f"        - [{question.type}] {question.stem[:44]}")

    # ---------- 汇总 ----------
    print()
    print("=" * 78)
    print("汇总")
    print("=" * 78)
    print(f"  {'#':>2}  {'耗时':>7}  {'结果':<2}  详情")
    for number, elapsed, mark, detail, topic in rows:
        print(f"  {number:>2}  {elapsed:>7}  {mark:<2}  {detail}   ({topic})")

    ratio = ok_count / args.count if args.count else 0.0
    print()
    print(f"  可直接渲染 : {ok_count} / {args.count} = {ratio:.0%}（验收线 {args.threshold:.0%}）")
    print(f"  题型完全符合 3/1/1 : {mix_matches} / {args.count}")
    if durations:
        print(
            f"  耗时       : 平均 {statistics.mean(durations):.1f}s · "
            f"中位 {statistics.median(durations):.1f}s · "
            f"最快 {min(durations):.1f}s · 最慢 {max(durations):.1f}s"
        )
    print("=" * 78)

    if ratio < args.threshold:
        print(f"[x] 未达验收线：{ratio:.0%} < {args.threshold:.0%}")
        return 1

    print("[ok] 通过 Phase 1.14 验收")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
