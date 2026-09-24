#!/usr/bin/env python
"""Phase C · 冒险日志报告链端到端抽验：真 HTTP + 真库 + 真模型。

用法（在 backend/ 目录下；需要后端已在 8000 端口运行）：

    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000      # 另开一个终端
    .venv/Scripts/python.exe scripts/verify_report_chain.py

## 它补的是 `verify_user_chain.py` 之后的半段

`verify_user_chain.py` 走到「交卷结算 + 档案增长」为止。报告链是它的**下游**：
结算把权威数字写进 `attempts`，报告再把这些数字搬出来讲成人话。
所以这里从「故意错一题的一局」开始，一路验到报告接口的返回体。

## 它验的是什么（pytest 验不到的部分）

pytest 里 `_submit` 被换成同步执行、模型被 mock —— 那是**进程内、依赖被替换**的条件。
这个脚本要回答的是另一个问题：把前端真会发的请求真发一遍，整条链是否还成立。具体包括：

1. 报告接口的鉴权与参数校验（4010 / 4000 / 4005），以及**越权与不存在同形**
2. `POST /report/generate` → 轮询 `GET /tasks/{id}` → `data.report` 的完整契约
3. **报告统计与结算逐位相同** —— 这是报告链最容易写错也最伤用户的一条：
   同一局在结算页写 80%、报告页写 85%，用户没法判断该信哪个
4. 幂等：不带 `force` 再请求一次**不重新调模型**，且任务立刻以成功状态返回
5. `force=true` 时确实重新生成（换出一个新任务，而不是把旧报告端回来）
6. 动作（`retry_question` / `review_plan` / `new_scroll`）**按真实事实**挂上，
   且 `retry_question` 指向的题目确实在本次卷轴里
7. `finished_at` **带 UTC 偏移** —— 不带的话前端 `new Date(...)` 会当成本地时间，
   北京时间的用户看到的日期可能差一天，而报告页头部就写着这个日期
8. 掌握 / 薄弱点与「这次到底答没答对」不自相矛盾

## 为什么断言是「自适应」的，而不是写死数字

模型出的题每次都不一样（题型分布、知识点、是否有多选题都不确定），
所以脚本先按**实际作答结果**推导出应然，再与报告比对 ——
写死 `weak_points == ["RAG"]` 的断言只能跑一次，第二次就红，最后一定会被忽略。

`degraded=True`（模型全失败 → 模板兜底）被视为**合法结果**而不是失败：
降级是按设计存在的（见 `app/llm/report_chain.py` 模块说明），
但脚本会把它打印出来 —— 兜底率高到一定程度就该有人去查模型了。

## 它会往业务库写什么

一个调试用户 + 一份卷轴 + 一两局挑战记录 + 一份报告，全部挂在
`device_id = "verify-report-chain"` 这个身份下，可随时按这个标识清理。

退出码：任一断言失败返回 1。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

# 允许直接以脚本方式运行（把 backend/ 加入 sys.path，与另两个抽验脚本一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"

#: 实际使用的根地址，由 `--base` 覆盖
BASE = DEFAULT_BASE

#: 设备标识固定，重复运行复用同一个调试用户
DEVICE_A = "verify-report-chain"
DEVICE_B = "verify-report-chain-b"

POLL_INTERVAL_S = 1.5
POLL_DEADLINE_S = 120.0

#: （2026-09-23）此处原有 `PERCENTILE_BANDS` + `expected_percentile_label`，
#: 用来抽验「档位文字与百分位数值自洽」。百分位整条链路已删除 —— 它与
#: 「社团」这个并不存在的实体绑定，见 `app/services/progress_service.py` 的模块说明。
#: 这一格现在讲「与自己的历史比」，因此也不需要一份独立重写的档位表。


# -----------------------------------------------------------------------------
# 极简 HTTP 客户端（stdlib，不引第三方依赖）
# -----------------------------------------------------------------------------
def call(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict]:
    """发一次请求，返回 `(http_status, 解包后的响应体)`。

    `urllib` 对 4xx/5xx 抛 `HTTPError`，但**错误响应体里同样有我们的信封**，
    所以要读出来再返回 —— 这里的错误码是断言的对象，不是异常。
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"_raw": raw}
    except urllib.error.URLError as exc:
        raise SystemExit(f"[x] 连不上后端 {BASE}：{exc}. 先在 backend/ 下启动 uvicorn。") from exc


