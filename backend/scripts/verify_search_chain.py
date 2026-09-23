#!/usr/bin/env python
"""联网检索增强出题 · 端到端抽验（`add-web-search-grounding` 第 11 组）。

用法（在 backend/ 目录下）：

    .venv/Scripts/python.exe scripts/verify_search_chain.py
    .venv/Scripts/python.exe scripts/verify_search_chain.py --only en,zh
    .venv/Scripts/python.exe scripts/verify_search_chain.py --out report.txt
    # 无 key 场景（另起一个 TAVILY_API_KEY= 空的实例）
    .venv/Scripts/python.exe scripts/verify_search_chain.py --base http://127.0.0.1:8001/api/v1 \
        --only en --expect-state degraded

## 它验证的是「真实链路」，不是「函数返回值」

前七组的测试全部是 mock 的（pytest 里 LLM 与检索一律不真调）。这个脚本是唯一
会真的去问 Tavily、真的让 DeepSeek 出题的地方，所以它承担三件 mock 测不出来的事：

1. **取材到底命中没有**。中文主题的命中率在规划期就是最大的未知数（design D3）——
   Tavily 的索引以英文为主，`country='china'` 只影响语种偏好、不保证命中率。
2. **落库的那两列是真的写进去了**。断言打在 `quizzes.search_state` 与
   `quizzes.references` 上，而不是响应体上 —— 重生成报告要靠这份快照。
3. **第一步的文案与真正走的取材路径一致**。「说联网却走了 Noop」这类不一致
   只在这一层能发现。

## 三条不做假的纪律

- **查询库**用的是 `app.db.session` 的业务库连接，读的是**真实落库结果**；
- 每个用例都会打印 `references` 的 `kind`/`source` 分布，好让人一眼看出
  「这条资料是用户给的页面还是模型自己搜的」；
- 抽验结论（尤其是命中率）**如实打印**，不做「应该没问题」的推断。

退出码：任一条断言失败返回 1。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# 允许直接以脚本方式运行（把 backend/ 加入 sys.path，与另外三个抽验脚本一致）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"

#: 实际使用的根地址，由 `--base` 覆盖
BASE = DEFAULT_BASE

#: 调试身份。`device_id` 派生稳定用户，所以每轮跑都是同一个账号，便于累积对比。
DEVICE = "verify-search-chain"

POLL_INTERVAL_S = 2.0
POLL_DEADLINE_S = 180.0

#: 真实存在的、内容足够出题的页面。选英文维基是因为它对 Tavily 必然可抓，
#: 而用例要验的是「按 URL 抓整页」这条路，不是抓取成功率。
REAL_PAGE = "https://en.wikipedia.org/wiki/Model_Context_Protocol"

#: 必然读不到的域名（RFC 2606 保留的 `.invalid`，不可能被解析）
DEAD_PAGE = "https://example.invalid/x"

#: 第二步的三种步骤名（`app/llm/search/base.py` 的 `StepDescriptor`）。
STEP_LINK = "读取你给的网页"
STEP_WEB = "联网检索知识"
STEP_NOOP = "理解你的输入"


@dataclass(frozen=True)
class Case:
    """一个端到端的抽查场景。"""

    key: str
    label: str
    user_input: str
    use_search: bool
    expect_step: str
    expect_states: tuple[str, ...]
    #: 期望 `references` 里出现的 `(kind, source)` 组合（每条都要出现）
    expect_refs: tuple[tuple[str, str], ...] = ()
    #: 期望题目里出现的关键词（至少命中一个）—— 用来做「题目内容与资料一致」的粗筛
    expect_keywords: tuple[str, ...] = ()
    note: str = ""


CASES: tuple[Case, ...] = (
    Case(
        key="en",
        label="英文·训练数据之外的新概念 · 联网开",
        user_input="什么是 Harness Engineering？它和普通 Prompt Engineering 有什么不同？",
        use_search=True,
        expect_step=STEP_WEB,
        expect_states=("hit", "degraded"),
        note="这是本次改动要解决的核心场景（用户提的例子）",
    ),
    Case(
        key="zh",
        label="中文·同一概念 · 联网开",
        user_input="我想了解 Harness Engineering 这个新概念，它是做什么的？",
        use_search=True,
        expect_step=STEP_WEB,
        expect_states=("hit", "degraded"),
        note="design D3 的未知数：中文查询的命中率",
    ),
    Case(
        key="link",
        label="真实网页链接 · 联网开",
        user_input=f"照着这个页面出题 {REAL_PAGE}",
        use_search=True,
        expect_step=STEP_LINK,
        expect_states=("hit", "degraded"),
        expect_refs=(("page", "user"),),
        expect_keywords=("MCP", "Model Context Protocol", "协议", "上下文"),
        note="链接一定被读；联网开时还会额外搜",
    ),
    Case(
        key="link_nosearch",
        label="真实网页链接 · 联网关",
        user_input=f"照着这个页面出题 {REAL_PAGE}",
        use_search=False,
        expect_step=STEP_LINK,
        expect_states=("hit", "degraded"),
        expect_refs=(("page", "user"),),
        note="`use_search=false` 压不住用户自己贴的链接（D4）",
    ),
    Case(
        key="plain_nosearch",
        label="纯文本 · 联网关",
        user_input="TCP 三次握手为什么不能是两次",
        use_search=False,
        expect_step=STEP_NOOP,
        expect_states=("off",),
        note="完全不走网络的路径",
    ),
    Case(
        key="bad_link",
        label="必然读不到的链接 · 联网开",
        user_input=f"照着这个页面出题 {DEAD_PAGE}",
        use_search=True,
        expect_step=STEP_LINK,
        expect_states=("degraded", "hit"),
        note="降级且不假装读过（D7）；联网开时仍可能靠搜索救回一些资料",
    ),
)

REPORT: list[str] = []
PASSED = 0
FAILED: list[str] = []

#: `--out` 的落点。放在模块级是为了让 `finally` 里也能拿到（见文件末尾）。
_OUT_PATH: list[str] = [""]


def emit(line: str = "") -> None:
    print(line)
    REPORT.append(line)


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASSED
    if condition:
        PASSED += 1
        emit(f"    ✅ {name}")
    else:
        FAILED.append(name)
        emit(f"    ❌ {name}{('  → ' + detail) if detail else ''}")
    return condition


# -----------------------------------------------------------------------------
# 极简 HTTP 客户端（stdlib，与 `verify_archive_chain.py` 同款）
# -----------------------------------------------------------------------------
def call(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict]:
    """发一次请求，返回 `(http_status, 解包后的响应体)`。

    `urllib` 对 4xx/5xx 抛 `HTTPError`，但错误响应体里同样有我们的信封，
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


