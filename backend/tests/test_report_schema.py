"""报告契约（`app/models/report.py`）测试 —— TDD 红灯先行。

守住的硬约束：

1. `three_line_summary` **恰好 3 条**、`advice` **恰好 3 条** —— 原型 03 的
   第 2/3 屏是按固定条数排版卡片，少一条就塌版。校验放在契约层而不是服务层，
   这样「模型少给一条」会在构造对象的那一刻就炸，而不是等渲染时才发现。
2. 统计数字一律是整数 / 定长小数，**不允许浮点尾数** —— 它们要写进 `DECIMAL(6,2)`
   并与 `attempts` 上已有的值逐位对齐（报告页的数字必须与结算页一致）。
3. 全对时不得出现薄弱知识点、全错时不得出现掌握知识点。
   「全对但报告告诉你某处薄弱」是最伤信任的一类错误 —— 用户没法判断该信哪个。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.report import (
    POINTS_MAX,
    Report,
    ReportAction,
    ReportActionKind,
    ReportAdvice,
    ReportDraft,
    ReportGenerateRequest,
)


def _advice(title: str = "重做错题", body: str = "再练一遍会更牢。") -> dict:
    return {"title": title, "body": body}


def _draft(**overrides: object) -> dict:
    payload: dict = {
        "mastered_points": ["RAG 基本定义"],
        "weak_points": ["向量检索"],
        "three_line_summary": ["第一句。", "第二句。", "第三句。"],
        "advice": [_advice(), _advice("复习", "按曲线复习。"), _advice("继续", "换张卷轴。")],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- 草稿（模型产出）
def test_draft_accepts_well_formed_payload() -> None:
    draft = ReportDraft.model_validate(_draft())
    assert len(draft.three_line_summary) == 3
    assert len(draft.advice) == 3


@pytest.mark.parametrize("count", [0, 1, 2, 4, 5])
def test_draft_rejects_wrong_summary_line_count(count: int) -> None:
    with pytest.raises(ValidationError):
        ReportDraft.model_validate(
            _draft(three_line_summary=[f"第 {i} 句。" for i in range(count)])
        )


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_draft_rejects_wrong_advice_count(count: int) -> None:
    with pytest.raises(ValidationError):
        ReportDraft.model_validate(
            _draft(advice=[_advice(f"建议 {i}") for i in range(count)])
        )


def test_draft_ignores_unknown_fields() -> None:
    """模型多回一个字段不该让整份报告失败 —— 严格模式会让小失误变成白屏。"""
    draft = ReportDraft.model_validate(_draft(accuracy=80, extra_note="多余"))
    assert not hasattr(draft, "accuracy")


def test_draft_rejects_blank_advice_title() -> None:
    with pytest.raises(ValidationError):
        ReportDraft.model_validate(_draft(advice=[_advice(title="  "), _advice("b"), _advice("c")]))


def test_draft_allows_empty_point_lists() -> None:
    """全对时 `weak_points` 就是空数组，这是合法输入而不是缺字段。"""
    draft = ReportDraft.model_validate(_draft(weak_points=[]))
    assert draft.weak_points == []


def test_draft_accepts_one_point_per_question() -> None:
    """回归用例：知识点上限是**题量**（5），不是建议条数（3）。

    `max_length` 一度被写成 `ADVICE_COUNT`（3）。后果不是「少显示一个标签」，
    而是**整份报告降级成模板**：「5 道题错 4 道」这种完全正常的一局里，
    模型如实给出 4 个薄弱点 → 草稿判非法 → 重试 → 再拒 → 模板兜底。
    实测在浏览器里看到的就是模板话术，日志只有一行 `schema_mapping_failed`。

    所以这里逐个钉住 3、4、5 都是合法输入 —— 写成参数化是为了让「3 也合法」
    这件事留在用例里（否则有人会以为「反正 3 以内」而改回去）。
    """
    for count in (3, 4, 5):
        points = [f"知识点 {i}" for i in range(count)]
        draft = ReportDraft.model_validate(_draft(weak_points=points, mastered_points=points))
        assert draft.weak_points == points
        assert draft.mastered_points == points


def test_draft_rejects_absurd_point_count() -> None:
    """上界不是「不限」：模型偶尔会吐一长串标签，那确实是跑偏了，该重试。

    5 是**有依据的**上界（每个题最多带 1 个知识点，题量上限就是 5），
    所以第 6 个标签一定超出了这次挑战能产生的事实范围。
    """
    with pytest.raises(ValidationError):
        ReportDraft.model_validate(
            _draft(weak_points=[f"知识点 {i}" for i in range(POINTS_MAX + 1)])
        )


# ---------------------------------------------------------------- 动作
def test_action_kind_is_closed_enum() -> None:
    """动作类型是闭集 —— 前端按 kind 决定渲染按钮还是胶囊，不能有野值。"""
    assert {k.value for k in ReportActionKind} == {
        "retry_question",
        "review_plan",
        "new_scroll",
    }


def test_retry_question_action_accepts_target() -> None:
    action = ReportAction(kind=ReportActionKind.RETRY_QUESTION, label="立即重做", question_id="12")
    assert action.question_id == "12"


def test_action_rejects_blank_label() -> None:
    with pytest.raises(ValidationError):
        ReportAction(kind=ReportActionKind.NEW_SCROLL, label="   ")


def test_advice_action_is_optional() -> None:
    """没有可用动作时允许为空 —— 编一个点了没反应的按钮比不给按钮更糟。"""
    assert ReportAdvice.model_validate(_advice()).action is None


# ---------------------------------------------------------------- 事实一致性
def _report(**overrides: object) -> dict:
    payload: dict = {
        "attempt_id": "1",
        "quiz_id": "2",
        "quiz_title": "RAG 入门闯关",
        "finished_at": "2026-09-14T06:20:00+00:00",
        "accuracy": 80,
        "total_count": 5,
        "correct_count": 4,
        "wrong_count": 1,
        "partial_count": 0,
        "avg_seconds_per_question": 1.68,
        "duration_ms": 8400,
        "xp_gained": 180,
        "max_xp": 220,
        "coins_gained": 32,
        "progress": {
            "state": "record",
            "attempt_count": 2,
            "delta_vs_prev": 1,
            "delta_vs_best": 1,
            "best": {"correct": 3, "total": 5},
            "previous": {"correct": 3, "total": 5},
        },
        "mastered_points": ["RAG 基本定义"],
        "weak_points": ["向量检索"],
        "three_line_summary": ["第一句。", "第二句。", "第三句。"],
        "advice": [_advice(), _advice("复习"), _advice("继续")],
    }
    payload.update(overrides)
    return payload


def test_report_accepts_consistent_facts() -> None:
    report = Report.model_validate(_report())
    assert report.accuracy == 80
    assert report.degraded is False
    assert report.progress.state == "record"
    assert report.progress.best is not None and report.progress.best.correct == 3


def test_report_requires_progress() -> None:
    """`progress` 是必填 —— 「这次没算出来」不该是一种状态。

    这一格是结算页与冒险日志页共用的内容，缺了它前端要么渲染一片空白、
    要么自己去推一遍（而「自己推一遍」正是被撤掉的那套做法的起点）。
    """
    payload = _report()
    payload.pop("progress")
    with pytest.raises(ValidationError):
        Report.model_validate(payload)


def test_report_schema_has_no_percentile_fields() -> None:
    """契约里不许再出现任何百分位字段。

    比「响应里没有这个键」多一道保险：`Report` 配的是 `extra="ignore"`，
    所以服务层即使把 `percentile=72` 塞进来，既不报错、响应里也不会出现 ——
    只测响应的话，这种「偷偷留着」的写法能一直活下去。
    """
    assert not [key for key in Report.model_fields if key.startswith("percentile")]


def test_report_rejects_weak_points_when_all_correct() -> None:
    """**全对却报出薄弱点**是最伤信任的一类错误：用户没法判断该信哪个。

    服务层本来就会把它清空（见 `report_service.sanitize`），
    这里这道校验是兜给「服务层忘了清」的那一刻 —— 宁可报错，也不要发一份假报告。
    """
    with pytest.raises(ValidationError):
        Report.model_validate(_report(correct_count=5, wrong_count=0, weak_points=["向量检索"]))


def test_report_rejects_mastered_points_when_all_wrong() -> None:
    with pytest.raises(ValidationError):
        Report.model_validate(
            _report(
                accuracy=0,
                correct_count=0,
                wrong_count=5,
                mastered_points=["RAG 基本定义"],
            )
        )


def test_report_rejects_summary_line_count_other_than_three() -> None:
    with pytest.raises(ValidationError):
        Report.model_validate(_report(three_line_summary=["只有一句。"]))


def test_report_rejects_avg_seconds_with_float_noise() -> None:
    """平均用时写进 `DECIMAL(6,2)`，浮点尾数会让「写进去=读出来」的断言不稳定。"""
    with pytest.raises(ValidationError):
        Report.model_validate(_report(avg_seconds_per_question=1.6800000000001))


def test_report_requires_attempt_and_quiz_id() -> None:
    for field in ("attempt_id", "quiz_id"):
        payload = _report()
        payload.pop(field)
        with pytest.raises(ValidationError):
            Report.model_validate(payload)


# ---------------------------------------------------------------- 入参
def test_generate_request_requires_numeric_attempt_id() -> None:
    assert ReportGenerateRequest(attempt_id="12").force is False
    assert ReportGenerateRequest(attempt_id="12", force=True).force is True
    for bad in ("abc", "0", "-1", "1.5", " 1 2", ""):
        with pytest.raises(ValidationError):
            ReportGenerateRequest(attempt_id=bad)