# -----------------------------------------------------------------------------
# 断言收集
# -----------------------------------------------------------------------------
PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  \u2705 {name}")
    else:
        FAILED.append(name)
        print(f"  \u274c {name}{('  → ' + detail) if detail else ''}")
    return condition


def section(title: str) -> None:
    print()
    print("-" * 78)
    print(title)
    print("-" * 78)


# -----------------------------------------------------------------------------
# 步骤
# -----------------------------------------------------------------------------
def login(device_id: str, label: str) -> tuple[str, dict]:
    status, body = call("POST", "/auth/dev", {"device_id": device_id})
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] {label} 登录失败：HTTP {status} {body}")
    data = body["data"]
    print(f"  {label}: user_id={data['user']['id']} 昵称={data['user']['nickname']!r} "
          f"Lv.{data['user']['level']} {data['user']['level_title']}")
    return data["token"], data["user"]


def generate_quiz(token: str, topic: str) -> dict:
    """带令牌建出题任务并轮询到终态，返回题库。"""
    status, body = call("POST", "/quiz/generate", {
        "user_input": topic,
        "question_count": 5,
        "difficulty": "mixed",
    }, token=token)
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] 创建出题任务失败：HTTP {status} {body}")

    task_id = body["data"]["task_id"]
    deadline = time.monotonic() + POLL_DEADLINE_S
    while time.monotonic() < deadline:
        _, task_body = call("GET", f"/tasks/{task_id}", token=token)
        task = task_body.get("data") or {}
        if task.get("status") == "succeeded":
            return task["quiz"]
        if task.get("status") in ("failed", "cancelled"):
            raise SystemExit(f"[x] 出题任务终态异常：{task}")
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit("[x] 轮询超时，出题任务未在预算内进入终态")


def option_keys(question: dict) -> list[str]:
    """取出题目的选项键（`A`/`B`/`C`/… 或判断题的 `T`/`F`）。

    ⚠️ 题库契约里 `options` 是 `[{key, text}]` **对象数组**，不是字符串数组
    （见 `app/models/quiz.py` 的 `Option`）。作答提交的是 `key`，
    且 `selected` 元素有 8 字符上限 —— 把整个对象 `str()` 进去会以
    「`answers.0.selected.0: String should have at most 8 characters`」
    的形式在**结算接口**报错，与出题链毫无关系，排查时容易被带偏。
    """
    return [str(item["key"]) for item in question.get("options", [])]


def wrong_selection(question: dict) -> list[str] | None:
    """给出一道**确定性答错**的选择；构造不出时返回 None。

    多选的特殊之处：选中一个「不在正确答案里」的选项会让判定为 `wrong`（含错选 → 0 分）。
    只有当所有选项都是正确答案（正确答案 = 全选）时才构造不出 —— 且题库契约已经
    禁止了多选题「正确答案 = 全选」，所以实际只有单选取不出反例时才需要跳过。
    """
    correct = {str(item) for item in question.get("answer", [])}
    for key in option_keys(question):
        if key not in correct:
            return [key]
    return None


def build_answers(quiz: dict) -> tuple[list[dict], str | None]:
    """构造一份「故意错一题、其余全对」的作答。

    Returns:
        `(answers, wrong_question_id)`；没能构造出错题时 `wrong_question_id` 为 None，
        调用方需要据此调整断言（而不是让脚本含糊地「通过」）。
    """
    questions = quiz["questions"]
    wrong_id: str | None = None
    answers: list[dict] = []

    for question in questions:
        selected = [str(item) for item in question["answer"]]
        if wrong_id is None:
            candidate = wrong_selection(question)
            if candidate is not None:
                selected = candidate
                wrong_id = str(question["id"])
        answers.append({
            "question_id": str(question["id"]),
            "selected": selected,
            "time_spent_ms": 4000,
        })
    return answers, wrong_id


