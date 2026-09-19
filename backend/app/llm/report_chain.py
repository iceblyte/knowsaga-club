"""报告链：把一局的确定性事实变成一份可读的复盘报告。

## 与出题链唯一的行为差异：失败不是终点，而是降级

出题链在所有尝试都失败时抛 5001 —— 因为**模板拼出来的题本质是编造学习材料**，
用户无法分辨它与 AI 出的题有什么区别，这比直接报错「出题失败，请重试」有害得多。

报告链反过来：报告是**对已知数据（正确率 / XP / 金币 / 用时）的复述**，
AI 只负责把它讲成人话。所以模型全失败时，用确定性模板拼出来的报告**仍然是一份真话**，
用户拿到它不会学到任何错误的东西。裁决原文见 `docs/MVP开发计划.md` §6 第 6 条。

## 降级必须是可观测的

`generate_report_draft` 返回 `(草稿, degraded)`。保留这个布尔值不是为了好看：
报告链的失败**不会表现为报错**，只会表现为「用户拿到的报告话术越来越像模板」。
没有这个标记，兜底率从 2% 涨到 40% 这件事只有靠人去翻日志才发现。

## 三层保障的落点

| 层级 | 做什么 | 在哪里 |
|---|---|---|
| 1. 换通道重试 | 空响应 / 映射失败 / 结构非法 | `app.llm.fallback` |
| 2. 字段完整性兜底 | 模型漏了知识点 → 用事实补齐；模型说假话 → 用事实纠正 | `complete_draft` |
| 3. 整份模板兜底 | 全部尝试失败 → 用事实拼一份真话报告 | `build_template_draft` |

第 2 层对应 MVP开发计划 §8.4 那句「其余字段由 AI 报告链生成，**服务层做字段完整性兜底**」。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.llm import fallback
from app.llm.fallback import AttemptFailure
from app.llm.langchain_factory import build_structured_llm
from app.models.report import POINTS_MAX, ReportAdviceDraft, ReportDraft
from app.prompts.report_prompt import build_report_prompt

logger = get_logger(__name__)

#: 可替换的时钟，便于测试时间预算而不真的等待
_clock: Callable[[], float] = time.monotonic

#: `method` -> 可供 invoke 的 runnable
LlmFactory = Callable[[str], Any]


@dataclass(frozen=True)
class ReportFacts:
    """服务端已知的**事实**。模板兜底与字段兜底都只信它，不信模型。

    `mastered_points` / `weak_points` 由**本次作答**推导（答对的题的知识点 /
    答错的题的知识点），不是从用户的历史统计里拿的 —— 报告讲的是「这一局」，
    用历史统计会让用户看到「我没答错这个知识点啊」。
    """

    total_count: int
    correct_count: int
    wrong_count: int
    accuracy: int
    xp_gained: int
    coins_gained: int
    mastered_points: tuple[str, ...] = field(default_factory=tuple)
    weak_points: tuple[str, ...] = field(default_factory=tuple)


# -----------------------------------------------------------------------------
# 第 3 层：整份模板兜底
# -----------------------------------------------------------------------------
def build_template_draft(facts: ReportFacts) -> ReportDraft:
    """用事实拼一份复盘报告。**读起来像模板，但每一句都是真的。**

    这是本函数存在的全部意义：宁可承认「这次没能给你写得更细」，
    也不要生成一段听起来漂亮、但把答错说成答对的话。
    """
    weak_head = facts.weak_points[0] if facts.weak_points else ""
    mastered_head = facts.mastered_points[0] if facts.mastered_points else ""

    summary = [
        f"这次一共 {facts.total_count} 道题，你答对了 {facts.correct_count} 道，正确率 {facts.accuracy}%。",
    ]
    if facts.wrong_count > 0:
        summary.append(f"需要再巩固的是「{weak_head}」，这道题这次没答对。")
    else:
        summary.append("这次全部答对，说明这几个概念你已经拿稳了。")

    if mastered_head:
        summary.append(f"「{mastered_head}」这一类题目你处理得很稳，可以照这个思路继续。")
    else:
        summary.append(f"本局拿到 {facts.xp_gained} 点经验与 {facts.coins_gained} 枚金币。")

    advice: list[ReportAdviceDraft]
    if facts.wrong_count > 0:
        advice = [
            ReportAdviceDraft(
                title="重做错题",
                body=f"你在「{weak_head}」上答错了，把这道题再做一遍，比重新看一遍资料更管用。",
            ),
            ReportAdviceDraft(
                title="过几天回头复习",
                body="这道题已经排进「旧识重温」，到时间会在微信里提醒你。",
            ),
            ReportAdviceDraft(
                title="继续下一张卷轴",
                body="把这个概念用到真实场景里，比重复刷同类型题记得更久。",
            ),
        ]
    else:
        advice = [
            ReportAdviceDraft(
                title="换一张更难的卷轴",
                body="这次全部答对，可以试着挑战难度更高的题目了。",
            ),
            ReportAdviceDraft(
                title="回头看一眼讲解",
                body="答对不等于想透了，讲解里通常还有一层细节值得再看。",
            ),
            ReportAdviceDraft(
                title="讲给别人听",
                body="试着用自己的话复述一遍，能讲清楚才算真的掌握。",
            ),
        ]

    return ReportDraft(
        mastered_points=list(facts.mastered_points[:POINTS_MAX]),
        weak_points=list(facts.weak_points[:POINTS_MAX]),
        three_line_summary=summary,
        advice=advice,
    )


# -----------------------------------------------------------------------------
# 第 2 层：字段完整性兜底
# -----------------------------------------------------------------------------
def complete_draft(draft: ReportDraft, facts: ReportFacts) -> ReportDraft:
    """用事实补齐 / 纠正模型草稿里的知识点字段。

    两类处理：

    1. **补齐**：模型把知识点留空（它有时会认为「没什么可说」）→ 用本次作答推导的
       知识点填上。留空会让原型第 2 屏的两个 chip 区变成空卡片。
    2. **纠正**：模型说「全对但某处薄弱」这类与事实相反的话 → 一律以事实为准。
       这一条不是优化，是**真实性底线** —— 报告页的环上写着 100%，
       卡片却说「需要巩固」，用户没法判断该信哪个。

    条数（恰好 3 句 / 3 条）由 `ReportDraft` 的契约保证，这里不处理。
    """
    if facts.correct_count == 0:
        mastered: list[str] = []
    else:
        mastered = list(draft.mastered_points) or list(facts.mastered_points[:POINTS_MAX])

    if facts.wrong_count == 0:
        weak: list[str] = []
    else:
        weak = list(draft.weak_points) or list(facts.weak_points[:POINTS_MAX])

    if mastered == list(draft.mastered_points) and weak == list(draft.weak_points):
        return draft
    return draft.model_copy(update={"mastered_points": mastered, "weak_points": weak})


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
def _attempt_plan(settings: Settings) -> list[str]:
    """报告链的尝试顺序（交替主 / 降级通道）。

    实现与「为什么交替」的完整理由见 `app.llm.fallback.attempt_plan`。
    """
    return fallback.attempt_plan(
        settings.structured_output_primary,
        settings.structured_output_fallback,
        settings.report_max_retries,
    )


def generate_report_draft(
    *,
    topic: str,
    quiz_json: str,
    answer_records: str,
    score_summary: str,
    facts: ReportFacts,
    settings: Settings | None = None,
    llm_factory: LlmFactory | None = None,
) -> tuple[ReportDraft, bool]:
    """生成一份报告草稿。

    Args:
        topic: 本次主题（题库标题）。
        quiz_json: 题库 JSON（含题干、选项、答案、讲解、知识点）。
        answer_records: 逐题作答的可读文本。
        score_summary: 服务端算好的统计结果文本 —— 模型据此写解读，
            但**不产出**这些数字（理由见 `prompts/report_prompt.py`）。
        facts: 服务端已知的事实，用于字段兜底与模板兜底。
        settings: 注入配置（测试用）。
        llm_factory: 注入 runnable 构造器（测试用），签名 `(method) -> runnable`。

    Returns:
        `(草稿, degraded)`。`degraded=True` 表示这次是**模板兜底**产物。
        本函数**不抛 5001** —— 模型失败会降级而不是失败。

    Raises:
        AppError: 只有**配置类**错误会穿透（例如未配置 `DEEPSEEK_API_KEY`）。
            这类错误必须让任务失败：如果把它也降级成模板报告，
            线上会表现为「报告质量一直很差」，而没人知道模型一次都没调通。
    """
    s = settings or get_settings()
    factory: LlmFactory = llm_factory or (
        lambda method: build_structured_llm(
            ReportDraft, "report", method=method, include_raw=True, settings=s
        )
    )

    prompt = build_report_prompt().invoke(
        {
            "topic": topic,
            "quiz_json": quiz_json,
            "answer_records": answer_records,
            "score_summary": score_summary,
        }
    )

    plan = _attempt_plan(s)
    started_at = _clock()
    failures: list[AttemptFailure] = []

    for index, method in enumerate(plan):
        # 第一次尝试永远放行：预算是「早点放弃」，不是「根本别试」
        if index:
            elapsed = _clock() - started_at
            if elapsed >= s.report_generation_budget_seconds:
                failures.append(
                    AttemptFailure(method, fallback.REASON_BUDGET, f"elapsed={elapsed:.1f}s")
                )
                logger.warning(
                    "报告链：已用时 %.1fs，越过 %ss 预算，放弃剩余 %d 次尝试（将降级为模板报告）",
                    elapsed,
                    s.report_generation_budget_seconds,
                    len(plan) - index,
                )
                break

        try:
            result = factory(method).invoke(prompt)
        except AppError:
            # 配置类异常（未配置 Key 等）本身就带着准确原因，降级会掩盖它
            raise
        except Exception as exc:  # noqa: BLE001 — 网络/上游异常一律算作一次可重试的失败
            failures.append(AttemptFailure(method, fallback.REASON_INVOKE, repr(exc)[:200]))
            logger.warning("报告链：第 %d 次尝试（%s）调用异常：%s", index + 1, method, exc)
            continue

        draft, failure = fallback.classify_result(method, result, ReportDraft)
        if draft is None:
            failures.append(failure)  # type: ignore[arg-type]
            logger.warning(
                "报告链：第 %d 次尝试（%s）失败 reason=%s detail=%s",
                index + 1,
                method,
                failure.reason,  # type: ignore[union-attr]
                failure.detail,  # type: ignore[union-attr]
            )
            continue

        logger.info("报告链：第 %d 次尝试（%s）成功", index + 1, method)
        return complete_draft(draft, facts), False

    logger.warning(
        "报告链全部 %d 次尝试失败，降级为确定性模板报告：%s",
        len(failures),
        fallback.summarize_failures(failures),
    )
    return build_template_draft(facts), True