# -----------------------------------------------------------------------------
# 落库结果（唯一能证明「资料快照真的写进去了」的地方）
# -----------------------------------------------------------------------------
#: 单题满分（`docs/MVP开发计划.md` §9.1）。**只用于打印**，不做断言 ——
#: 真值在 `app/services/scoring.py`，脚本里重算一遍只是为了报告好看，
#: 所以这里不去 import 它（脚本读的是接口回包，不是服务端内部对象）。
QUESTION_XP = {"single": 40, "multiple": 60, "judge": 20}


def full_score(quiz: dict) -> int:
    """题库满分。

    ⚠️ `total_xp` 是 `Quiz` 上的 `@property`，**不进 JSON**（`model_dump()` 不含属性），
    所以接口回包里取不到，只能按题型自己加。第一次跑就是栽在这个假设上
    （`KeyError: 'total_xp'`，整个用例的结论都没打印出来）。
    """
    if isinstance(quiz.get("total_xp"), int):
        return quiz["total_xp"]
    return sum(QUESTION_XP.get(q.get("type"), 0) for q in quiz.get("questions") or [])


def db_snapshot(quiz_id: str) -> dict:
    """按主键读 `quizzes` 的 `search_state` / `references`。"""
    from sqlalchemy import select  # noqa: PLC0415

    from app.db.session import get_session_factory  # noqa: PLC0415
    from app.db.tables import QuizRecord  # noqa: PLC0415

    with get_session_factory()() as session:
        row = session.scalar(select(QuizRecord).where(QuizRecord.id == int(quiz_id)))
        if row is None:
            return {"found": False}
        refs = row.references or []
        return {
            "found": True,
            "search_state": row.search_state,
            "references": refs,
            "kinds": {r.get("kind", "?") for r in refs},
            "sources": {r.get("source", "?") for r in refs},
        }