def submit_attempt(token: str, quiz: dict, answers: list[dict]) -> dict:
    now_ms = int(time.time() * 1000)
    status, body = call("POST", "/attempts", {
        "quiz_id": str(quiz["quiz_id"]),
        "client_token": str(uuid.uuid4()),
        "started_at": now_ms - 120_000,
        "finished_at": now_ms,
        "answers": answers,
    }, token=token)
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] 交卷失败：HTTP {status} {body}")
    return body["data"]


def poll_report(token: str, task_id: str) -> dict:
    """轮询报告任务到终态，返回 `data`。"""
    deadline = time.monotonic() + POLL_DEADLINE_S
    while time.monotonic() < deadline:
        _, body = call("GET", f"/tasks/{task_id}", token=token)
        task = body.get("data") or {}
        if task.get("status") == "succeeded":
            return task
        if task.get("status") in ("failed", "cancelled"):
            raise SystemExit(f"[x] 报告任务终态异常：{task}")
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit("[x] 轮询超时，报告任务未在预算内进入终态")


def main() -> int:
    global BASE

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"接口根地址，默认 {DEFAULT_BASE}")
    parser.add_argument("--topic", default="我想学习什么是 RAG，以及它和传统搜索有什么区别")
    parser.add_argument("--skip-generate", action="store_true",
                        help="跳过真实模型调用（不消耗额度），只验鉴权、参数校验与越权")
    args = parser.parse_args()

    BASE = args.base.rstrip("/")

    print("=" * 78)
    print("Phase C · 冒险日志报告链端到端抽验")
    print("=" * 78)
    print(f"  接口根地址 : {BASE}")
    print(f"  调试身份   : {DEVICE_A} / {DEVICE_B}")
    print("=" * 78)

    # ---------- 1. 未登录 ----------
    section("1. 未登录一律 4010")
    status, body = call("POST", "/report/generate", {"attempt_id": "1"})
    check("POST /report/generate 无令牌 → 401 / 4010",
          status == 401 and body.get("code") == 4010,
          f"实际 HTTP {status} code={body.get('code')}")

    # ---------- 2. 登录 ----------
    section("2. 静默登录")
    token_a, user_a = login(DEVICE_A, "用户 A")
    token_b, _user_b = login(DEVICE_B, "用户 B")

    # ---------- 3. 参数校验（不依赖真实作答） ----------
    section("3. 参数校验：形状非法 4000，不存在与越权同为 4005")
    status, body = call("POST", "/report/generate", {"attempt_id": "attempt_1"}, token=token_a)
    check("attempt_id 非数字 → 4000", body.get("code") == 4000, f"code={body.get('code')}")

    status, body = call("POST", "/report/generate", {"attempt_id": "999999999"}, token=token_a)
    check("attempt_id 不存在 → 404 / 4005",
          status == 404 and body.get("code") == 4005,
          f"HTTP {status} code={body.get('code')}")

    if args.skip_generate:
        print()
        print("[i] --skip-generate：跳过出题 / 结算 / 报告生成链路")
        return report()

    # ---------- 4. 出题 ----------
    section("4. 带令牌出题（真实模型）")
    quiz = generate_quiz(token_a, args.topic)
    questions = quiz["questions"]
    print(f"  卷轴 id={quiz['quiz_id']} 标题={quiz['title']!r} 题数={len(questions)}")
    check("题目 id 全为数据库主键（数字）",
          all(str(q["id"]).isdigit() for q in questions),
          str([q["id"] for q in questions]))
    check("题目都带了知识点（报告的知识点标签靠它推导）",
          all((q.get("knowledge_point") or "").strip() for q in questions))

    # ---------- 5. 交一份「故意错一题」的卷 ----------
    section("5. 交卷结算（故意错一题，供报告链使用）")
    answers, wrong_question_id = build_answers(quiz)
    check("构造出了一道会答错的题", wrong_question_id is not None,
          "本次题库所有题都无法构造确定性错答（正确答案 = 全选）")
    print(f"  故意答错的题：question_id={wrong_question_id}")

    settled = submit_attempt(token_a, quiz, answers)
    summary = settled["summary"]
    attempt_id = str(settled["attempt_id"])
    print(f"  attempt_id={attempt_id} · 答对 {summary['correct_count']}/{summary['total_count']} · "
          f"部分正确 {summary['partial_count']} · 答错 {summary['wrong_count']} · "
          f"正确率 {summary['accuracy']}% · XP {summary['xp_gained']}/{summary['max_xp']} · "
          f"金币 {summary['coins_gained']} · 进度 {summary['progress']['state']} · "
          f"平均每题 {summary['avg_seconds_per_question']}s")
    check("确实产生了一道非全对的题",
          summary["wrong_count"] + summary["partial_count"] >= 1,
          f"wrong={summary['wrong_count']} partial={summary['partial_count']}")

    # ---------- 6. 越权（用真实存在的 attempt） ----------
    section("6. 越权隔离：用户 B 拿不到用户 A 的报告")
    status, body = call("POST", "/report/generate", {"attempt_id": attempt_id}, token=token_b)
    check("B 为 A 的挑战记录生成报告 → 404 / 4005（与不存在同形）",
          status == 404 and body.get("code") == 4005,
          f"HTTP {status} code={body.get('code')}")

    # ---------- 7. 生成报告 ----------
    section("7. 生成报告（真实模型，轮询取回）")
    status, body = call("POST", "/report/generate", {"attempt_id": attempt_id}, token=token_a)
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] 创建报告任务失败：HTTP {status} {body}")
    first = body["data"]
    print(f"  task_id={first['task_id']} status={first['status']} "
          f"轮询间隔={first['poll_interval_ms']}ms 预估={first['estimated_seconds']}s")
    check("返回可轮询的任务信封（形状与出题链一致）",
          bool(first.get("task_id")) and first["status"] in ("pending", "running", "succeeded")
          and first["poll_interval_ms"] > 0
          and first["estimated_seconds"] > 0,
          str(first)[:140])
    check("首次生成不应直接是复用（库里还没有报告）", first["status"] != "succeeded",
          f"status={first['status']}")

    task = poll_report(token_a, first["task_id"])
    report_doc = task.get("report")
    if not isinstance(report_doc, dict):
        raise SystemExit(f"[x] 任务成功但 data.report 缺失：{str(task)[:200]}")

    print(f"  报告 degraded={report_doc['degraded']} 进度={report_doc['progress']['state']}")
    print(f"  掌握点={report_doc['mastered_points']}")
    print(f"  薄弱点={report_doc['weak_points']}")
    for index, line in enumerate(report_doc["three_line_summary"], start=1):
        print(f"  总结{index}. {line}")
    for index, item in enumerate(report_doc["advice"], start=1):
        action = item.get("action")
        print(f"  建议{index}. [{item['title']}] {item['body']}  → {action}")

    # ---------- 8. 契约完整性 ----------
    section("8. 报告契约完整性")
    check("任务带完整的两步进度且名称来自后端",
          len(task.get("steps") or []) == 2
          and all(step.get("status") == "done" for step in task["steps"]),
          str(task.get("steps"))[:160])
    check("attempt_id 指回本次挑战", report_doc.get("attempt_id") == attempt_id,
          f"{report_doc.get('attempt_id')} vs {attempt_id}")
    check("quiz_id / quiz_title 与卷轴一致",
          str(report_doc.get("quiz_id")) == str(quiz["quiz_id"])
          and report_doc.get("quiz_title") == quiz["title"],
          f"{report_doc.get('quiz_id')} / {report_doc.get('quiz_title')!r}")
    check("三句话总结恰好 3 句且非空",
          len(report_doc["three_line_summary"]) == 3
          and all(str(line).strip() for line in report_doc["three_line_summary"]))
    check("复习建议恰好 3 条且标题 / 正文非空",
          len(report_doc["advice"]) == 3
          and all(item["title"].strip() and item["body"].strip()
                  for item in report_doc["advice"]))
    check("建议文案不超长（移动端不塌版）",
          all(len(item["title"]) <= 24 and len(item["body"]) <= 120
              for item in report_doc["advice"]))
    check("degraded 是布尔值（降级可观测）",
          isinstance(report_doc.get("degraded"), bool))

    # ---------- 9. 统计与结算逐位相同 ----------
    section("9. 统计数字与结算页逐位相同（报告链最关键的一条）")
    for field in ("accuracy", "correct_count", "wrong_count", "partial_count", "total_count",
                  "xp_gained", "max_xp", "coins_gained", "duration_ms"):
        check(f"{field} 与结算一致",
              report_doc.get(field) == summary[field],
              f"报告 {report_doc.get(field)} vs 结算 {summary[field]}")
    check("avg_seconds_per_question 与结算一致（含两位小数量化）",
          report_doc["avg_seconds_per_question"] == summary["avg_seconds_per_question"],
          f"{report_doc['avg_seconds_per_question']} vs {summary['avg_seconds_per_question']}")
    check("进度（与自己比）在报告与结算里逐位相同",
          report_doc["progress"] == summary["progress"],
          f"报告 {report_doc['progress']} vs 结算 {summary['progress']}")
    check("报告里没有任何 percentile* 字段",
          not [key for key in report_doc if key.startswith("percentile")],
          str(sorted(report_doc)))
    check("答对 + 答错 + 部分正确 = 题量",
          report_doc["correct_count"] + report_doc["wrong_count"] + report_doc["partial_count"]
          == report_doc["total_count"],
          f"{report_doc['correct_count']}+{report_doc['wrong_count']}+"
          f"{report_doc['partial_count']} vs {report_doc['total_count']}")

    # ---------- 10. finished_at 时区 ----------
    section("10. finished_at 必须带 UTC 偏移（否则前端日期会差一天）")
    raw_finished = str(report_doc["finished_at"])
    check("序列化后带时区偏移（Z 或 ±hh:mm）",
          raw_finished.endswith("Z") or "+" in raw_finished[10:] or "-" in raw_finished[10:],
          raw_finished)
    try:
        parsed = datetime.fromisoformat(raw_finished.replace("Z", "+00:00"))
        check("能被 ISO 解析且有时区信息", parsed.tzinfo is not None, raw_finished)
    except ValueError as exc:  # pragma: no cover — 真出现就是契约坏了
        check("能被 ISO 解析且有时区信息", False, f"{raw_finished} → {exc}")

    # ---------- 11. 动作按真实事实挂载 ----------
    section("11. 复习建议上的动作按真实事实挂载")
    kinds = [item["action"]["kind"] if item.get("action") else None
             for item in report_doc["advice"]]
    print(f"  动作序列：{kinds}")
    check("最后一条建议总是「召唤新副本」", kinds[-1] == "new_scroll", str(kinds))
    if summary["wrong_count"] + summary["partial_count"] > 0:
        check("有非全对的题 → 第一条是「立即重做」",
              kinds[0] == "retry_question", str(kinds))
        retry_action = report_doc["advice"][0]["action"]
        quiz_ids = {str(q["id"]) for q in questions}
        check("「立即重做」指向的是本次卷轴里真实存在的题目",
              retry_action.get("question_id") in quiz_ids,
              f"question_id={retry_action.get('question_id')} 卷轴={sorted(quiz_ids)}")
        check("「立即重做」的题目确实是答错的那一道",
              wrong_question_id is not None
              and retry_action.get("question_id") == wrong_question_id,
              f"{retry_action.get('question_id')} vs {wrong_question_id}")
    else:  # pragma: no cover — 上面的构造保证了不会走到这里
        check("没有非全对的题 → 不应出现「立即重做」",
              "retry_question" not in kinds, str(kinds))
    if summary["wrong_count"] > 0:
        check("有答错的题 → 出现「已加入复习计划」胶囊", "review_plan" in kinds, str(kinds))
    check("动作都是闭集内的值",
          all(kind in (None, "retry_question", "review_plan", "new_scroll") for kind in kinds),
          str(kinds))

    # ---------- 12. 掌握 / 薄弱点不自相矛盾 ----------
    section("12. 知识点与本次作答不自相矛盾")
    if report_doc["degraded"]:
        print("  [i] 本次走的是模板兜底，知识点断言按兜底语义放宽")
        check("模板兜底时降级标记为 True（可观测）", report_doc["degraded"] is True)
    check("全对时不得出现薄弱点",
          not (report_doc["accuracy"] == 100 and report_doc["weak_points"]))
    check("没有答错的题时不得出现薄弱点",
          not (report_doc["wrong_count"] == 0 and report_doc["weak_points"]))
    check("没有答对的题时不得出现掌握点",
          not (report_doc["correct_count"] == 0 and report_doc["mastered_points"]))
    check("知识点条数不超过题量（每个题最多 1 个知识点）",
          len(report_doc["mastered_points"]) <= len(questions)
          and len(report_doc["weak_points"]) <= len(questions),
          f"掌握 {len(report_doc['mastered_points'])} 薄弱 {len(report_doc['weak_points'])} "
          f"vs 题量 {len(questions)}")

    # ---------- 13. 幂等 ----------
    section("13. 幂等：不带 force 再请求一次不重新生成")
    status, body = call("POST", "/report/generate", {"attempt_id": attempt_id}, token=token_a)
    second = body["data"]
    check("复用路径直接以成功状态返回（不排模型队列）",
          second["status"] == "succeeded" and second["estimated_seconds"] == 0,
          str(second)[:140])
    check("仍然返回可轮询的 task_id", bool(second.get("task_id")))

    reused_task = poll_report(token_a, second["task_id"])
    reused = reused_task["report"]
    check("复用返回的报告与原报告逐字段相同",
          reused == report_doc,
          "复用的报告与首次不同，说明复用路径重新生成了")
    check("复用走的是「已读取此前的复盘报告」这一步",
          str(reused_task["steps"][-1].get("detail", "")).strip() == "已读取此前的复盘报告",
          str(reused_task["steps"][-1])[:120])

    # ---------- 14. force 重新生成 ----------
    section("14. force=true 时确实重新生成")
    status, body = call("POST", "/report/generate",
                       {"attempt_id": attempt_id, "force": True}, token=token_a)
    forced = body["data"]
    check("force 时重新排队（不再直接复用）",
          forced["status"] in ("pending", "running"),
          f"status={forced['status']}")
    forced_task = poll_report(token_a, forced["task_id"])
    forced_report = forced_task["report"]
    check("重新生成后统计数字仍然与结算逐位相同",
          all(forced_report[field] == summary[field]
              for field in ("accuracy", "correct_count", "wrong_count", "partial_count",
                            "total_count", "xp_gained", "max_xp", "coins_gained",
                            "duration_ms")),
          "force 重算出来的数字与结算不一致")
    check("重新生成后 attempt_id 未漂移",
          forced_report["attempt_id"] == attempt_id, str(forced_report["attempt_id"]))
    check("重新生成后仍是完整契约（3 句 + 3 条建议）",
          len(forced_report["three_line_summary"]) == 3
          and len(forced_report["advice"]) == 3)
    check("重新生成后动作仍按事实挂载",
          [item["action"]["kind"] if item.get("action") else None
           for item in forced_report["advice"]][-1] == "new_scroll")

    # 复用一次，确认第 14 步的产物已落库、再次请求不再调模型
    status, body = call("POST", "/report/generate", {"attempt_id": attempt_id}, token=token_a)
    check("force 生成的结果已落库，随后再次请求命中复用",
          body["data"]["status"] == "succeeded", str(body["data"])[:140])

    return report()


def report() -> int:
    print()
    print("=" * 78)
    print(f"  通过 {PASSED} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print(f"    \u274c {name}")
    print("=" * 78)
    if FAILED:
        print("[x] 端到端抽验未通过")
        return 1
    print("[ok] 端到端抽验全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
