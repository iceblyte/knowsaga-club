"""出题链接入知识库（`add-private-knowledge-base` 第 9 组）。

`POST /quiz/generate` 多一个**可选** `kb_id`，它决定这次出题去哪个库里取资料。
本文件守三件事：

## 一、作用域是「这个用户 + 这一个库」，不是裸的 kb_id

带 `kb_id` 时知识库作用域必须被带进 `SearchRequest`（`KbScope`），
而且是**当前登录用户**的 id —— 客户端只提供 `kb_id`，`user_id` 由服务端填。
两者都由客户端提供的话，越权就只是一个数字的事。

## 二、归属校验必须发生在**建任务之前**（design D13）

越权 / 不存在 → 4005，并且**一个任务都不该被创建**。
反例（建完任务再校验）的症状是：用户拿到 `task_id`、看着进度条跑几秒，
最后收获一个注定失败的任务 —— 而这件事在第 0 毫秒就已经能确定了。
所以这里直接窥探 `task_service.create_task` 的调用次数来钉住顺序，
而不是只看返回码（只看返回码的话，「先建任务后校验」也能通过）。

## 三、不带 `kb_id` 时请求与今天**逐位一致**

这是「新增一个可选字段」的唯一硬证据。`SearchRequest` 是 frozen dataclass，
所以「逐位一致」是可以直接 `==` 出来的 —— 比逐个字段断言更难作假：
漏掉一个字段、或者给某个字段换了个默认值，这里就会响。

## 为什么用窥探替身而不是真 Provider

真跑就会走进 `run_search_agent` → `build_chat_model()`，也就是一次**真实模型请求**
（测试红线）。本文件验的是「接线」，所以把 `get_search_provider` 换成一个只记录
请求的替身；取材循环本身的形状由 `test_search_agent_kb.py` 覆盖。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import ErrorCode
from app.llm import quiz_chain
from app.llm.search.base import KbScope, SearchOutcome, SearchRequest, build_initial_step
from app.models.quiz import Quiz
from app.services import quiz_service, task_service
from app.utils.text_cleaner import validate_input

GENERATE_URL = "/api/v1/quiz/generate"
KB = "/api/v1/kb"
ME = "/api/v1/users/me"

#: 干净、长度足够、不含链接的输入。刻意不含链接 —— 那样 `urls` 恒为空元组，
#: 「逐位一致」那条断言里的期望值才不需要跟着正则走。
VALID_INPUT = "我想系统学习监督学习的基本原理和常见算法"


@pytest.fixture(autouse=True)
def _kb(kb_harness):  # noqa: ANN001, ANN201, ARG001
    """本文件里每条用例都在「知识库已开启 + 假向量化」的环境里跑。

    出题链本身不向量化，但要经手 `kb_service` 的归属校验 ——
    而它读的是同一套配置，所以环境必须一起打开。
    """
    return kb_harness


@pytest.fixture
def fake_quiz(sample_quiz_payload: dict) -> Quiz:
    """一份可直接返回的合法题库（与 `test_quiz_api.py` 同源）。"""
    payload = dict(sample_quiz_payload)
    payload["user_input"] = VALID_INPUT
    return Quiz.model_validate(payload)


@pytest.fixture
def patch_generate(monkeypatch: pytest.MonkeyPatch, fake_quiz: Quiz) -> None:
    """把出题链替换成「立刻返回固定题库」，不发任何真实请求。"""
    monkeypatch.setattr(quiz_chain, "generate_quiz", lambda **_: fake_quiz)


class SpyProvider:
    """只记录取材请求的 Provider 替身（**不碰网络、不碰模型**）。

    `initial_step` 与 `gather` 都按真实的 `build_initial_step` 算 ——
    这样 `submit_quiz_request` 里建任务那一步拿到的第一步文案与真实情况一致，
    不会因为替身太笨而漏掉「带库时第一步该叫什么」那类问题。
    """

    name = "spy"
    can_search_web = False
    can_read_pages = False

    def __init__(self) -> None:
        self.requests: list[SearchRequest] = []

    def initial_step(self, request: SearchRequest):
        return build_initial_step(
            request,
            can_search_web=False,
            can_read_pages=False,
            can_search_kb=request.has_kb,
        )

    def gather(self, request: SearchRequest, *, on_progress=None) -> SearchOutcome:  # noqa: ANN001
        self.requests.append(request)
        return SearchOutcome(
            provider=self.name,
            step_name=self.initial_step(request).name,
            results=(),
            end_reason="disabled",
        )


@pytest.fixture
def spy_provider(monkeypatch: pytest.MonkeyPatch) -> SpyProvider:
    """把 Provider 工厂换成替身，并把每次取材请求留档。"""
    spy = SpyProvider()
    monkeypatch.setattr(quiz_service, "get_search_provider", lambda _settings: spy)
    return spy


@pytest.fixture
def created_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """记录 `task_service.create_task` 的调用（**真的建**，只是留一份记录）。

    不换成「什么都不做」的假货：留档的同时让真实路径继续跑，
    这样「带了合法 kb_id 时任务确实被建出来了」仍然是被验过的。
    """
    calls: list[dict] = []
    real = task_service.create_task

    def _spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append({"args": args, "kwargs": kwargs})
        return real(*args, **kwargs)

    monkeypatch.setattr(task_service, "create_task", _spy)
    return calls


# -----------------------------------------------------------------------------
# 小工具
# -----------------------------------------------------------------------------
def _make_base(client: TestClient, headers: dict, name: str = "机器学习") -> int:
    resp = client.post(KB, headers=headers, json={"name": name})
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["id"])


def _me_id(client: TestClient, headers: dict) -> int:
    """当前登录用户的 id。

    刻意走接口而不是从数据库里捞：它就是服务端在鉴权时认定的那个人，
    正是 `KbScope.user_id` 该等于的值。

    ⚠️ 形状是 `data["user"]["id"]`（`GET /users/me` 返回 `ProfileResponse`
    = `{user, stats}`），不是 `data["id"]`。
    """
    resp = client.get(ME, headers=headers)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["user"]["id"])


def _body(**overrides) -> dict:  # noqa: ANN003
    body = {"user_input": VALID_INPUT, "question_count": 5, "difficulty": "mixed"}
    body.update(overrides)
    return body


# -----------------------------------------------------------------------------
# 一、作用域被带进取材请求
# -----------------------------------------------------------------------------
def test_kb_id_is_carried_into_the_search_request(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001 - 后台落库指向测试库
    auth_headers: dict,
    spy_provider: SpyProvider,
    created_tasks: list[dict],  # noqa: ARG001
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
) -> None:
    """带 `kb_id` ⇒ `SearchRequest.kb` 是 `KbScope(当前用户, 这个库)`。"""
    kb_id = _make_base(db_client, auth_headers)
    user_id = _me_id(db_client, auth_headers)

    resp = db_client.post(GENERATE_URL, json=_body(kb_id=kb_id), headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
    assert len(spy_provider.requests) == 1, "带库的请求必须真的走一次取材"
    assert spy_provider.requests[0].kb == KbScope(user_id=user_id, kb_id=kb_id)


def test_kb_scope_user_id_comes_from_the_token_not_the_body(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    other_auth_headers: dict,
    spy_provider: SpyProvider,
    created_tasks: list[dict],  # noqa: ARG001
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
) -> None:
    """请求体里就算带了 `user_id` 也不作数 —— 作用域里的用户来自登录态。

    这条挡的是「客户端指定自己是谁」这个最朴素的越权手法。
    `extra="ignore"` 会让多出来的字段被丢掉，所以这里同时验了
    「多余字段不会污染模型」与「user_id 只可能来自 token」。
    """
    kb_id = _make_base(db_client, auth_headers)
    owner_id = _me_id(db_client, auth_headers)
    other_id = _me_id(db_client, other_auth_headers)

    resp = db_client.post(
        GENERATE_URL,
        json=_body(kb_id=kb_id, user_id=other_id),
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert spy_provider.requests[0].kb == KbScope(user_id=owner_id, kb_id=kb_id)
    assert spy_provider.requests[0].kb.user_id != other_id


# -----------------------------------------------------------------------------
# 二、归属校验在建任务之前
# -----------------------------------------------------------------------------
def test_missing_base_returns_4005_and_creates_no_task(
    db_client: TestClient,
    auth_headers: dict,
    spy_provider: SpyProvider,
    created_tasks: list[dict],
) -> None:
    """库不存在 ⇒ 4005，且**一个任务都没建**、**一次取材都没发生**。"""
    resp = db_client.post(GENERATE_URL, json=_body(kb_id=999_999), headers=auth_headers)

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND == 4005
    assert created_tasks == [], "校验必须发生在建任务之前（design D13）"
    assert spy_provider.requests == [], "更不该走到取材"


def test_other_users_base_returns_4005_and_creates_no_task(
    db_client: TestClient,
    auth_headers: dict,
    other_auth_headers: dict,
    spy_provider: SpyProvider,
    created_tasks: list[dict],
) -> None:
    """别人的库与不存在的库返回**同一个** 4005 —— 不为越权单独给信号。

    `created_tasks` 这条断言是重点：越权如果建了任务，用户会拿到一个
    `task_id`，然后看着进度条跑到一半失败。
    """
    foreign = _make_base(db_client, other_auth_headers, "别人的库")

    resp = db_client.post(GENERATE_URL, json=_body(kb_id=foreign), headers=auth_headers)

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND
    assert created_tasks == []
    assert spy_provider.requests == []


def test_unauthenticated_request_with_kb_id_is_rejected(
    db_client: TestClient,
    auth_headers: dict,
    created_tasks: list[dict],
) -> None:
    """未登录照样 401 —— 带了 kb_id 不改变鉴权要求。"""
    kb_id = _make_base(db_client, auth_headers)

    resp = db_client.post(GENERATE_URL, json=_body(kb_id=kb_id))

    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED
    assert created_tasks == []


# -----------------------------------------------------------------------------
# 三、不带 kb_id ⇒ 与今天逐位一致
# -----------------------------------------------------------------------------
def test_without_kb_id_the_search_request_is_unchanged(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    spy_provider: SpyProvider,
    settings: Settings,
    created_tasks: list[dict],  # noqa: ARG001
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
) -> None:
    """不带 `kb_id` ⇒ 取材请求**逐位等于**今天会构造出来的那一份。

    `SearchRequest` 是 frozen dataclass，所以这一条能直接 `==`。
    比逐个字段断言更强：以后谁给请求加了新字段却忘了给默认值，
    或者悄悄改了 `max_results` 的来源，这里都会响。
    """
    resp = db_client.post(GENERATE_URL, json=_body(), headers=auth_headers)

    assert resp.status_code == 200, resp.text
    expected = SearchRequest(
        query=validate_input(VALID_INPUT),
        urls=(),
        use_search=True,
        max_results=settings.search_max_results,
    )
    assert spy_provider.requests == [expected]
    assert spy_provider.requests[0].kb is None


def test_without_kb_id_the_response_shape_is_unchanged(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    spy_provider: SpyProvider,  # noqa: ARG001
    created_tasks: list[dict],  # noqa: ARG001
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
) -> None:
    """响应体一个字段都不多 —— 前端不必为「有没有带库」写两套解析。"""
    resp = db_client.post(GENERATE_URL, json=_body(), headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert set(resp.json()["data"]) == {
        "task_id",
        "status",
        "poll_interval_ms",
        "estimated_seconds",
    }


def test_the_first_step_is_named_after_the_base_when_one_is_given(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    spy_provider: SpyProvider,  # noqa: ARG001
    created_tasks: list[dict],
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
) -> None:
    """建任务时那三步状态卡的第一步要说「检索你的知识库」，不是「理解你的输入」。

    它归 `quiz_service._initial_steps()` 管，而那里只看得到 `SearchRequest` ——
    所以这条同时证明「kb 作用域在 `create_task` 之前就已经装配好了」。
    """
    kb_id = _make_base(db_client, auth_headers)

    db_client.post(GENERATE_URL, json=_body(kb_id=kb_id), headers=auth_headers)

    steps = created_tasks[0]["kwargs"]["steps"]
    assert steps[0].name == "检索你的知识库", steps[0].name


# -----------------------------------------------------------------------------
# 四、非法 kb_id 的形态
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_kb_id_is_rejected(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    spy_provider: SpyProvider,  # noqa: ARG001
    created_tasks: list[dict],
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
    bad: int,
) -> None:
    """`kb_id` 有 `ge=1` 的下限 ⇒ 4000（参数校验失败），不落到默认库上。

    ⚠️ 静默当成 `None` 是最糟的处理：用户以为自己选了某个库，
    结果出题用的是默认库 —— 界面上完全看不出来。
    """
    resp = db_client.post(GENERATE_URL, json=_body(kb_id=bad), headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM == 4000
    assert created_tasks == []


def test_non_numeric_kb_id_is_rejected(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    spy_provider: SpyProvider,  # noqa: ARG001
    created_tasks: list[dict],
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
) -> None:
    """非数字同样 4000，理由同上：不许退化成「没传」。"""
    resp = db_client.post(GENERATE_URL, json=_body(kb_id="abc"), headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM
    assert created_tasks == []


def test_kb_id_is_not_silently_dropped_when_the_feature_is_off(
    db_client: TestClient,
    db_scope,  # noqa: ANN001, ARG001
    auth_headers: dict,
    spy_provider: SpyProvider,
    created_tasks: list[dict],  # noqa: ARG001
    inline_submit,  # noqa: ANN001, ARG001
    patch_generate,  # noqa: ANN001, ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """知识库功能关着时，带 `kb_id` 的请求仍走同一条归属校验，且不会被当成「没带」。

    关开关**不**让这个字段变得可以忽略：库里那条记录不会因为开关关掉就消失，
    而「忽略它、跑去默认库」正是这条用例要挡的。这里库是真的存在的，
    所以期望是「照常通过」而不是 4005 —— 真正要钉的是**不许静默丢弃**：
    作用域里仍然带着那个库（否则出题会悄悄用别处的资料）。

    （D18 说明为什么知识库路由无条件注册、开关只影响入口可见性。）
    """
    kb_id = _make_base(db_client, auth_headers)
    user_id = _me_id(db_client, auth_headers)

    from app.core.config import get_settings

    monkeypatch.setenv("KNOWLEDGE_BASE_ENABLED", "false")
    get_settings.cache_clear()
    try:
        resp = db_client.post(GENERATE_URL, json=_body(kb_id=kb_id), headers=auth_headers)
    finally:
        monkeypatch.delenv("KNOWLEDGE_BASE_ENABLED", raising=False)
        get_settings.cache_clear()

    assert resp.status_code == 200, resp.text
    assert spy_provider.requests[0].kb == KbScope(user_id=user_id, kb_id=kb_id)
