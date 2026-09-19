"""报告服务：把「一局挑战」变成一份冒险日志。

## 为什么报告是异步任务

与出题同理（`quiz_service` 的模块说明）：小程序单次请求有 60s 上限，
而一次报告生成要调模型。所以形状与 `/quiz/generate` 完全对齐：

    POST /report/generate   校验归属 + 入队，立刻返回 task_id
    GET  /tasks/{id}        轮询，成功后 `data.report` 是完整报告

前端因此**只写一套轮询逻辑**。任务表也是同一张（`task_type="report"`）。

## 报告由两个来源拼成（本模块最容易写错的地方）

| 字段 | 来源 |
|---|---|
| 正确率 / 答对答错数 / 用时 / XP / 金币 / 百分位 | `attempts` 表的既有值，**原样搬运** |
| 掌握点 / 薄弱点 / 三句话总结 / 复习建议 | `reports` 表（AI 生成或模板兜底） |

搬运统计数字时**不重新计算**，直接读 `attempts` 上的列。理由是这些列是结算
那一刻的权威快照：万一将来评分规则改了，历史报告仍然要显示当时算出来的数字，
用新规则重算会让用户看到「同一局的两个页面数字不一样」。

## 一次读取，两种生命周期

`_snapshot()` 把需要的全部信息在**一个会话内**读成纯数据（dataclass），
之后 ORM 会话关闭也不影响使用。这是刻意的：后台线程里如果抱着 ORM 对象跨会话用，
会在 `session.close()` 之后撞上 `DetachedInstanceError`，而那种报错发生在
「报告已经生成完毕、只剩写回」的最后一刻，最难排查。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ErrorCode, DEFAULT_MESSAGES, resource_not_found
from app.core.logging import get_logger
from app.db.session import session_scope
from app.db.tables import Answer, Attempt, QuizRecord, Report as ReportRow, User
from app.llm import report_chain
from app.llm.report_chain import ReportFacts
from app.models.report import (
    ADVICE_COUNT,
    POINTS_MAX,
    Report,
    ReportAction,
    ReportActionKind,
    ReportAdvice,
    ReportDraft,
    ReportGenerateRequest,
    ReportGenerateResponse,
)
from app.services import quiz_repository, scoring, task_service
from app.services.task_service import TaskRecord, TaskStep
from app.utils.timeutil import as_aware_utc, utcnow

logger = get_logger(__name__)

#: 报告任务在界面上的两步。名称由后端给，前端直接渲染（§7.3 的同一条约定）。
STEP_REVIEW = "review"
STEP_COMPOSE = "compose"

_PROGRESS_REVIEW = 30
_PROGRESS_COMPOSE_DONE = 100

#: 报告的估算耗时（展示用，不参与逻辑判断）
_REPORT_ESTIMATED_SECONDS = 8

#: 后台执行器。与出题链分开：报告不该排在出题后面等（用户是「刚答完立刻看报告」），
#: 也不该把出题的执行槽位占满。
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-gen")

#: 落库用的会话工厂（可替换）。理由同 `quiz_service._open_session`。
_open_session: Callable[[], AbstractContextManager[Session]] = session_scope


def _submit(fn: Callable[[], None]) -> None:
    """把报告生成交给后台线程。测试可替换成同步执行以获得确定性的轮询结果。"""
    _executor.submit(fn)


# -----------------------------------------------------------------------------
# 报告草稿 → 对外契约
# -----------------------------------------------------------------------------
#: 建议卡的三个动作槽位（按优先级）。原型 03 第 3 屏的三张卡各带一个动作。
#:
#: 为什么由服务端挂而不是让模型选：动作是**事实问题**而不是文案问题 ——
#: 有没有错题可重做、错题有没有进复习队列，都是确定性的。
#: 让模型决定「建议重做第 3 题」而第 3 题其实答对了，就是一份假报告。
def build_actions(facts: ReportFacts, *, wrong_question_id: int | None) -> list[ReportAction]:
    """按真实事实排出可用的动作（优先级从高到低）。

    只返回**当前确实成立**的动作：
    - 有答错的题 → 才能「立即重做」
    - 有答错的题 → 才说「已加入复习计划」（错题入队是结算时做的，见 `growth_service`）
    - 「召唤新副本」永远成立
    """
    actions: list[ReportAction] = []
    if wrong_question_id is not None:
        actions.append(
            ReportAction(
                kind=ReportActionKind.RETRY_QUESTION,
                label="立即重做",
                question_id=str(wrong_question_id),
            )
        )
    if facts.wrong_count > 0:
        actions.append(
            ReportAction(kind=ReportActionKind.REVIEW_PLAN, label="已加入复习计划")
        )
    actions.append(ReportAction(kind=ReportActionKind.NEW_SCROLL, label="召唤新副本"))
    return actions


def merge_draft(
    snapshot: "_Snapshot", draft: ReportDraft, actions: list[ReportAction], *, degraded: bool
) -> Report:
    """把「确定性事实 + 叙述内容 + 动作」拼成对外契约。

    动作按序挂到前 N 条建议上，**多出来的建议没有动作**（`action=None`）。
    宁可不给按钮，也不要挂一个点了没反应的按钮 —— 后者会让用户以为是 bug。
    """
    advice = [
        ReportAdvice(
            title=item.title,
            body=item.body,
            action=actions[index] if index < len(actions) else None,
        )
        for index, item in enumerate(draft.advice[:ADVICE_COUNT])
    ]

    return Report(
        attempt_id=str(snapshot.attempt_id),
        quiz_id=str(snapshot.quiz_id),
        quiz_title=snapshot.quiz_title,
        # 必须**带上时区**：库里存的是 naive UTC，若原样序列化出去是
        # `2026-09-14T06:20:00`（无偏移），前端 `new Date(...)` 会当成本地时间，
        # 于是北京时间的用户看到的日期可能差一天 —— 报告页头部就写着这个日期。
        finished_at=as_aware_utc(snapshot.finished_at),
        accuracy=snapshot.accuracy,
        total_count=snapshot.total_count,
        correct_count=snapshot.correct_count,
        wrong_count=snapshot.wrong_count,
        partial_count=snapshot.partial_count,
        duration_ms=snapshot.duration_ms,
        avg_seconds_per_question=snapshot.avg_seconds_per_question,
        xp_gained=snapshot.xp_gained,
        max_xp=snapshot.max_xp,
        coins_gained=snapshot.coins_gained,
        percentile=snapshot.percentile,
        percentile_label=scoring.percentile_label_for(snapshot.percentile),
        mastered_points=list(draft.mastered_points),
        weak_points=list(draft.weak_points),
        three_line_summary=list(draft.three_line_summary),
        advice=advice,
        degraded=degraded,
    )


# -----------------------------------------------------------------------------
# 读库
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class _Snapshot:
    """构建报告所需的全部信息，全部是**纯数据**（见模块说明）。"""

    attempt_id: int
    #: 归属者。`reports.user_id` 是 NOT NULL 外键，写库时必须带上；
    #: 放在快照里而不是让调用方另传一次，是因为它和 attempt_id 一样
    #: 是「读出来的事实」，分开传容易在后台线程里传错人。
    user_id: int
    quiz_id: int
    quiz_title: str
    finished_at: datetime
    accuracy: int
    total_count: int
    correct_count: int
    wrong_count: int
    partial_count: int
    duration_ms: int
    avg_seconds_per_question: float
    xp_gained: int
    max_xp: int
    coins_gained: int
    percentile: int
    #: 喂给模型的三段文本
    quiz_json: str
    answer_records: str
    score_summary: str
    facts: ReportFacts
    #: 第一道答错的题（按题序），供「立即重做」指向它。全对时为 None。
    wrong_question_id: int | None
    #: 已存在的报告行内容（没有则为 None）
    existing: "_ExistingReport | None"


@dataclass(frozen=True)
class _ExistingReport:
    id: int
    status: str
    summary_lines: list[str]
    strong_points: list[str]
    weak_points: list[str]
    suggestions: list[dict]
    model: str


def _fmt_duration(ms: int) -> str:
    """把毫秒说成人话：「3 分 12 秒」。"""
    total_seconds = max(0, ms) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes} 分 {seconds} 秒"
    return f"{seconds} 秒"


def _load_snapshot(session: Session, *, attempt_id: int, user_id: int) -> _Snapshot | None:
    """读出一局的全部信息。

    归属校验在这里做：不是自己的挑战记录返回 `None`（调用方转成 4005），
    与「不存在」完全同形，避免错误码差异泄漏存在性。
    """
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or int(attempt.user_id) != int(user_id):
        return None

    quiz_row = session.get(QuizRecord, int(attempt.quiz_id))
    if quiz_row is None:
        # 外键保证不该发生；真发生了说明数据被绕过约束改过，如实报错
        logger.error("挑战记录 %s 指向的卷轴 %s 不存在", attempt_id, attempt.quiz_id)
        return None

    questions = quiz_repository.load_questions(session, int(attempt.quiz_id))
    answer_rows = session.execute(
        select(Answer).where(Answer.attempt_id == attempt_id)
    ).scalars().all()
    by_question = {int(row.question_id): row for row in answer_rows}

    # ---- 逐题的作答说明文本 + 知识点的掌握 / 薄弱归属 ----
    mastered: list[str] = []
    weak: list[str] = []
    wrong_question_id: int | None = None
    lines: list[str] = []

    for index, question in enumerate(questions, start=1):
        row = by_question.get(int(question.id))
        outcome = (row.outcome if row is not None else "wrong") or "wrong"
        selected = list(row.selected) if row is not None and row.selected else []
        correct = list(question.answer or [])
        point = (question.knowledge_point or "").strip()

        if outcome == "correct":
            if point and point not in mastered:
                mastered.append(point)
        else:
            if point and point not in weak:
                weak.append(point)
            if wrong_question_id is None:
                wrong_question_id = int(question.id)

        label = {"correct": "答对", "partial": "部分正确"}.get(outcome, "答错")
        lines.append(
            f"第 {index} 题（{question.type}）：{question.stem}\n"
            f"  你的选择：{'、'.join(selected) if selected else '（未作答）'}；"
            f"正确答案：{'、'.join(correct)}；判定：{label}；知识点：{point or '（无）'}"
        )

    quiz = quiz_repository.build_quiz(quiz_row, questions)
    facts = ReportFacts(
        total_count=int(attempt.total_count),
        correct_count=int(attempt.correct_count),
        wrong_count=int(attempt.wrong_count),
        accuracy=int(attempt.accuracy),
        xp_gained=int(attempt.xp_gained),
        coins_gained=int(attempt.coins_gained),
        mastered_points=tuple(mastered[:POINTS_MAX]),
        weak_points=tuple(weak[:POINTS_MAX]),
    )

    existing_row = session.execute(
        select(ReportRow).where(ReportRow.attempt_id == attempt_id)
    ).scalars().first()

    return _Snapshot(
        attempt_id=int(attempt.id),
        user_id=int(attempt.user_id),
        quiz_id=int(attempt.quiz_id),
        quiz_title=quiz.title,
        finished_at=attempt.finished_at,
        accuracy=int(attempt.accuracy),
        total_count=int(attempt.total_count),
        correct_count=int(attempt.correct_count),
        wrong_count=int(attempt.wrong_count),
        partial_count=int(attempt.partial_count),
        duration_ms=int(attempt.duration_ms),
        avg_seconds_per_question=float(attempt.avg_seconds_per_question),
        xp_gained=int(attempt.xp_gained),
        max_xp=int(attempt.max_xp),
        coins_gained=int(attempt.coins_gained),
        percentile=int(attempt.percentile),
        quiz_json=json.dumps(quiz.model_dump(mode="json"), ensure_ascii=False),
        answer_records="\n".join(lines),
        score_summary=(
            f"共 {attempt.total_count} 题：答对 {attempt.correct_count} 题，"
            f"部分正确 {attempt.partial_count} 题，答错 {attempt.wrong_count} 题；"
            f"正确率 {attempt.accuracy}%；"
            f"总用时 {_fmt_duration(int(attempt.duration_ms))}，"
            f"平均每题 {float(attempt.avg_seconds_per_question):.2f} 秒；"
            f"获得 {attempt.xp_gained} 点经验值（满分 {attempt.max_xp}）"
            f"与 {attempt.coins_gained} 枚金币。"
        ),
        facts=facts,
        wrong_question_id=wrong_question_id,
        existing=(
            _ExistingReport(
                id=int(existing_row.id),
                status=str(existing_row.status),
                summary_lines=list(existing_row.summary_lines or []),
                strong_points=list(existing_row.strong_points or []),
                weak_points=list(existing_row.weak_points or []),
                suggestions=list(existing_row.suggestions or []),
                model=str(existing_row.model or ""),
            )
            if existing_row is not None
            else None
        ),
    )


def _report_from_existing(snapshot: _Snapshot) -> Report | None:
    """把已存在的、状态为 `ready` 的报告行还原成对外契约。

    存进去的是**叙述部分**，统计数字仍然从 `attempts` 现取 ——
    这样即使将来补算了统计字段，旧报告也能立刻显示正确的数字。
    """
    existing = snapshot.existing
    if existing is None or existing.status != "ready":
        return None

    try:
        draft = ReportDraft.model_validate(
            {
                "mastered_points": existing.strong_points,
                "weak_points": existing.weak_points,
                "three_line_summary": existing.summary_lines,
                "advice": [
                    {"title": item.get("title", ""), "body": item.get("body", "")}
                    for item in existing.suggestions
                ],
            }
        )
    except Exception:  # noqa: BLE001 — 库里存的行坏了就走重新生成，不要卡住用户
        logger.warning("已存在的报告行 %s 结构不合法，将重新生成", existing.id)
        return None

    # 动作**不落库**：它是从事实推出来的，每次读取时重算，避免存一份可能过期的事实
    # （例如错题在之后被复习掉了，库里那句「已加入复习计划」就变成了假话）。
    actions = build_actions(snapshot.facts, wrong_question_id=snapshot.wrong_question_id)
    return merge_draft(snapshot, draft, actions, degraded=existing.model.startswith("template"))


# -----------------------------------------------------------------------------
# 写库
# -----------------------------------------------------------------------------
def persist_report(
    session: Session,
    snapshot: _Snapshot,
    draft: ReportDraft,
    *,
    degraded: bool,
    model: str,
) -> None:
    """写入 / 更新 `reports` 行（1:1 于 attempt，所以是 upsert 而不是 insert）。

    只存**叙述部分**：动作不落库（理由见 `_report_from_existing` 的注释），
    统计数字也不落库（它们属于 `attempts`）。
    """
    suggestions = [{"title": item.title, "body": item.body} for item in draft.advice]

    payload = {
        "user_id": snapshot.user_id,
        "status": "ready",
        "summary_lines": list(draft.three_line_summary),
        "strong_points": list(draft.mastered_points),
        "weak_points": list(draft.weak_points),
        "suggestions": suggestions,
        "model": model,
        "error_code": None,
        "error_message": None,
        # 落库用 naive UTC（与全库一致）；只有**出接口**时才补时区
        "generated_at": utcnow(),
    }

    row = session.execute(
        select(ReportRow).where(ReportRow.attempt_id == snapshot.attempt_id)
    ).scalars().first()
    if row is None:
        row = ReportRow(attempt_id=snapshot.attempt_id, **payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    session.flush()
    logger.info("报告已落库：attempt=%s degraded=%s model=%s", snapshot.attempt_id, degraded, model)


def mark_report_failed(
    session: Session, *, attempt_id: int, user_id: int, code: int, message: str
) -> None:
    """把报告行标记为失败。

    原型 03 第 6 屏「报告生成失败 · 保留答题数据」靠的就是这里 ——
    报告失败**不影响** `attempts` / `answers`，用户回来点「重新生成报告」即可。
    """
    row = session.execute(
        select(ReportRow).where(ReportRow.attempt_id == attempt_id)
    ).scalars().first()
    if row is None:
        row = ReportRow(attempt_id=attempt_id, user_id=user_id, status="failed")
        session.add(row)
    row.status = "failed"
    row.error_code = int(code)
    row.error_message = message[:255]
    session.flush()




# -----------------------------------------------------------------------------
# 后台生成
# -----------------------------------------------------------------------------
def _advance(
    task_id: str, key: str, *, status: str, detail: str | None = None, progress: int | None = None
) -> None:
    """推进某一步的状态与整体进度。已进入终态的任务直接忽略（用户的选择优先）。"""
    record = task_service.get_task_or_none(task_id)
    if record is None or task_service.is_finished(record.status):
        return

    steps: list[TaskStep] = []
    for step in record.steps:
        if step.key == key:
            changes: dict[str, object] = {"status": status}
            if detail is not None:
                changes["detail"] = detail
            steps.append(step.model_copy(update=changes))
        else:
            steps.append(step)

    fields: dict[str, object] = {"steps": steps}
    if progress is not None:
        fields["progress"] = progress
    task_service.update_task(task_id, **fields)


def _finish_failed(task_id: str, code: int, message: str) -> None:
    record = task_service.get_task_or_none(task_id)
    if record is None or record.status == "cancelled":
        return

    steps = [
        step.model_copy(update={"status": "failed"})
        if step.status in {"running", "pending"}
        else step
        for step in record.steps
    ]
    task_service.update_task(
        task_id,
        status="failed",
        steps=steps,
        error=task_service.TaskError(code=code, message=message),
    )


def _complete_reuse(task_id: str, *, total_count: int, report: Report) -> None:
    """复用已有报告时的收尾：把两步进度推到完成，再置任务成功。

    顺序**不能反**：`_advance` 对已进入终态的任务直接返回（用户的选择优先），
    所以先置 `succeeded` 会让这两步永远停在 `pending` —— 表现为「任务说成功、
    步骤说待处理」，前端的三步进度卡会照着错的状态渲染。

    抽成一个函数是因为「复用」有**两个入口**：同步的 `submit_report_request`
    （库里已有报告，直接返回）与后台的 `run_report_generation`（任务已排队后
    才发现可以复用）。两处各写一遍时，其中一处漏掉步骤推进就是这样发生的 ——
    实测踩过：抽验脚本报「复用返回的报告与原报告逐字段相同」通过，但
    `steps[1]` 仍写着「将结合 5 道题的作答情况」。
    """
    _advance(
        task_id,
        STEP_REVIEW,
        status="done",
        detail=f"共 {total_count} 道题",
        progress=_PROGRESS_REVIEW,
    )
    _advance(
        task_id,
        STEP_COMPOSE,
        status="done",
        detail="已读取此前的复盘报告",
        progress=_PROGRESS_COMPOSE_DONE,
    )
    task_service.update_task(task_id, status="succeeded", report=report.model_dump(mode="json"))


def run_report_generation(
    task_id: str,
    *,
    user_id: int,
    attempt_id: int,
    force: bool = False,
    settings: Settings | None = None,
    generate: Callable[..., tuple[ReportDraft, bool]] | None = None,
) -> None:
    """后台生成报告。**这个函数不抛异常** —— 失败一律落到任务与 `reports` 行上。

    Args:
        force: 用户显式要求重写（`ReportGenerateRequest.force`）。
            为 `True` 时**即使库里已有可用报告也要重新调模型**。
            必须由调用方透传进来：这里再判一次「有报告就复用」会把
            `force` 悄悄吃掉，表现为「用户点了重新生成，看到的还是上一份」。
        generate: 注入报告链（测试用）；不传则用 `report_chain.generate_report_draft`。
            用 module 属性现取，这样测试 monkeypatch 才生效。
    """
    s = settings or get_settings()
    generate_report = generate or report_chain.generate_report_draft

    record = task_service.get_task_or_none(task_id)
    if record is None or task_service.is_finished(record.status):
        logger.info("报告任务 %s 已结束或不存在，跳过执行", task_id)
        return

    try:
        task_service.update_task(task_id, status="running", progress=5)
        _advance(task_id, STEP_REVIEW, status="running", detail="正在回看这次作答", progress=10)

        with _open_session() as session:
            snapshot = _load_snapshot(session, attempt_id=attempt_id, user_id=user_id)
            if snapshot is None:
                raise resource_not_found("这次挑战记录不存在或无权访问")

            # 已有一份可用报告时直接复用，不再调模型 —— 见 submit_report_request。
            # `force` 时跳过复用：用户已经明确说「重写一份」了。
            reuse = None if force else _report_from_existing(snapshot)

            if reuse is not None:
                _complete_reuse(
                    task_id, total_count=snapshot.total_count, report=reuse
                )
                return

            _advance(
                task_id,
                STEP_REVIEW,
                status="done",
                detail=f"共 {snapshot.total_count} 道题 · 正确率 {snapshot.accuracy}%",
                progress=_PROGRESS_REVIEW,
            )
            _advance(
                task_id,
                STEP_COMPOSE,
                status="running",
                detail="正在组织复盘内容",
                progress=_PROGRESS_REVIEW + 10,
            )

        draft, degraded = generate_report(
            topic=snapshot.quiz_title,
            quiz_json=snapshot.quiz_json,
            answer_records=snapshot.answer_records,
            score_summary=snapshot.score_summary,
            facts=snapshot.facts,
            settings=s,
        )

        record = task_service.get_task_or_none(task_id)
        if record is None or record.status == "cancelled":
            logger.info("报告任务 %s 已被取消，丢弃生成结果", task_id)
            return

        model = "template" if degraded else s.deepseek_model
        with _open_session() as session:
            persist_report(session, snapshot, draft, degraded=degraded, model=model)

        actions = build_actions(snapshot.facts, wrong_question_id=snapshot.wrong_question_id)
        report = merge_draft(snapshot, draft, actions, degraded=degraded)

        _advance(
            task_id,
            STEP_COMPOSE,
            status="done",
            detail="复盘报告已生成",
            progress=_PROGRESS_COMPOSE_DONE,
        )
        task_service.update_task(task_id, status="succeeded", report=report.model_dump(mode="json"))

    except AppError as exc:
        logger.warning("报告任务 %s 失败：code=%s detail=%s", task_id, exc.code, exc.detail)
        try:
            with _open_session() as session:
                mark_report_failed(
                    session,
                    attempt_id=attempt_id,
                    user_id=user_id,
                    code=int(exc.code),
                    message=exc.message,
                )
        except Exception:  # noqa: BLE001 — 连失败都记不下来时，仍然要把任务标成失败
            logger.exception("报告任务 %s：失败状态写库也失败了", task_id)
        _finish_failed(task_id, exc.code, exc.message)

    except Exception as exc:  # noqa: BLE001
        # 后台线程里的意外异常必须被兜住，否则任务永远停在 running，前端一直转圈
        logger.exception("报告任务 %s 出现未预期异常", task_id)
        try:
            with _open_session() as session:
                mark_report_failed(
                    session,
                    attempt_id=attempt_id,
                    user_id=user_id,
                    code=int(ErrorCode.INTERNAL_ERROR),
                    message=DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
                )
        except Exception:  # noqa: BLE001
            logger.exception("报告任务 %s：失败状态写库也失败了", task_id)
        _finish_failed(
            task_id,
            int(ErrorCode.INTERNAL_ERROR),
            DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
        )
        logger.debug("未预期异常详情：%r", exc)


# -----------------------------------------------------------------------------
# 提交入口
# -----------------------------------------------------------------------------
def _initial_steps(total_count: int) -> list[TaskStep]:
    return [
        TaskStep(key=STEP_REVIEW, name="回看这次作答", status="pending", detail="准备中"),
        TaskStep(
            key=STEP_COMPOSE,
            name="撰写复盘报告",
            status="pending",
            detail=f"将结合 {total_count} 道题的作答情况",
        ),
    ]


def submit_report_request(
    session: Session,
    user: User,
    payload: ReportGenerateRequest,
    *,
    settings: Settings | None = None,
) -> ReportGenerateResponse:
    """校验归属并创建报告任务（同步返回，不等生成）。

    Raises:
        AppError: 4005 —— 挑战记录不存在，或不属于当前用户（两者同形）。
    """
    s = settings or get_settings()
    user_id = int(user.id)
    attempt_id = int(payload.attempt_id)

    snapshot = _load_snapshot(session, attempt_id=attempt_id, user_id=user_id)
    if snapshot is None:
        raise resource_not_found("这次挑战记录不存在或无权访问")

    reuse = None if payload.force else _report_from_existing(snapshot)

    record = task_service.create_task(
        "report", user_id=user_id, steps=_initial_steps(snapshot.total_count)
    )

    if reuse is not None:
        # 已经有可用报告：任务直接以成功状态返回，不排队、不调模型。
        # 这样前端只有一条路径（建任务 → 轮询 → 读 report），
        # 而「重复点一下」不会多花一次模型调用，也不会重写库里的报告。
        _complete_reuse(record.task_id, total_count=snapshot.total_count, report=reuse)
    else:
        _submit(
            lambda: run_report_generation(
                record.task_id,
                user_id=user_id,
                attempt_id=attempt_id,
                force=payload.force,
                settings=s,
            )
        )

    return ReportGenerateResponse(
        task_id=record.task_id,
        status="succeeded" if reuse is not None else record.status,
        poll_interval_ms=s.quiz_task_poll_interval_ms,
        estimated_seconds=0 if reuse is not None else _REPORT_ESTIMATED_SECONDS,
    )


def get_task_for_polling(task_id: str, user_id: int) -> TaskRecord:
    """轮询入口的语义封装：**带归属校验**（不是自己的任务按不存在处理）。"""
    return task_service.get_task_for_user(task_id, user_id)


def shutdown_executor(wait: bool = False) -> None:
    """关闭后台执行器（进程退出或测试收尾时调用）。"""
    _executor.shutdown(wait=wait)