# -----------------------------------------------------------------------------
# 用例执行
# -----------------------------------------------------------------------------
@dataclass
class Outcome:
    case: Case
    quiz: dict = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    elapsed: float = 0.0
    db: dict = field(default_factory=dict)
    error: str = ""


def run_case(case: Case, token: str) -> Outcome:
    emit(f"  → 输入：{case.user_input}")
    emit(f"    意愿：use_search={case.use_search}" + (f" ｜ {case.note}" if case.note else ""))

    status, body = call(
        "POST",
        "/quiz/generate",
        {
            "user_input": case.user_input,
            "question_count": 5,
            "difficulty": "mixed",
            "use_search": case.use_search,
        },
        token=token,
    )
    if status != 200 or body.get("code") != 0:
        return Outcome(case=case, error=f"建任务失败 HTTP {status} {body}")

    task_id = data_of(body)["task_id"]
    started = time.monotonic()
    deadline = started + POLL_DEADLINE_S
    last: dict = {}
    while time.monotonic() < deadline:
        _, task_body = call("GET", f"/tasks/{task_id}", token=token)
        last = data_of(task_body)
        if last.get("status") in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(POLL_INTERVAL_S)

    elapsed = time.monotonic() - started
    steps = last.get("steps") or []
    if last.get("status") != "succeeded":
        return Outcome(case=case, steps=steps, elapsed=elapsed, error=f"任务终态 {last.get('status')}: {last.get('error')}")

    quiz = last["quiz"]
    return Outcome(
        case=case,
        quiz=quiz,
        steps=steps,
        elapsed=elapsed,
        db=db_snapshot(quiz["quiz_id"]),
    )


