#!/usr/bin/env python
"""Phase B · 用户系统端到端抽验：走**真实 HTTP + 真实库 + 真实模型**跑通整条链。

用法（在 backend/ 目录下；需要后端已在 8000 端口运行）：

    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000      # 另开一个终端
    .venv/Scripts/python.exe scripts/verify_user_chain.py

## 它验的是什么

`pytest` 已经把每条规则单独钉死了，但那是在**进程内、依赖被替换**的条件下。
这个脚本回答的是另一个问题：**把前端会发的请求真发一遍，整条链是否还成立**。

覆盖的链路：

    静默登录 → 带令牌出题（异步任务）→ 轮询取回题库
             → 交卷结算（服务端重判）→ 档案增长 → 幂等重放
             → 越权隔离（另一个用户读不到也交不了）

## 为什么断言「增量」而不是「绝对值」

调试通道按 `device_id` 派生稳定身份，所以同一条命令跑第二遍会**复用同一个用户**，
累计 XP 一直涨。断言 `xp_total == 200` 只在第一次跑时成立 —— 那种脚本第二次跑
就红，最后一定会被忽略。所以这里先读一次基线，再断增量。

## 它会往业务库写什么

一个调试用户 + 一份卷轴 + 一两局挑战记录，全部挂在
`device_id = "verify-user-chain"` 这个身份下，可随时按这个标识清理。
这是「真实链路」的必然代价 —— 与 `verify_quiz_chain.py` 真实调用模型是同一类取舍。

退出码：任一断言失败返回 1。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# 允许直接以脚本方式运行（把 backend/ 加入 sys.path，与另一个抽验脚本一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"

#: 实际使用的根地址，由 `--base` 覆盖
BASE = DEFAULT_BASE

#: 设备标识固定，重复运行复用同一个调试用户
DEVICE_A = "verify-user-chain"
DEVICE_B = "verify-user-chain-b"

POLL_INTERVAL_S = 1.5
POLL_DEADLINE_S = 90.0


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
    所以要把 body 读出来再返回 —— 这里的错误码是断言的对象，不是异常。
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


def generate_quiz(token: str, topic: str) -> tuple[dict, str]:
    """带令牌建出题任务并轮询到终态，返回 `(题库, 任务 id)`。"""
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
            return task["quiz"], task_id
        if task.get("status") in ("failed", "cancelled"):
            raise SystemExit(f"[x] 出题任务终态异常：{task}")
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit("[x] 轮询超时，任务未在预算内进入终态")


def all_correct_answers(quiz: dict) -> list[dict]:
    return [
        {"question_id": str(question["id"]), "selected": list(question["answer"]), "time_spent_ms": 3000}
        for question in quiz["questions"]
    ]


def main() -> int:
    global BASE

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"接口根地址，默认 {DEFAULT_BASE}")
    parser.add_argument("--topic", default="我想学习什么是 RAG，以及它和传统搜索有什么区别")
    parser.add_argument("--skip-generate", action="store_true",
                        help="跳过真实出题（不消耗模型额度），只验鉴权与越权")
    args = parser.parse_args()

    BASE = args.base.rstrip("/")

    print("=" * 78)
    print("Phase B · 用户系统端到端抽验")
    print("=" * 78)
    print(f"  接口根地址 : {BASE}")
    print(f"  调试身份   : {DEVICE_A} / {DEVICE_B}")
    print("=" * 78)

    # ---------- 1. 未登录必须被挡住 ----------
    section("1. 未登录一律 4010（不区分原因）")
    for method, path, payload in [
        ("POST", "/quiz/generate", {"user_input": "未登录的出题请求测试"}),
        ("GET", "/tasks/1", None),
        ("POST", "/attempts", {"quiz_id": "1", "client_token": str(uuid.uuid4()),
                               "started_at": 1, "finished_at": 2, "answers": []}),
        ("GET", "/users/me", None),
    ]:
        status, body = call(method, path, payload)
        check(f"{method} {path} 无令牌 → 401 / 4010",
              status == 401 and body.get("code") == 4010,
              f"实际 HTTP {status} code={body.get('code')}")

    status, body = call("GET", "/users/me", token="not-a-real-token")
    check("伪造令牌 → 401 / 4010", status == 401 and body.get("code") == 4010,
          f"实际 HTTP {status} code={body.get('code')}")

    # ---------- 2. 登录 ----------
    section("2. 静默登录与身份")
    token_a, user_a = login(DEVICE_A, "用户 A")
    token_b, user_b = login(DEVICE_B, "用户 B")
    check("两次登录得到不同用户", user_a["id"] != user_b["id"],
          f"{user_a['id']} vs {user_b['id']}")

    status, body = call("GET", "/users/me", token=token_a)
    me = body["data"]
    check("GET /users/me 返回身份 + 三宫格",
          status == 200 and "user" in me and "stats" in me, str(body)[:120])
    check("响应里不出现 openid / session_key",
          "openid" not in json.dumps(me) and "session_key" not in json.dumps(me))

    if args.skip_generate:
        print()
        print("[i] --skip-generate：跳过出题与结算链路")
        return report()

    # ---------- 3. 出题 ----------
    section("3. 带令牌出题（真实模型）")
    quiz, task_id = generate_quiz(token_a, args.topic)
    quiz_id = str(quiz["quiz_id"])
    print(f"  题库 id={quiz_id} 标题={quiz['title']!r} 题数={len(quiz['questions'])}")
    check("题目 id 已回填成数据库主键（全为数字）",
          all(str(q["id"]).isdigit() for q in quiz["questions"]),
          str([q["id"] for q in quiz["questions"]]))
    check("卷轴 id 是数据库主键（数字）", quiz_id.isdigit(), quiz_id)

    # ---------- 4. 交卷结算 ----------
    section("4. 交卷结算（服务端权威重判）")
    answers = all_correct_answers(quiz)
    expected_xp = sum({"single": 40, "multiple": 60, "judge": 20}[q["type"]] for q in quiz["questions"])

    before = call("GET", "/users/me", token=token_a)[1]["data"]["user"]

    client_token = str(uuid.uuid4())
    now_ms = int(time.time() * 1000)
    submit_body = {
        "quiz_id": quiz_id,
        "client_token": client_token,
        "started_at": now_ms - 120_000,
        "finished_at": now_ms,
        "answers": answers,
    }
    status, body = call("POST", "/attempts", submit_body, token=token_a)
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] 交卷失败：HTTP {status} {body}")
    result = body["data"]
    summary = result["summary"]

    print(f"  XP {summary['xp_gained']}/{summary['max_xp']} · 金币 {summary['coins_gained']} · "
          f"正确率 {summary['accuracy']}% · 百分位 {summary['percentile']}% · "
          f"用时 {summary['duration_ms']}ms")
    check("全对 = 满分", summary["xp_gained"] == summary["max_xp"] == expected_xp,
          f"{summary['xp_gained']} vs {expected_xp}")
    check("正确率 100%", summary["accuracy"] == 100, str(summary["accuracy"]))
    check("金币 = floor(XP × 0.18)", summary["coins_gained"] == math.floor(expected_xp * 0.18),
          f"{summary['coins_gained']} vs {math.floor(expected_xp * 0.18)}")
    check("百分位 = clamp(round(正确率 × 0.9), 5, 95)",
          summary["percentile"] == min(95, max(5, round(100 * 0.9))), str(summary["percentile"]))
    check("结果按题序返回",
          [item["seq"] for item in result["results"]] == list(range(1, len(quiz["questions"]) + 1)),
          str([item["seq"] for item in result["results"]]))
    check("逐题回传答案与解析（供报告页回放）",
          all(item["answer"] and item["explanation"] for item in result["results"]))
    check("本局标记为非重复", result["duplicate"] is False)
    check("错题入队数为 0（全对）", result["wrong_queued_count"] == 0,
          str(result["wrong_queued_count"]))

    # ---------- 5. 档案增长 ----------
    section("5. 档案增长（断增量，可重复运行）")
    after = call("GET", "/users/me", token=token_a)[1]["data"]["user"]
    check("xp_total 增加量 = 本局 XP",
          after["xp_total"] - before["xp_total"] == summary["xp_gained"],
          f"{before['xp_total']} → {after['xp_total']}")
    check("coins 增加量 = 本局金币",
          after["coins"] - before["coins"] == summary["coins_gained"],
          f"{before['coins']} → {after['coins']}")
    check("结算响应里的用户快照与 /users/me 一致",
          result["user"]["xp_total"] == after["xp_total"]
          and result["user"]["coins"] == after["coins"],
          f"{result['user']['xp_total']} vs {after['xp_total']}")
    check("连续天数被推进（≥1）", after["streak_days"] >= 1, str(after["streak_days"]))
    check("等级文案非空", bool(after["level_title"]), repr(after["level_title"]))
    check("等级进度在 0–100", 0 <= after["level_progress"] <= 100, str(after["level_progress"]))

    # ---------- 6. 幂等 ----------
    section("6. 幂等：同一个 client_token 重复提交")
    status, body = call("POST", "/attempts", submit_body, token=token_a)
    replay = body["data"]
    check("返回同一条挑战记录", replay["attempt_id"] == result["attempt_id"],
          f"{replay['attempt_id']} vs {result['attempt_id']}")
    check("汇总与首次逐字段相同", replay["summary"] == summary)
    check("标记为重复提交", replay["duplicate"] is True)

    after_replay = call("GET", "/users/me", token=token_a)[1]["data"]["user"]
    check("重复提交不重复加 XP",
          after_replay["xp_total"] == after["xp_total"],
          f"{after['xp_total']} → {after_replay['xp_total']}")
    check("重复提交不重复加金币", after_replay["coins"] == after["coins"])

    status, body = call("POST", "/attempts", dict(submit_body, client_token=client_token.upper()),
                        token=token_a)
    check("令牌大小写不敏感（大写视为同一个）",
          status == 200 and body["data"]["duplicate"] is True and
          body["data"]["attempt_id"] == result["attempt_id"],
          str(body)[:120])

    # ---------- 7. 重做 ----------
    section("7. 重做同一卷轴")
    status, body = call("POST", f"/attempts/{result['attempt_id']}/retry", token=token_a)
    retry = body.get("data") or {}
    check("重做返回可复用的题库",
          status == 200 and retry.get("quiz", {}).get("quiz_id") == quiz_id,
          str(body)[:140])
    check("重做题库的题目 id 与首次一致",
          [q["id"] for q in retry.get("quiz", {}).get("questions", [])]
          == [q["id"] for q in quiz["questions"]])
    check("重做提示的次序号 = 本局次序号 + 1",
          retry.get("attempt_no") == result["attempt_no"] + 1,
          f"{retry.get('attempt_no')} vs {result['attempt_no'] + 1}")

    # ---------- 8. 越权隔离 ----------
    section("8. 越权隔离：用户 B 拿不到用户 A 的任何东西")
    status, body = call("POST", "/attempts", dict(submit_body, client_token=str(uuid.uuid4())),
                        token=token_b)
    check("B 交 A 的卷轴 → 4005 资源不存在或无权访问",
          status == 404 and body.get("code") == 4005, f"HTTP {status} code={body.get('code')}")

    status, body = call("POST", f"/attempts/{result['attempt_id']}/retry", token=token_b)
    check("B 重做 A 的挑战记录 → 4005",
          status == 404 and body.get("code") == 4005, f"HTTP {status} code={body.get('code')}")

    status, body = call("GET", f"/tasks/{task_id}", token=token_b)
    check("B 读 A 的真实任务 id → 4004（与不存在同形）",
          body.get("code") == 4004, f"code={body.get('code')}")

    status, body = call("GET", "/tasks/task-does-not-exist", token=token_b)
    check("读一个不存在的任务 → 同样是 4004（不可据此探测存在性）",
          body.get("code") == 4004, f"code={body.get('code')}")

    status, body = call("POST", "/tasks/task-does-not-exist/cancel", token=token_b)
    check("取消一个不存在的任务 → 4004", body.get("code") == 4004, f"code={body.get('code')}")

    # ---------- 9. 参数校验 ----------
    section("9. 交卷参数校验（都是 4000）")
    cases = {
        "非数字卷轴 id": dict(submit_body, quiz_id="quiz_test", client_token=str(uuid.uuid4())),
        "结束早于开始": dict(submit_body, client_token=str(uuid.uuid4()),
                          started_at=now_ms, finished_at=now_ms - 1000),
        "秒当毫秒传": dict(submit_body, client_token=str(uuid.uuid4()),
                       started_at=1700000000, finished_at=now_ms),
        "令牌形状不合法": dict(submit_body, client_token="!!!not-a-token!!!"),
        "题号不属于该卷轴": dict(submit_body, client_token=str(uuid.uuid4()),
                           answers=answers + [{"question_id": "999999999", "selected": ["A"]}]),
        "同一题重复作答": dict(submit_body, client_token=str(uuid.uuid4()),
                          answers=answers + [answers[0]]),
    }
    for name, payload in cases.items():
        status, body = call("POST", "/attempts", payload, token=token_a)
        check(f"{name} → 4000", body.get("code") == 4000, f"code={body.get('code')}")

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
