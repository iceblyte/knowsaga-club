"""资料快照的落库与三态可区分性（`add-web-search-grounding` 第 6、7 组）。

## 本文件的两半

- **上半（第 6 组）**：`search_state` 三态可区分、`references` 能原样读回、体积按上限压住。
- **下半（第 7 组）**：走 HTTP 接口验证「本次意愿（`use_search`）+ 输入里的链接」这一对入参
  真的改变了取材行为 —— 用真实 `TavilySearchProvider` 配**假模型 + 假工具**，
  一个包都不联网。

## 第 6 组要证明的唯一一件事

「这份卷轴的题目是依据什么出的」**事后答得出来**。所以要能区分三种情况：

| `search_state` | 含义 | 该去哪查 |
|---|---|---|
| `off` | 没去取（开关关 / 用户关） | 正常，不是问题 |
| `degraded` | 取了但一条没取到 | 主题太新 / 网页抓不动 / 额度用尽 |
| `hit` | 取到了 N 条 | 看 `references` |

把三者混成一个布尔，排查时就分不开「配置问题」与「主题问题」——
这是 design D9 选择**两列**而不是一列 JSON 的全部理由。

## 两条测试红线（本文件全程遵守）

- 用 `db_session`，**不用** `get_session_factory()`（那是业务库工厂）。
- **不写死 `user_id=1`**：本文件自己按 `openid` 建用户，从 `flush()` 后的对象上取 id。
- 读了之后若还要读接口/另一次写入的结果，先 `rollback()`（REPEATABLE READ）。

## fixture 里没有第三方网页正文

`references` 的样本全部是手工构造的假数据（13.3 要求被跟踪文件里不出现真实抓取内容）。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.tables import QuizRecord, User
from app.llm import quiz_chain
from app.llm.search import TavilySearchProvider
from app.llm.search.base import (
    ReferenceCaps,
    SearchOutcome,
    SearchRequest,
    SearchResult,
    build_initial_step,
)
from app.llm.search.collector import serialize_references
from app.models.quiz import Quiz
from app.services import quiz_repository, quiz_service

CAPS = ReferenceCaps(snippet_max_chars=100, page_max_chars=200, total_max_chars=1000)


def _make_user(session, openid: str = "openid-search-test") -> int:
    """建一个用户并 flush（**不写死 id**）。"""
    user = User(openid=openid, nickname="取材测试员")
    session.add(user)
    session.flush()
    return int(user.id)


def _quiz(payload: dict) -> Quiz:
    return Quiz.model_validate(payload)


def _refs(*items: SearchResult) -> list[dict[str, str]]:
    return serialize_references(items, caps=CAPS)


USER_REF = SearchResult(
    title="用户给的页面",
    url="https://user.example/page",
    snippet="# 标题\n\n整页正文内容",
    kind="page",
    source="user",
)
WEB_REF = SearchResult(
    title="检索到的文章",
    url="https://web.example/post",
    snippet="检索摘要片段",
    kind="snippet",
    source="web",
)


# ---------------------------------------------------------------- 三态可区分
def test_off_state_has_no_references_row(db_session, sample_quiz_payload: dict) -> None:
    """`off` = 没去取。这一列必须有值（不能是 NULL），否则与存量旧行分不开。"""
    user_id = _make_user(db_session)

    stored = quiz_repository.persist_quiz(
        db_session, user_id=user_id, quiz=_quiz(sample_quiz_payload), search_state="off"
    )
    db_session.rollback()  # 换快照再读，确保读到的是真正落库的值

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert row.search_state == "off"
    assert row.references is None, "没去取就不该有空数组 —— NULL 与 [] 不是一回事"


def test_degraded_state_is_distinguishable_from_off(db_session, sample_quiz_payload: dict) -> None:
    """`degraded`（取了没取到）必须与 `off`（没去取）**分得开**。"""
    user_id = _make_user(db_session, "openid-degraded")

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="degraded",
        references=[],
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert row.search_state == "degraded"
    assert row.search_state != "off", "这两种情况的排查路径完全不同"


def test_hit_state_round_trips_references(db_session, sample_quiz_payload: dict) -> None:
    """`hit` 且 `references` 能原样读回，`kind` 与 `source` 都在。"""
    user_id = _make_user(db_session, "openid-hit")

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=_refs(USER_REF, WEB_REF),
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert row.search_state == "hit"
    refs = row.references
    assert isinstance(refs, list) and len(refs) == 2
    assert refs[0]["source"] == "user", "「我贴的链接读到没有」要能查出来"
    assert refs[0]["kind"] == "page"
    assert refs[1]["source"] == "web"
    assert refs[1]["kind"] == "snippet"


def test_references_urls_are_stored_verbatim(db_session, sample_quiz_payload: dict) -> None:
    """URL 原样保存：将来做「参考来源展示」时它就是链接目标，不能被截断或改写。"""
    user_id = _make_user(db_session, "openid-url")
    long_url = "https://web.example/" + "a" * 180 + "?q=1&x=%E4%B8%AD"

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=_refs(SearchResult(title="t", url=long_url, snippet="s")),
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert row.references[0]["url"] == long_url


# ---------------------------------------------------------------- 体积约束
def test_snippet_is_clipped_to_the_shared_cap(db_session, sample_quiz_payload: dict) -> None:
    """片段按 `search_snippet_max_chars` 对应的上限截断（复用同一组常量）。"""
    user_id = _make_user(db_session, "openid-clip")
    caps = ReferenceCaps.from_settings(Settings(_env_file=None))
    huge = "字" * (caps.snippet_max_chars + 500)

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=serialize_references(
            [SearchResult(title="t", url="https://a.example", snippet=huge)], caps=caps
        ),
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    snippet = row.references[0]["snippet"]
    assert len(snippet) < len(huge)
    assert "截断" in snippet


def test_full_page_body_is_never_stored(db_session, sample_quiz_payload: dict) -> None:
    """整页正文**不许**整篇落库：实测单页可达 7.5 万字符，这张表会迅速膨胀。"""
    user_id = _make_user(db_session, "openid-nobody")
    caps = ReferenceCaps.from_settings(Settings(_env_file=None))
    page = "正" * 80_000

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=serialize_references(
            [SearchResult(title="t", url="https://a.example", snippet=page, kind="page")], caps=caps
        ),
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert len(row.references[0]["snippet"]) <= caps.page_max_chars + 16


# ---------------------------------------------------------------- 默认不破坏存量路径
def test_default_is_off_for_existing_callers(db_session, sample_quiz_payload: dict) -> None:
    """不传新参数的调用方（复习关卡等）拿到 `off` —— 它们的语义确实就是「没用外部资料」。"""
    user_id = _make_user(db_session, "openid-default")

    stored = quiz_repository.persist_quiz(
        db_session, user_id=user_id, quiz=_quiz(sample_quiz_payload)
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert row.search_state == "off"
    assert row.references is None


def test_unknown_state_is_clipped_not_rejected(db_session, sample_quiz_payload: dict) -> None:
    """状态值超长时按列宽截断，而不是让整次出题因为一个枚举值白跑。"""
    user_id = _make_user(db_session, "openid-longstate")

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="x" * 40,
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert len(row.search_state) <= quiz_repository.SEARCH_STATE_MAX


# ---------------------------------------------------------------- search_state 的判定
@pytest.mark.parametrize(
    ("end_reason", "results", "expected"),
    [
        ("disabled", (), "off"),
        ("done", (), "degraded"),
        ("no_tool_calls", (), "degraded"),
        ("rounds_exhausted", (), "degraded"),
        ("budget_exhausted", (), "degraded"),
        ("error", (), "degraded"),
        ("done", (USER_REF,), "hit"),
        # 「没去取」与「有资料」同时出现是矛盾状态；派生规则里**资料优先**，
        # 这样 `search_state == "hit"` 与 `not degraded` 永远是同一个条件。
        ("disabled", (USER_REF,), "hit"),
    ],
)
def test_search_state_derivation(end_reason: str, results: tuple, expected: str) -> None:
    """三态由「结束原因 + 有没有资料」派生，不是一个能被设错的独立字段。"""
    outcome = SearchOutcome(provider="tavily", results=results, end_reason=end_reason)  # type: ignore[arg-type]

    assert outcome.search_state == expected


def test_search_state_is_consistent_with_degraded() -> None:
    """`search_state == "off" / "degraded"` ⇒ `degraded is True`。两个派生值不许打架。"""
    for end_reason in ("disabled", "done", "no_tool_calls", "error"):
        outcome = SearchOutcome(provider="tavily", end_reason=end_reason)  # type: ignore[arg-type]
        assert outcome.degraded is True
        assert outcome.search_state in ("off", "degraded")

    hit = SearchOutcome(provider="tavily", results=(USER_REF,), end_reason="done")
    assert hit.degraded is False
    assert hit.search_state == "hit"


# ---------------------------------------------------------------- 真实取材 → 落库的形状
def test_repository_never_sees_raw_third_party_text(db_session, sample_quiz_payload: dict) -> None:
    """落库的是采集器压过的结构，字段固定五项 —— 多出来的键不许被顺手写进去。"""
    user_id = _make_user(db_session, "openid-shape")

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=_refs(WEB_REF),
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert set(row.references[0]) == {"title", "url", "snippet", "kind", "source"}


def test_references_do_not_leak_into_other_columns(db_session, sample_quiz_payload: dict) -> None:
    """资料只进 `references`，不许顺手写进 `source_name` / `summary` 这类展示列。"""
    user_id = _make_user(db_session, "openid-noleak")

    stored = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=_refs(USER_REF),
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert "example.com" not in row.source_name
    assert "example.com" not in row.summary


def test_a_second_quiz_does_not_inherit_the_first_snapshot(db_session, sample_quiz_payload: dict) -> None:
    """两份卷轴各自持有自己的快照 —— 快照不是挂在用户或全局上的。"""
    user_id = _make_user(db_session, "openid-two")

    first = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="hit",
        references=_refs(WEB_REF),
    )
    second = quiz_repository.persist_quiz(
        db_session,
        user_id=user_id,
        quiz=_quiz(sample_quiz_payload),
        search_state="degraded",
        references=[],
    )
    db_session.rollback()

    rows = {
        int(r.id): r
        for r in db_session.execute(select(QuizRecord).order_by(QuizRecord.id)).scalars()
    }
    assert rows[int(first.quiz_id)].references is not None
    assert rows[int(second.quiz_id)].references == []
    assert rows[int(second.quiz_id)].search_state == "degraded"


def test_search_request_is_not_persisted(db_session, sample_quiz_payload: dict) -> None:
    """用户输入本身仍原样进 `source_name`（既有行为不许被这次改动挤掉）。"""
    user_id = _make_user(db_session, "openid-input")

    stored = quiz_repository.persist_quiz(
        db_session, user_id=user_id, quiz=_quiz(sample_quiz_payload), search_state="off"
    )
    db_session.rollback()

    row = db_session.get(QuizRecord, int(stored.quiz_id))
    assert row is not None
    assert row.source_name == sample_quiz_payload["user_input"]


def test_search_request_helper_still_builds_from_input() -> None:
    """`_build_search_request` 是「入参 → 取材请求」的**唯一**组装点（第 7 组接管后）。"""
    settings = Settings(_env_file=None, search_max_results=7)

    request = quiz_service._build_search_request("什么是 Harness Engineering", settings)

    assert isinstance(request, SearchRequest)
    assert request.query == "什么是 Harness Engineering"
    assert request.max_results == 7
    assert request.urls == (), "这句话里没有链接"
    assert request.use_search is True, "不传就是「想搜」——默认开启是产品决策"


# =============================================================================
# 第 7 组：出题入参 —— 本次意愿（use_search）+ 输入里的链接
# =============================================================================
#
# 这两件事**只能在接口层验证**：它们是从 HTTP 请求体一路传到取材循环的，
# 中间经过「建任务时展示的第一步文案」与「真正取材时用的请求」两个消费者 ——
# 只要有一处没接上，用户看到的就是「点了联网但其实没联网」。
#
# 用**真实** `TavilySearchProvider` 配假模型 + 假工具：走的是生产代码的整条路径，
# 只有最外层的网络调用被换掉（与项目「pytest 里 LLM 一律 mock」一致）。

GENERATE_URL = "/api/v1/quiz/generate"
TASKS_URL = "/api/v1/tasks/{task_id}"
PLAIN_INPUT = "我想学习什么是 RAG，以及它和传统搜索有什么区别"
LINKED_PAGE = "https://user.example/page"
LINKED_INPUT = f"请按这个页面出题 {LINKED_PAGE}"


class _FakeTool:
    """假工具：只记录被调用的参数，返回构造时给的东西。"""

    def __init__(self, name: str, payload: object) -> None:
        self.name = name
        self._payload = payload
        self.calls: list[dict] = []

    def invoke(self, args: dict) -> object:
        self.calls.append(dict(args))
        return self._payload


class _SilentLLM:
    """一轮就收手的假模型（不要求任何工具）。"""

    def __init__(self) -> None:
        self.rounds = 0
        self.bound: list[object] = []

    def bind_tools(self, tools: list[object]) -> _SilentLLM:
        self.bound = list(tools)
        return self

    def invoke(self, messages: list[object]) -> AIMessage:  # noqa: ARG002
        self.rounds += 1
        return AIMessage(content="资料已足够，不再调用工具。")


class _SpyProvider:
    """把真实 Provider 包一层，只为记录「服务端问了它什么」。**透明**，不做任何断言。"""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.requests: list[SearchRequest] = []
        self.name = inner.name  # type: ignore[attr-defined]
        self.can_search_web = inner.can_search_web  # type: ignore[attr-defined]
        self.can_read_pages = inner.can_read_pages  # type: ignore[attr-defined]

    def initial_step(self, request: SearchRequest):  # noqa: ANN201
        return self._inner.initial_step(request)  # type: ignore[attr-defined]

    def gather(self, request: SearchRequest, *, on_progress: object = None):  # noqa: ANN201
        self.requests.append(request)
        return self._inner.gather(request, on_progress=on_progress)  # type: ignore[attr-defined]


class _ExplodingProvider:
    """违反契约、`gather` 直接抛异常的 Provider（服务端必须自己兜住）。"""

    name = "tavily"
    can_search_web = True
    can_read_pages = True

    def __init__(self) -> None:
        self.gather_calls = 0

    def initial_step(self, request: SearchRequest):  # noqa: ANN201
        return build_initial_step(request, can_search_web=True, can_read_pages=True)

    def gather(self, request: SearchRequest, *, on_progress: object = None):  # noqa: ANN201, ARG002
        self.gather_calls += 1
        raise RuntimeError("取材链路整个炸了")


SEARCH_HIT = {"query": "q", "results": [{"title": "检索到的文章", "url": "https://web.example/p", "content": "片段"}]}
EXTRACT_HIT = {"results": [{"title": "用户给的页面", "url": LINKED_PAGE, "raw_content": "整页正文"}], "failed_results": []}


def _provider_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "knowledge_search_enabled": True,
        "knowledge_search_provider": "tavily",
        "tavily_api_key": "test-key",
        "search_agent_max_rounds": 2,
        "search_agent_max_tool_calls": 2,
        "search_agent_budget_seconds": 10,
        "search_tool_timeout_seconds": 1,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture
def wiring(monkeypatch: pytest.MonkeyPatch, sample_quiz_payload: dict):
    """装好「假模型 + 假工具 + 真实 Provider」的整条链，并替换出题函数。"""
    search = _FakeTool("tavily_search", SEARCH_HIT)
    extract = _FakeTool("tavily_extract", EXTRACT_HIT)
    llm = _SilentLLM()
    inner = TavilySearchProvider(_provider_settings(), llm=llm, tools=(search, extract), caps=CAPS)
    spy = _SpyProvider(inner)
    monkeypatch.setattr(quiz_service, "get_search_provider", lambda _s=None: spy)
    monkeypatch.setattr(
        quiz_chain,
        "generate_quiz",
        lambda **_: Quiz.model_validate({**sample_quiz_payload, "user_input": PLAIN_INPUT}),
    )
    return spy, search, extract, llm


def _post(client, headers: dict, body: dict):  # noqa: ANN202
    return client.post(GENERATE_URL, json=body, headers=headers)


def _task(client, headers: dict, task_id: str) -> dict:
    return client.get(TASKS_URL.format(task_id=task_id), headers=headers).json()["data"]


def _first_step(task: dict) -> dict:
    return task["steps"][0]


@pytest.fixture
def read_session(db_engine):  # noqa: ANN001, ANN201
    """读断言用的独立会话（**不与接口共享快照**，否则读到的可能是过期值）。"""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _stored_quiz(session, task: dict) -> QuizRecord:
    """按任务返回的题库 id 取库里那一行。"""
    row = session.get(QuizRecord, int(task["quiz"]["quiz_id"]))
    assert row is not None, "任务成功了就必须能查到题库"
    return row


# ---------------------------------------------------------------- ① 默认开启
def test_use_search_defaults_to_on(db_client, db_scope, auth_headers, inline_submit, wiring) -> None:
    """请求体不带 `use_search` → 按**开启**处理，Provider 真的被问了一次。"""
    spy, _search, _extract, llm = wiring

    resp = _post(db_client, auth_headers, {"user_input": PLAIN_INPUT})

    assert resp.json()["code"] == 0
    assert len(spy.requests) == 1, "开关开 ⇒ Provider 必须被调用"
    assert spy.requests[0].use_search is True
    assert spy.requests[0].wants_external is True
    assert [getattr(t, "name", None) for t in llm.bound] == ["tavily_search", "tavily_extract"], (
        "想搜就该两个工具都给它 —— 由它自己决定调哪个"
    )


def test_default_step_name_says_online_search(db_client, db_scope, auth_headers, inline_submit, wiring) -> None:
    """默认开启时，第一步叫「联网检索知识」——名字必须与真正做的事一致。"""
    task_id = _post(db_client, auth_headers, {"user_input": PLAIN_INPUT}).json()["data"]["task_id"]

    assert _first_step(_task(db_client, auth_headers, task_id))["name"] == "联网检索知识"


# ---------------------------------------------------------------- ② 关掉且没链接
def test_use_search_false_without_links_touches_nothing(
    db_client, db_scope, auth_headers, inline_submit, wiring
) -> None:
    """`use_search=false` + 无链接 → 一次工具、一次模型调用都不该发生。

    ⚠️ 断言的是**外部动作为零**（工具没被调、模型没被调），不是「Provider 没被调用」——
    服务端仍会问 Provider 一次，由它回答「这次不用出去」（`end_reason='disabled'`）。
    两者不是一回事：前者才是用户能感知的「没联网」。
    """
    spy, search, extract, llm = wiring

    resp = _post(db_client, auth_headers, {"user_input": PLAIN_INPUT, "use_search": False})
    task = _task(db_client, auth_headers, resp.json()["data"]["task_id"])

    assert spy.requests[0].wants_external is False
    assert llm.rounds == 0, "完全不想联网时，连模型都不该被调用（provider 层先拦）"
    assert search.calls == []
    assert extract.calls == []
    assert _first_step(task)["name"] == "理解你的输入", "关掉搜索还显示「联网检索知识」就是文案在说谎"
    assert "未取到可用资料" not in _first_step(task)["detail"], "压根没去取，不该说「未取到」"
    assert task["status"] == "succeeded"


# ---------------------------------------------------------------- ③ 关掉但有链接
def test_links_are_read_even_when_search_is_off(
    db_client, db_scope, auth_headers, inline_submit, wiring
) -> None:
    """`use_search=false` + 有链接 → 仍读链接（合作 3），第一步叫「读取你给的网页」。"""
    spy, search, extract, llm = wiring

    resp = _post(db_client, auth_headers, {"user_input": LINKED_INPUT, "use_search": False})
    task = _task(db_client, auth_headers, resp.json()["data"]["task_id"])

    assert spy.requests[0].urls == (LINKED_PAGE,), "链接由服务端自己从输入里抽，不看前端的判断"
    assert spy.requests[0].wants_external is True, "链接必读，不该被开关压掉"
    assert extract.calls == [{"urls": [LINKED_PAGE]}], "服务端兜底必须先读一次"
    assert search.calls == [], "关掉搜索就不该有任何搜索调用"
    assert [getattr(t, "name", None) for t in llm.bound] == ["tavily_extract"], (
        "连 search 工具都不该绑给模型 —— 让「不该发生」变成「不可能发生」"
    )
    assert _first_step(task)["name"] == "读取你给的网页"
    assert task["status"] == "succeeded"


def test_linked_quiz_records_the_page_as_user_sourced(
    db_client, db_scope, auth_headers, inline_submit, wiring, read_session  # noqa: ARG001
) -> None:
    """读到的页面在快照里标成 `source='user'` + `kind='page'` —— 「我贴的链接读到没有」要查得出来。"""
    task_id = _post(db_client, auth_headers, {"user_input": LINKED_INPUT}).json()["data"]["task_id"]
    task = _task(db_client, auth_headers, task_id)

    row = _stored_quiz(read_session, task)
    assert row.search_state == "hit"
    refs = row.references
    assert len(refs) == 1, "同一个 URL 不该同时以片段和整页两种形态存在"
    assert refs[0]["source"] == "user"
    assert refs[0]["kind"] == "page"
    assert refs[0]["url"] == LINKED_PAGE


# ---------------------------------------------------------------- ④ 取证失败不中断
def _patch_exploding(monkeypatch: pytest.MonkeyPatch, sample_quiz_payload: dict) -> _ExplodingProvider:
    exploding = _ExplodingProvider()
    monkeypatch.setattr(quiz_service, "get_search_provider", lambda _s=None: exploding)
    monkeypatch.setattr(
        quiz_chain,
        "generate_quiz",
        lambda **_: Quiz.model_validate({**sample_quiz_payload, "user_input": PLAIN_INPUT}),
    )
    return exploding


def test_gathering_failure_does_not_fail_the_task(
    db_client, db_scope, auth_headers, inline_submit, monkeypatch: pytest.MonkeyPatch, sample_quiz_payload: dict
) -> None:
    """取材整个抛异常 → 任务仍 `succeeded`（降级出题，不打断用户）。

    契约上说 `gather()` 不许抛异常，但调用侧**不能信任**这条：取材只是增强项，
    它炸一次不该让用户白等十秒再看到一个失败任务。
    """
    exploding = _patch_exploding(monkeypatch, sample_quiz_payload)

    resp = _post(db_client, auth_headers, {"user_input": PLAIN_INPUT})
    task = _task(db_client, auth_headers, resp.json()["data"]["task_id"])

    assert exploding.gather_calls == 1, "确实走了取材这条路"
    assert task["status"] == "succeeded", "取材炸了也必须把题出出来"
    assert task["quiz"]["questions"], "题库要完整"


def test_search_state_is_degraded_after_a_gathering_failure(
    db_client,
    db_scope,
    auth_headers,
    inline_submit,
    monkeypatch: pytest.MonkeyPatch,
    sample_quiz_payload: dict,
    read_session,  # noqa: ANN001
) -> None:
    """取证炸掉的那次落库是 `degraded` —— 事后能查出来「这次没资料」。"""
    _patch_exploding(monkeypatch, sample_quiz_payload)

    resp = _post(db_client, auth_headers, {"user_input": PLAIN_INPUT})
    task = _task(db_client, auth_headers, resp.json()["data"]["task_id"])

    row = _stored_quiz(read_session, task)
    assert row.search_state == "degraded", "「去取了但失败」要能与「没去取」分开"
    assert row.references == []


# ---------------------------------------------------------------- ⑤ 配置错要立刻报
def test_missing_key_fails_the_request_instead_of_silently_degrading(
    db_client, auth_headers, inline_submit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关开 + provider=tavily 但没配 key → **立刻** 5000，而不是静默降级成纯模型出题。

    「静默降级」在这里是最坏的结果：用户以为自己在用联网能力，实际拿到的还是
    「AI 凭记忆出题」—— 那正是本次要修的那个失败模式。所以这条**不打桩** Provider，
    走真实工厂，验的就是「配置错了会不会被静默吃掉」。
    """
    monkeypatch.setenv("KNOWLEDGE_SEARCH_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()

    resp = _post(db_client, auth_headers, {"user_input": PLAIN_INPUT})

    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 5000
    assert "TAVILY_API_KEY" in body["message"], "要让运维一眼看出该去填哪个变量"
    assert not resp.json()["data"], "失败时不该给出 task_id —— 那会让前端去轮询一个不存在的任务"