def report_case(outcome: Outcome) -> None:
    case = outcome.case
    emit("=" * 78)
    emit(f"[{case.key}] {case.label}")
    emit("=" * 78)

    if outcome.error:
        emit(f"  ❌ 用例未跑通：{outcome.error}")
        FAILED.append(f"{case.key}/任务")
        return

    # ---- 第一步文案（与真正走的取材路径是否一致）----
    first = outcome.steps[0] if outcome.steps else {}
    emit(f"  第一步：{first.get('name')!r} · {first.get('detail')!r}")
    check(
        f"{case.key}/第一步文案 == {case.expect_step!r}",
        first.get("name") == case.expect_step,
        f"实际 {first.get('name')!r}",
    )

    # ---- 步骤全貌（三态进度卡）----
    for step in outcome.steps:
        emit(f"    · {step.get('key'):8} {step.get('status'):8} {step.get('name')} — {step.get('detail')}")

    # ---- 落库结果 ----
    db = outcome.db
    if not db.get("found"):
        check(f"{case.key}/库里有这条卷轴", False, "按 quiz_id 查不到")
        return

    emit(f"  落库：search_state={db['search_state']!r} references={len(db['references'])} 条 "
         f"kind={sorted(db['kinds'])} source={sorted(db['sources'])}")
    for ref in db["references"][:6]:
        snippet = (ref.get("snippet") or "").replace("\n", " ")
        emit(f"    - [{ref.get('kind')}/{ref.get('source')}] {ref.get('title')!r} {ref.get('url')}")
        emit(f"      {snippet[:90]}…")

    check(
        f"{case.key}/search_state ∈ {case.expect_states}",
        db["search_state"] in case.expect_states,
        f"实际 {db['search_state']!r}",
    )

    for kind, source in case.expect_refs:
        check(
            f"{case.key}/references 含 kind={kind} source={source}",
            kind in db["kinds"] and source in db["sources"],
            f"实际 kind={sorted(db['kinds'])} source={sorted(db['sources'])}",
        )

    # ---- 题目内容（11.6 的粗筛：不许出现别处的同名概念）----
    quiz = outcome.quiz
    emit(f"  题库：{quiz['title']!r}（{len(quiz['questions'])} 题 · {full_score(quiz)} XP）")
    emit(f"    摘要：{quiz['summary']}")
    joined = []
    for question in quiz["questions"]:
        joined.append(question["stem"])
        joined.append(question["explanation"])
        emit(f"    · [{question['type']}] {question['stem']}")
        emit(f"        答案 {question['answer']} ｜ 讲解 {question['explanation'][:60]}")
    text = "\n".join(joined)

    if case.expect_keywords:
        hit = [word for word in case.expect_keywords if word in text]
        check(
            f"{case.key}/题目落在资料主题上（命中 {hit}）",
            bool(hit),
            f"关键词一个都没出现：{case.expect_keywords}",
        )

    emit(f"  耗时：{outcome.elapsed:.1f}s")
    emit("")


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
def main() -> int:
    global BASE

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"接口根地址，默认 {DEFAULT_BASE}")
    parser.add_argument("--only", default="", help="只跑这些用例（逗号分隔的 key）")
    parser.add_argument("--expect-state", default="", help="覆盖全部用例的 search_state 期望（如 degraded）")
    parser.add_argument("--out", default="", help="把结论另存为 UTF-8 文本（PowerShell 重定向会乱码）")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")
    _OUT_PATH[0] = args.out

    keys = {k.strip() for k in args.only.split(",") if k.strip()}
    selected = [c for c in CASES if not keys or c.key in keys]
    if args.expect_state:
        selected = [
            Case(**{**c.__dict__, "expect_states": (args.expect_state,)})
            for c in selected
        ]

    emit("=" * 78)
    emit("联网检索增强出题 · 端到端抽验（add-web-search-grounding 第 11 组）")
    emit("=" * 78)
    emit(f"  接口根地址 : {BASE}")

    # ⚠️ `search_enabled` 是**配置开关**（`knowledge_search_enabled`），不是「key 配好了」——
    # key 缺失是第三个状态，只有真去取一次才知道，所以它由用例的 `search_state` 断言覆盖。
    status, body = call("GET", "/health")
    health = data_of(body)
    emit(f"  search_enabled = {health.get('search_enabled')}  model = {health.get('model')}")
    check("11.1 health 里 search_enabled 为真", bool(health.get("search_enabled")),
          "这个实例没开检索；若这是「无 key 降级」场景，用 --only 与 --expect-state 单独跑")

    status, body = call("POST", "/auth/dev", {"device_id": DEVICE})
    if status != 200 or body.get("code") != 0:
        raise SystemExit(f"[x] 调试登录失败：HTTP {status} {body}")
    data = data_of(body)
    token = data["token"]
    emit(f"  调试身份   : user_id={data['user']['id']} {data['user']['nickname']!r}")
    emit("")

    for case in selected:
        # 每个用例**各自兜底**：一个用例崩了不该带走整份结论。
        # 第一次跑就是栽在这 —— 打印题库时 `KeyError: 'total_xp'` 抛到 main 外面，
        # `--out` 那一行永远没执行，前面几十行证据全丢，只剩一份乱码控制台。
        try:
            report_case(run_case(case, token))
        except Exception as exc:  # noqa: BLE001 —— 抽验脚本要的是「跑完并留下证据」
            emit(f"[{case.key}] ❌ 脚本异常：{type(exc).__name__}: {exc}")
            FAILED.append(f"{case.key}/脚本异常")

    emit("=" * 78)
    emit(f"汇总：{PASSED} 项断言通过，{len(FAILED)} 项失败")
    for name in FAILED:
        emit(f"  ❌ {name}")
    emit("=" * 78)

    return 1 if FAILED else 0


if __name__ == "__main__":
    _code = 1
    try:
        _code = main()
    finally:
        # 落盘放 finally：无论断言失败还是脚本本身崩掉，已跑到的结论都要留在磁盘上。
        # PowerShell 的 `*>` 会用 GBK 解 UTF-8 字节流（中文必乱码），所以由脚本自己写。
        if _OUT_PATH[0]:
            Path(_OUT_PATH[0]).write_text("\n".join(REPORT) + "\n", encoding="utf-8")
            print(f"[ok] 结论已写入 {_OUT_PATH[0]}")
    raise SystemExit(_code)
