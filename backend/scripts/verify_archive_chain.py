#!/usr/bin/env python
"""Phase D · 成长体系端到端抽验：走**真实 HTTP + 真实库 + 真实模型**验四屏与复习链。

用法（在 backend/ 目录下；需要后端已在 8000 端口运行）：

    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000      # 另开一个终端
    .venv/Scripts/python.exe scripts/verify_archive_chain.py

## 它验的是什么

`pytest` 已经把每个口径单独钉死了，但那是在**进程内、依赖被替换**的条件下。
这个脚本回答的是另一个问题：**把前端会发的请求真发一遍，这几个接口是否还成立**。

覆盖的链路：

    空档案四屏（全是 0 而不是报错）→ 交一局全错的卷轴 → 看板 / 知识树 / 错题本 / 勋章墙
      → 组一局复习关卡 → 复习全对 → **推进的是原错题的阶段**（身份重定向）
      → 越权隔离（另一个用户看不到任何东西）→ 参数校验

## 为什么要「先把错题改成已到期」

错题入队时排的是**明天**（`REVIEW_INTERVALS_DAYS[0] = 1`），所以刚交完一局全错，
`POST /review/start` 一定回 4005 —— 那是正确行为，不是这次要验的东西。

为了把「到期 → 组卷 → 复习 → 阶段推进」这条链跑通，脚本会在组卷之前
**直接把该调试身份的错题排期改成已到期**（只动 `device_id` 归属的那几行）。
这是脚本对**自己造的数据**做的操作，不碰任何别人的记录；也是「真实链路」的代价，
与 `verify_quiz_chain.py` 真实调用模型是同一类取舍。

## 为什么断言「增量」而不是「绝对值」

调试通道按 `device_id` 派生稳定身份，所以同一条命令跑第二遍会**复用同一个用户**，
档案一直涨。断言 `unlocked_count == 1` 只在第一次跑时成立 —— 那种脚本第二次跑就红，
最后一定会被忽略。所以凡是会累积的量都先读基线、再断增量；涉及具体题目时，
一律**只断言本局产生的那几道题**，不假设整个队列里只有它们。

同一原则还要求：**凡是依赖「队列此刻很干净」的断言，前置条件必须自己构造出来**，
不能靠「碰巧刚交完卷」。第 6 节的 4005 就是这类 —— 它要求整个队列一道到期的都没有，
而上一轮跑完会留下到期错题，于是脚本先主动把排期推到远期再断言（见
`mark_wrong_questions_not_due`）。第 7 节的「阶段 +1」同理：阶段达到
`REVIEW_MASTERED_STAGE` 会把错题移出队列，所以断言分成
「推进到期望值」与「已移出」两支，第二轮跑（阶段 1→2）才不会被误判成失败。

## 它会往业务库写什么

两个调试用户 + 两份卷轴 + 两局挑战记录，全部挂在
`device_id = "verify-archive-*"` 这些身份下，可随时按这个前缀清理。

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
from pathlib import Path

# 允许直接以脚本方式运行（把 backend/ 加入 sys.path，与另外两个抽验脚本一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"

#: 实际使用的根地址，由 `--base` 覆盖
BASE = DEFAULT_BASE

#: 两个调试身份。`EMPTY` 只读不写，所以它**永远**是空档案 —— 每次跑都能验空态。
DEVICE_A = "verify-archive-chain"
DEVICE_EMPTY = "verify-archive-empty"

POLL_INTERVAL_S = 1.5
POLL_DEADLINE_S = 90.0

#: 复习关卡单局上限，与 `models.quiz.MAX_QUESTIONS` 一致
MAX_REVIEW_QUESTIONS = 5

#: 构造「零到期」前置条件时把排期推多远（十年，远到不会被误判成「快了」）
NOT_DUE_DAYS = 3650

#: 未登录时全部要 4010 的读接口
GUARDED = (
    "/users/me",
    "/users/me/dashboard",
    "/users/me/knowledge-tree",
    "/users/me/wrong-questions",
    "/users/me/badges",
)


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


def data_of(body: dict) -> dict:
    return body.get("data") or {}


def read(path: str, token: str, *, method: str = "GET", body: dict | None = None) -> dict:
    """读一次并直接取 `data`。

    断言几乎全是「读接口 → 看 data 里的字段」，所以把「解包 `(status, body)`
    再取 data」这三步收成一个函数。逐处手写会漏掉 `[1]`，而那一步的失败
    不是断言红了，是 `'tuple' object has no attribute 'get'` —— 看起来像脚本坏了，
    实际是用错了返回结构。
    """
    return data_of(call(method, path, body, token)[1])


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
    data = data_of(body)
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

    task_id = data_of(body)["task_id"]
    deadline = time.monotonic() + POLL_DEADLINE_S
    while time.monotonic() < deadline:
        _, task_body = call("GET", f"/tasks/{task_id}", token=token)
        task = data_of(task_body)
        if task.get("status") == "succeeded":
            return task["quiz"]
        if task.get("status") in ("failed", "cancelled"):
            raise SystemExit(f"[x] 出题任务终态异常：{task}")
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit("[x] 轮询超时，任务未在预算内进入终态")


def wrong_answers(quiz: dict) -> list[dict]:
    """每题都挑一个**不属于正确答案**的选项。

    多选题要特别注意：选「正确项的真子集」会判成部分正确（30 XP），
    不是答错。所以这里宁可挑错选项 —— 含错选一票否决，判定为 0。
    """
    picked: list[dict] = []
    for question in quiz["questions"]:
        correct = set(question["answer"])
        wrong_keys = [o["key"] for o in question["options"] if o["key"] not in correct]
        if not wrong_keys:  # pragma: no cover - 契约保证 answer ⊆ options 且多选题非全选
            raise SystemExit(f"[x] 题目 {question['id']} 没有可选的错误选项，无法构造全错卷")
        picked.append({
            "question_id": str(question["id"]),
            "selected": [wrong_keys[0]],
            "time_spent_ms": 2000,
        })
    return picked


def correct_answers(quiz: dict) -> list[dict]:
    return [
        {
            "question_id": str(question["id"]),
            "selected": list(question["answer"]),
            "time_spent_ms": 3000,
        }
        for question in quiz["questions"]
    ]


def submit(token: str, quiz: dict, answers: list[dict], *, tag: str) -> dict:
    """交卷并返回结算体。"""
    now_ms = int(time.time() * 1000)
    status, body = call("POST", "/attempts", {
        "quiz_id": str(quiz["quiz_id"]),
        "client_token": str(uuid.uuid4()),
        "started_at": now_ms - 120_000,
        "finished_at": now_ms,
        "answers": answers,
    }, token=token)
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] {tag} 交卷失败：HTTP {status} {body}")
    return data_of(body)


def read_wrong(token: str, *, due_only: bool = False) -> dict:
    suffix = "?due=1" if due_only else ""
    return read(f"/users/me/wrong-questions{suffix}", token=token)


def _set_wrong_review_at(device_id: str, *, days_from_now: int) -> int:
    """把该调试身份名下未攻克的错题排期统一改成「现在 + days_from_now 天」，返回改动行数。

    两个方向都由它承担：

    - `days_from_now=0` → 刚刚到期（第 7 节要走通复习组卷的**成功**路径）；
    - `days_from_now=NOT_DUE_DAYS` → 一道都不到期（第 6 节要走通** 4005** 路径）。

    只按 `user_id`（由 `device_id` 派生的那个调试用户）过滤，不碰任何别人的记录。

    `users` 表里**没有** `device_id` 列：调试通道是把设备标识哈希成 openid 再建档的
    （`auth_service.dev_openid`）。所以这里必须复用那个函数，而不是自己拼一个
    看起来差不多的串 —— 拼错的表现是「查不到用户 → 一行都没改」，
    而脚本会因此报一个与真实原因无关的断言失败。
    """
    from sqlalchemy import select, update  # noqa: PLC0415

    from app.db.session import get_session_factory  # noqa: PLC0415
    from app.db.tables import User, WrongQuestion  # noqa: PLC0415
    from app.services.auth_service import dev_openid  # noqa: PLC0415
    from app.utils.timeutil import add_days, utcnow  # noqa: PLC0415

    target = utcnow() if days_from_now == 0 else add_days(utcnow(), days_from_now)

    with get_session_factory()() as session:
        user_id = session.scalar(select(User.id).where(User.openid == dev_openid(device_id)))
        if user_id is None:
            return 0
        result = session.execute(
            update(WrongQuestion)
            .where(WrongQuestion.user_id == user_id, WrongQuestion.mastered.is_(False))
            .values(next_review_at=target)
        )
        session.commit()
        return int(result.rowcount or 0)


def mark_wrong_questions_due(device_id: str) -> int:
    """把该调试身份名下未攻克的错题排期改成「刚刚已到期」。"""
    return _set_wrong_review_at(device_id, days_from_now=0)


def mark_wrong_questions_not_due(device_id: str) -> int:
    """把所有未攻克的错题推到远期，构造「一道都没到期」的干净前置条件。

    第 6 节的内容是「没有到期的题时不建空局」，而 `POST /review/start` 只有在
    **整个队列**都没有到期题时才回 4005。这个调试身份是**跨轮次累积**的：
    上一轮留下的到期错题会让组卷正常成功 —— 那是正确行为，不是缺陷，
    但会让「刚交完全错 → 4005」这条断言在第二次跑时变成假红。
    所以这里显式把队列清成「零到期」，让断言在每一轮都成立。
    """
    return _set_wrong_review_at(device_id, days_from_now=NOT_DUE_DAYS)


def main() -> int:
    global BASE

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"接口根地址，默认 {DEFAULT_BASE}")
    parser.add_argument("--topic", default="我想学习什么是 RAG，以及它和传统搜索有什么区别")
    parser.add_argument("--skip-generate", action="store_true",
                        help="跳过真实出题（不消耗模型额度），只验鉴权、空档案与参数校验")
    args = parser.parse_args()

    BASE = args.base.rstrip("/")

    print("=" * 78)
    print("Phase D · 成长体系端到端抽验")
    print("=" * 78)
    print(f"  接口根地址 : {BASE}")
    print(f"  调试身份   : {DEVICE_A}（会写数据）/ {DEVICE_EMPTY}（只读）")
    print("=" * 78)

    # ---------- 1. 未登录必须被挡住 ----------
    section("1. 未登录一律 4010（不区分原因）")
    for path in GUARDED:
        status, body = call("GET", path)
        check(f"GET {path} 无令牌 → 401 / 4010",
              status == 401 and body.get("code") == 4010,
              f"实际 HTTP {status} code={body.get('code')}")

    status, body = call("POST", "/review/start")
    check("POST /review/start 无令牌 → 401 / 4010",
          status == 401 and body.get("code") == 4010,
          f"实际 HTTP {status} code={body.get('code')}")

    status, body = call("GET", "/users/me/badges", token="not-a-real-token")
    check("伪造令牌 → 401 / 4010", status == 401 and body.get("code") == 4010,
          f"实际 HTTP {status} code={body.get('code')}")

    # ---------- 2. 空档案：四屏都要能渲染，而不是报错 ----------
    section("2. 空档案四屏（新用户必须看到「全是 0」，不是空页也不是错误）")
    token_empty, _ = login(DEVICE_EMPTY, "空档案用户")

    status, body = call("GET", "/users/me", token=token_empty)
    profile = data_of(body)
    check("GET /users/me 返回身份 + 统计",
          status == 200 and "user" in profile and "stats" in profile, str(body)[:140])
    stats = profile.get("stats", {})
    check("空档案的统计全为 0",
          all(stats.get(key) == 0 for key in
              ("attempt_count", "avg_accuracy", "lit_kp_count", "scroll_count", "badge_unlocked")),
          str(stats))
    check("勋章分母恒为 18", stats.get("badge_total") == 18, str(stats.get("badge_total")))
    check("等级从 Lv.1 起、进度是个合法百分比",
          profile["user"]["level"] == 1 and 0 <= profile["user"]["level_progress"] <= 100,
          str({k: profile["user"][k] for k in ("level", "level_progress")}))
    check("进度条的分子分母都是数（前端直接当宽度用）",
          isinstance(profile["user"]["xp_total"], int)
          and isinstance(profile["user"]["next_level_xp"], int)
          and profile["user"]["next_level_xp"] > 0,
          str({k: profile["user"][k] for k in ("xp_total", "next_level_xp")}))
    check("响应里不出现 openid / session_key",
          "openid" not in json.dumps(profile) and "session_key" not in json.dumps(profile))

    board = read("/users/me/dashboard?range=7d", token=token_empty)
    check("空档案看板：has_data / range_has_data 都是 false",
          board.get("has_data") is False and board.get("range_has_data") is False,
          str({k: board.get(k) for k in ("has_data", "range_has_data")}))
    check("空档案看板：柱子恒为 7 根且全 0",
          len(board.get("bars", [])) == 7 and all(bar["count"] == 0 for bar in board["bars"]),
          str(board.get("bars")))
    check("空档案看板：对比值为 null（不编造 +100%）",
          board.get("week_delta_percent") is None and board.get("accuracy_delta") is None
          and board.get("duration_delta_ms") is None,
          str({k: board.get(k) for k in
               ("week_delta_percent", "accuracy_delta", "duration_delta_ms")}))
    check("空档案看板：领域列表为空", board.get("domains") == [], str(board.get("domains")))
    check("柱下标签是「一二三四五六日」",
          all(bar["label"] in "一二三四五六日" for bar in board["bars"]),
          str([bar["label"] for bar in board["bars"]]))

    tree = read("/users/me/knowledge-tree", token=token_empty)
    check("空档案知识树：节点为空、三个计数都是 0",
          tree.get("nodes") == [] and tree.get("lit_count") == 0
          and tree.get("growing_count") == 0 and tree.get("not_started_count") == 0,
          str({k: tree.get(k) for k in ("lit_count", "growing_count", "not_started_count")}))
    check("空档案知识树：建议为空串、目标是 null（不编一句安慰话）",
          tree.get("suggestion") == "" and tree.get("next_target") is None,
          str({k: tree.get(k) for k in ("suggestion", "next_target")}))

    wrong = read_wrong(token_empty)
    check("空档案错题本：两个计数都是 0、列表为空",
          wrong.get("due_count") == 0 and wrong.get("total_count") == 0
          and wrong.get("items") == [],
          str({k: wrong.get(k) for k in ("due_count", "total_count")}))

    badges = read("/users/me/badges", token=token_empty)
    check("空档案勋章墙：恒返回全部 18 枚",
          badges.get("total") == 18 and len(badges.get("items", [])) == 18,
          f"total={badges.get('total')} len={len(badges.get('items', []))}")
    check("空档案勋章墙：一枚都没解锁",
          badges.get("unlocked_count") == 0
          and all(not item["unlocked"] for item in badges["items"]),
          str(badges.get("unlocked_count")))
    check("未解锁的也带名称与条件（原型要求保留轮廓与名称）",
          all(item["name"] and item["desc"] and item["icon"] for item in badges["items"]))
    check("勋章顺序即注册表顺序（前端不重排）",
          [item["key"] for item in badges["items"]][:2] == ["first_quest", "five_in_a_row"],
          str([item["key"] for item in badges["items"]][:3]))
    check("未解锁时 unlocked_at 为 null",
          all(item["unlocked_at"] is None for item in badges["items"]))
    check("每枚勋章的 tier 是 gold / rare",
          all(item["tier"] in ("gold", "rare") for item in badges["items"]),
          str(sorted({item["tier"] for item in badges["items"]})))

    # ---------- 3. 参数校验 ----------
    section("3. 参数校验（都是 4000，不是 500）")
    for name, path in {
        "range 不在闭集内": "/users/me/dashboard?range=90d",
        "range 大小写不符": "/users/me/dashboard?range=7D",
        "due 超出 0/1": "/users/me/wrong-questions?due=2",
        "due 非数字": "/users/me/wrong-questions?due=yes",
        "due 为负": "/users/me/wrong-questions?due=-1",
    }.items():
        status, body = call("GET", path, token=token_empty)
        check(f"{name} → 4000", body.get("code") == 4000, f"code={body.get('code')}")

    if args.skip_generate:
        print()
        print("[i] --skip-generate：跳过出题、结算与复习链")
        return report()

    # ---------- 4. 交一局全错的卷轴 ----------
    section("4. 交一局全错（真实模型出题 + 服务端权威判卷）")
    token_a, user_a = login(DEVICE_A, "成长链用户")

    before_stats = read("/users/me", token=token_a)["stats"]
    before_badges = read("/users/me/badges", token=token_a)["unlocked_count"]

    quiz = generate_quiz(token_a, args.topic)
    print(f"  题库 id={quiz['quiz_id']} 标题={quiz['title']!r} 题数={len(quiz['questions'])}")
    quiz_ids = [str(question["id"]) for question in quiz["questions"]]

    result = submit(token_a, quiz, wrong_answers(quiz), tag="全错")
    summary = result["summary"]
    print(f"  XP {summary['xp_gained']}/{summary['max_xp']} · 正确率 {summary['accuracy']}% · "
          f"入队错题 {result['wrong_queued_count']} 道")
    check("全错 = 0 XP", summary["xp_gained"] == 0, str(summary["xp_gained"]))
    check("全错 = 正确率 0%", summary["accuracy"] == 0, str(summary["accuracy"]))
    check("每道题都进了错题队列",
          result["wrong_queued_count"] == len(quiz["questions"]),
          f"{result['wrong_queued_count']} vs {len(quiz['questions'])}")
    check("逐题判定都是 wrong",
          all(item["outcome"] == "wrong" for item in result["results"]),
          str([item["outcome"] for item in result["results"]]))

    # ---------- 5. 档案四屏随结算变化 ----------
    section("5. 档案四屏（结算之后必须看得到这一局）")
    after_profile = read("/users/me", token=token_a)
    after_stats = after_profile["stats"]
    check("闯关副本 +1",
          after_stats["attempt_count"] == before_stats["attempt_count"] + 1,
          f"{before_stats['attempt_count']} → {after_stats['attempt_count']}")
    check("历史卷轴数 = 挑战次数（与闯关副本同值）",
          after_stats["scroll_count"] == after_stats["attempt_count"],
          f"{after_stats['scroll_count']} vs {after_stats['attempt_count']}")
    check("平均正确率被这一局拉低了（或本来就是 0）",
          after_stats["avg_accuracy"] <= before_stats["avg_accuracy"] if after_stats["attempt_count"] > 1
          else after_stats["avg_accuracy"] == 0,
          f"{before_stats['avg_accuracy']} → {after_stats['avg_accuracy']}")

    board = read("/users/me/dashboard?range=7d", token=token_a)
    check("看板 has_data / range_has_data 都变 true",
          board["has_data"] is True and board["range_has_data"] is True,
          str({k: board.get(k) for k in ("has_data", "range_has_data")}))
    check("最近 7 天答题量 ≥ 本局题数",
          board["week_answers"] >= len(quiz["questions"]), str(board["week_answers"]))
    check("今天那根柱子 ≥ 本局题数（本局落在最后一根）",
          board["bars"][-1]["count"] >= len(quiz["questions"]), str(board["bars"][-1]))
    check("看板领域条只列答过题的领域",
          board["domains"] and all(domain["total_count"] > 0 for domain in board["domains"]),
          str(board["domains"]))
    check("领域条按掌握度降序",
          [domain["mastery"] for domain in board["domains"]]
          == sorted((domain["mastery"] for domain in board["domains"]), reverse=True))
    check("range=30d 与 7d 的柱子完全一致（柱子与区间无关）",
          read("/users/me/dashboard?range=30d", token=token_a)["bars"] == board["bars"])

    tree = read("/users/me/knowledge-tree", token=token_a)
    check("知识树出现节点", len(tree["nodes"]) >= 1, str(len(tree["nodes"])))
    check("三态计数之和 = 节点数",
          tree["lit_count"] + tree["growing_count"] + tree["not_started_count"] == len(tree["nodes"]),
          f"{tree['lit_count']}+{tree['growing_count']}+{tree['not_started_count']}"
          f" vs {len(tree['nodes'])}")
    check("节点按掌握度降序",
          [node["mastery"] for node in tree["nodes"]]
          == sorted((node["mastery"] for node in tree["nodes"]), reverse=True))
    check("建议与 next_target 同指（要么都给要么都不给）",
          bool(tree["suggestion"]) == (tree["next_target"] is not None)
          and (tree["next_target"] is None or tree["next_target"] in tree["suggestion"]),
          f"suggestion={tree['suggestion']!r} next_target={tree['next_target']!r}")

    wrong = read_wrong(token_a)
    by_id = {item["question_id"]: item for item in wrong["items"]}
    check("本局每道错题都在队列里", all(qid in by_id for qid in quiz_ids),
          f"缺 {[qid for qid in quiz_ids if qid not in by_id]}")
    check("本局错题刚入队 → due=false（排的是明天）",
          all(not by_id[qid]["due"] for qid in quiz_ids if qid in by_id),
          str([(qid, by_id[qid]["due"]) for qid in quiz_ids if qid in by_id]))
    check("本局错题 stage 归零", all(by_id[qid]["stage"] == 0 for qid in quiz_ids if qid in by_id),
          str([by_id[qid]["stage"] for qid in quiz_ids if qid in by_id]))
    check("本局错题 wrong_count 都是 1",
          all(by_id[qid]["wrong_count"] >= 1 for qid in quiz_ids if qid in by_id),
          str([by_id[qid]["wrong_count"] for qid in quiz_ids if qid in by_id]))
    check("每条错题都带上知识点与来源卷轴",
          all(item["knowledge_point"] and item["quiz_title"] and item["stem"]
              for item in wrong["items"]))
    check("到期说法来自后端（「明天」/「已经到期」/「N 天后」）",
          all(item["next_review_label"] for item in wrong["items"]))

    badges = read("/users/me/badges", token=token_a)
    unlocked_keys = {item["key"] for item in badges["items"] if item["unlocked"]}
    check("首局挑战解锁「初次启程」", "first_quest" in unlocked_keys, str(sorted(unlocked_keys)))
    check("unlocked_count 与 items 里实际的解锁数一致",
          badges["unlocked_count"] == sum(1 for item in badges["items"] if item["unlocked"]),
          str(badges["unlocked_count"]))
    check("解锁数只增不减",
          badges["unlocked_count"] >= before_badges,
          f"{before_badges} → {badges['unlocked_count']}")
    check("已解锁的带解锁时间（带 UTC 偏移）",
          all(item["unlocked_at"] and ("+" in item["unlocked_at"] or item["unlocked_at"].endswith("Z"))
              for item in badges["items"] if item["unlocked"]),
          str([item["unlocked_at"] for item in badges["items"] if item["unlocked"]]))
    check("未解锁的仍带名称与条件", all(item["name"] and item["desc"] for item in badges["items"]))

    # ---------- 6. 复习组卷：没有到期的题时不建空局 ----------
    section("6. 复习组卷：没有到期的题时不建空局")
    # 「刚交完的错题排在明天」在第 5 节已经断言过（`due=false` + 「明天」文案），
    # 这里只验组卷本身：**队列里一道到期的都没有** 时才回 4005。
    #
    # 前置条件是**构造**出来的，不是靠「碰巧刚交完卷」—— 这个调试身份跨轮次累积，
    # 上一轮留下的到期错题会让组卷正常成功（那是正确行为，不是缺陷），
    # 于是「刚交完全错 → 4005」在第二轮跑时变成假红。显式构造前置条件，
    # 这条断言才能在任何一轮都成立。
    pushed = mark_wrong_questions_not_due(DEVICE_A)
    check("构造出「零到期」前置条件（推到未来的行数 ≥ 1）", pushed >= 1, str(pushed))

    status, body = call("POST", "/review/start", token=token_a)
    check("队列里一道都没到期 → 4005（不建空局）",
          body.get("code") == 4005, f"code={body.get('code')} HTTP {status}")
    check("提示语说的是自己的队列状态，不是「内容不存在」",
          "到期" in str(body.get("message", "")), str(body.get("message")))

    # ---------- 7. 复习链：到期 → 组卷 → 全对 → 原错题阶段推进 ----------
    section("7. 复习链（组卷前把调试身份的错题排期改成已到期）")
    touched = mark_wrong_questions_due(DEVICE_A)
    print(f"  已把 {touched} 条错题的排期改成已到期（只动 {DEVICE_A} 名下未攻克的记录）")
    check("确实有用例可改（否则下面的断言无意义）", touched >= 1, str(touched))

    all_wrong = read_wrong(token_a)
    due_wrong = read_wrong(token_a, due_only=True)
    check("due=1 只回到期的 → 列表长度等于 due_count",
          len(due_wrong["items"]) == due_wrong["due_count"],
          f"{len(due_wrong['items'])} vs {due_wrong['due_count']}")
    check("两个计数不随筛选变化（接口按整个队列统计）",
          (due_wrong["due_count"], due_wrong["total_count"])
          == (all_wrong["due_count"], all_wrong["total_count"]),
          f"due=1 → {due_wrong['due_count']}/{due_wrong['total_count']}；"
          f"不传 → {all_wrong['due_count']}/{all_wrong['total_count']}")
    check("due=1 的列表里每一条都 due=true", all(item["due"] for item in due_wrong["items"]))
    check("due=1 的列表比不传时短或等长",
          len(due_wrong["items"]) <= len(all_wrong["items"]))
    check("本局的题都在到期列表里", all(qid in {i["question_id"] for i in due_wrong["items"]}
                                  for qid in quiz_ids))

    # 服务端按 `next_review_at asc, id asc` 取前 MAX_QUESTIONS 道，与这里取前 N 条一致
    expect_count = min(MAX_REVIEW_QUESTIONS, due_wrong["due_count"])
    picked = [item["question_id"] for item in due_wrong["items"]][:expect_count]
    stage_before = {item["question_id"]: (item["stage"], item["wrong_count"])
                    for item in due_wrong["items"]}

    status, body = call("POST", "/review/start", token=token_a)
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] 复习组卷失败：HTTP {status} {body}")
    review = data_of(body)
    review_quiz = review["quiz"]
    print(f"  复习关卡 id={review_quiz['quiz_id']} 标题={review_quiz['title']!r} "
          f"题数={review['question_count']}")

    check("source_type 是 review", review_quiz["source_type"] == "review",
          str(review_quiz.get("source_type")))
    check("题数 = 题目数组长度 = min(5, 到期数)",
          review["question_count"] == len(review_quiz["questions"]) == expect_count,
          f"{review['question_count']} vs {len(review_quiz['questions'])} vs {expect_count}")
    check("标题固定为「旧识重温」（带题数会被刷满「卷轴收藏家」）",
          review_quiz["title"] == "旧识重温", str(review_quiz["title"]))
    check("副本题是**新题号**，与原创题号不重合",
          not ({str(q["id"]) for q in review_quiz["questions"]} & set(quiz_ids)),
          str([q["id"] for q in review_quiz["questions"]])[:120])
    check("复习局没有「输入资料」（复习不是一次召唤）",
          review_quiz.get("user_input") in (None, ""), str(review_quiz.get("user_input")))
    check("复习局的题与原错题逐字相同（是副本而不是重新生成）",
          {q["stem"] for q in review_quiz["questions"]}
          <= {by_id[qid]["stem"] for qid in picked},
          str([q["stem"][:24] for q in review_quiz["questions"]]))

    review_result = submit(token_a, review_quiz, correct_answers(review_quiz), tag="复习全对")
    check("复习全对 = 满分",
          review_result["summary"]["xp_gained"] == review_result["summary"]["max_xp"],
          str(review_result["summary"]))
    check("复习全对不再新增错题", review_result["wrong_queued_count"] == 0,
          str(review_result["wrong_queued_count"]))

    # 阶段推进到 `REVIEW_MASTERED_STAGE` 时错题会被**移出错题本**（`mastered=True`：
    # 行还留在库里，但不再出现在队列里）。第一轮跑时阶段从 0→1，不触发移出；
    # 第二轮跑时已经是 1→2，就会移出 —— 所以断言必须带上「移出」这个分支，
    # 否则脚本第二次跑必红，而红久了的闸门一定会被忽略（模块头部同一原则）。
    from app.core.constants import (  # noqa: PLC0415
        REVIEW_INTERVALS_DAYS,
        REVIEW_MASTERED_STAGE,
    )

    max_stage = len(REVIEW_INTERVALS_DAYS) - 1
    expect_stage = {qid: min(stage_before[qid][0] + 1, max_stage) for qid in picked}
    graduated = [qid for qid in picked if expect_stage[qid] >= REVIEW_MASTERED_STAGE]

    wrong_after = read_wrong(token_a)
    after_map = {item["question_id"]: (item["stage"], item["wrong_count"])
                 for item in wrong_after["items"]}
    advanced = [qid for qid in picked
                if qid in after_map and after_map[qid][0] == expect_stage[qid]]

    check("错题**总数 = 原总数 − 本轮移出的题数**（复习答对不该凭空多出一行重复）",
          wrong_after["total_count"] == all_wrong["total_count"] - len(graduated),
          f"{all_wrong['total_count']} → {wrong_after['total_count']}，"
          f"本轮达到掌握阶段 {len(graduated)} 道")
    check("原错题的 stage 推进到期望值（身份重定向到 origin_question_id 生效）",
          len(advanced) == len(picked) - len(graduated),
          f"推进 {len(advanced)}/{len(picked) - len(graduated)}"
          f"（另有 {len(graduated)} 道达到掌握阶段被移出）；"
          f"before={ {k: stage_before[k] for k in picked} } "
          f"after={ {k: after_map.get(k) for k in picked} }")
    check("达到掌握阶段（连续两次答对）的错题已移出错题本",
          all(qid not in after_map for qid in graduated),
          f"应移出={graduated}，仍留在列表里="
          f"{[q for q in graduated if q in after_map]}")
    check("原错题的 wrong_count 不变（复习答对不算又答错一次）",
          all(after_map[qid][1] == stage_before[qid][1] for qid in picked if qid in after_map),
          f"before={[stage_before[q][1] for q in picked]} "
          f"after={[after_map.get(q, (0, 0))[1] for q in picked]}")
    check("推进后这几道不再是「已经到期」",
          all(item["due"] is False for item in wrong_after["items"]
              if item["question_id"] in advanced),
          str([item["next_review_label"] for item in wrong_after["items"]
               if item["question_id"] in advanced]))
    check("没被选中的到期错题没有被动过",
          all(after_map[qid] == stage_before[qid]
              for qid in stage_before if qid not in picked and qid in after_map),
          str({qid: after_map.get(qid) for qid in stage_before if qid not in picked})[:200])

    # ---------- 8. 越权隔离 ----------
    section("8. 越权隔离：另一个用户读不到任何东西")
    token_b, user_b = login(DEVICE_EMPTY, "隔离用户")
    check("两个用户 id 不同", user_a["id"] != user_b["id"], f"{user_a['id']} vs {user_b['id']}")

    other = read_wrong(token_b)
    check("B 的错题本里没有 A 的任何一道题",
          not (set(after_map) & {item["question_id"] for item in other["items"]}),
          f"A={len(after_map)} B={len(other['items'])}")
    other_badges = read("/users/me/badges", token=token_b)
    check("B 的勋章墙仍是 0 枚（勋章按 user_id 过滤）",
          other_badges["unlocked_count"] == 0, str(other_badges["unlocked_count"]))
    other_board = read("/users/me/dashboard", token=token_b)
    check("B 的看板 has_data 仍为 false",
          other_board["has_data"] is False, str(other_board["has_data"]))
    other_tree = read("/users/me/knowledge-tree", token=token_b)
    check("B 的知识树仍是空",
          other_tree["nodes"] == [] and other_tree["lit_count"] == 0, str(other_tree["nodes"])[:120])

    status, body = call("POST", "/review/start", token=token_b)
    check("B 没有到期错题 → 4005（而不是拿到 A 的题）",
          body.get("code") == 4005, f"code={body.get('code')}")

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
