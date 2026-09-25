"""pytest 公共夹具。

原则（见 docs/MVP开发计划.md §10）：
- **绝不允许测试发出真实 LLM 请求**，因此所有 LLM 交互都必须能被 mock。
- 测试环境变量通过 monkeypatch 注入，优先级高于仓库根目录的 `.env`，
  保证测试结果不受开发者本地配置影响。
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# 测试基线环境：在导入 app 之前就位
TEST_ENV = {
    "APP_ENV": "dev",
    "APP_VERSION": "0.1.0-test",
    "DEEPSEEK_API_KEY": "sk-test-key-not-real",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "deepseek-flash",
    "DEEPSEEK_THINKING": "false",
    "KNOWLEDGE_SEARCH_ENABLED": "false",
    # 私有知识库同样钉死为**关**。不钉的话，本机 `.env` 里那句
    # `KNOWLEDGE_BASE_ENABLED=true`（做端到端验收时加的）会漏进测试，
    # 于是「默认关 ⇒ 前端看不见入口」「开关关 ⇒ 不绑工具」这些用例
    # 在开发者机器上全都不成立 —— 这是典型的「只在本机红/绿」。
    # 需要打开的模块用 `kb_env` 夹具显式打开（见本文件末的 KB 夹具组）。
    "KNOWLEDGE_BASE_ENABLED": "false",
    "LOG_LEVEL": "WARNING",
    "QUIZ_TASK_TTL_SECONDS": "600",
    # ---------- 用户系统 ----------
    # 固定测试用密钥（≥32 字符），保证测试不依赖开发者本地 .env
    "JWT_SECRET": "unit-test-secret-0123456789abcdef0123456789abcdef",
    "JWT_EXPIRE_HOURS": "168",
    "APP_TIMEZONE": "Asia/Shanghai",
    # 调试登录通道在测试里必须开启，否则 H5/本机链路无法验证
    "DEV_LOGIN_ENABLED": "true",
    "WECHAT_APPID": "wx_unittest_appid",
    "WECHAT_APP_SECRET": "unittest_app_secret",
    # **关键**：测试环境一律走 mock 身份 Provider。
    # 若为 real，任何走登录接口的用例都会真的去请求微信服务器。
    "WECHAT_PROVIDER": "mock",
    "AVATAR_MAX_BYTES": str(2 * 1024 * 1024),
    # 限流阈值调小，便于在一个用例里验证 4290
    "LOGIN_RATE_LIMIT": "10",
    "LOGIN_RATE_WINDOW_SECONDS": "60",
}


@pytest.fixture(scope="session", autouse=True)
def _baseline_env() -> Iterator[None]:
    """会话级基线环境变量，避免读到开发者本地的 .env 造成测试不确定。"""
    original = {k: os.environ.get(k) for k in TEST_ENV}
    os.environ.update(TEST_ENV)
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def settings(_baseline_env: None):  # noqa: ARG001
    """获取配置单例，并清掉 lru_cache 以确保读到的是当前环境变量。"""
    from app.core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_task_store() -> Iterator[None]:
    """任务表是**进程内全局状态**，用例之间必须隔离。

    放在 conftest 里而不是各测试文件里，是因为任何走接口的用例都可能悄悄创建任务，
    漏掉一处就会出现「只在全量跑时失败」的串味问题 —— 那种问题最难查。
    """
    from app.services import task_service

    task_service.reset_store()
    yield
    task_service.reset_store()


@pytest.fixture
def inline_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """把异步任务执行替换成同步，让轮询类用例不依赖线程调度。

    只有明确验证「真实线程池路径」的用例才不用它。
    """
    from app.services import quiz_service

    monkeypatch.setattr(quiz_service, "_submit", lambda fn: fn())


@pytest.fixture
def inline_report_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """报告链的同步执行版（理由同 `inline_submit`）。

    单独一个夹具而不是复用 `inline_submit`：两者替换的是**不同的执行器**
    （报告链刻意用独立的池，不与出题抢槽位）。合并成一个夹具会让人以为
    替换了出题器就等于替换了报告器 —— 那样报告用例会变成「真的起线程」，
    于是轮询断言时好时坏。
    """
    from app.services import report_service

    monkeypatch.setattr(report_service, "_submit", lambda fn: fn())


@pytest.fixture
def client(settings) -> Iterator[TestClient]:  # noqa: ARG001
    """FastAPI 测试客户端。"""
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


# -----------------------------------------------------------------------------
# 固定样本：一份「3 单选 + 1 多选 + 1 判断」的合法题库
# -----------------------------------------------------------------------------
# 取这个组合有两个原因：
#   1. 它正是原型「副本确认页」的题型构成（3 单选 · 1 多选 · 1 判断）
#   2. 它同时覆盖三种题型的校验分支，且满分恰好 200 XP
#      （40×3 + 60 + 20），与原型通关结算的数字一致
SAMPLE_QUESTIONS: list[dict] = [
    {
        "id": "q1",
        "type": "single",
        "stem": "RAG 的核心思路是什么？",
        "options": [
            {"key": "A", "text": "先检索相关资料，再把资料交给模型生成回答"},
            {"key": "B", "text": "把模型参数调大以获得更多知识"},
            {"key": "C", "text": "只用关键词匹配返回链接列表"},
            {"key": "D", "text": "把全部训练数据重新训练一遍"},
        ],
        "answer": ["A"],
        "explanation": "RAG（检索增强生成）先检索外部资料，再让模型基于资料作答。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "easy",
    },
    {
        "id": "q2",
        "type": "single",
        "stem": "向量检索相比关键词检索，最主要的优势是？",
        "options": [
            {"key": "A", "text": "检索速度一定更快"},
            {"key": "B", "text": "不需要建立索引"},
            {"key": "C", "text": "能按语义相似度召回，而不只是字面匹配"},
            {"key": "D", "text": "结果永远比关键词检索更准"},
        ],
        "answer": ["C"],
        "explanation": "向量检索把文本映射到语义空间，可以召回字面不同但含义相近的内容。",
        "knowledge_point": "向量检索",
        "difficulty": "medium",
    },
    {
        "id": "q3",
        "type": "single",
        "stem": "RAG 与搜索引擎最本质的差别在于？",
        "options": [
            {"key": "A", "text": "RAG 的数据量更大"},
            {"key": "B", "text": "RAG 会基于检索结果组织成连贯回答，搜索引擎返回的是候选链接"},
            {"key": "C", "text": "RAG 只支持中文"},
            {"key": "D", "text": "搜索引擎不能处理长文本"},
        ],
        "answer": ["B"],
        "explanation": "搜索引擎给链接，用户自己读；RAG 把召回内容转写成直接可用的回答。",
        "knowledge_point": "与搜索引擎的边界",
        "difficulty": "medium",
    },
    {
        "id": "q4",
        "type": "multiple",
        "stem": "下面哪些属于 RAG 的典型收益？（多选）",
        "options": [
            {"key": "A", "text": "回答可以引用最新的外部资料"},
            {"key": "B", "text": "可以彻底消除模型幻觉"},
            {"key": "C", "text": "知识可以更新而无需重新训练模型"},
            {"key": "D", "text": "让模型参数量变小"},
        ],
        "answer": ["A", "C"],
        "explanation": "RAG 能引入新资料、免训练更新知识；但它只能降低幻觉，不能彻底消除。",
        "knowledge_point": "应用场景",
        "difficulty": "hard",
    },
    {
        "id": "q5",
        "type": "judge",
        "stem": "RAG 系统必须先完成检索，才能生成最终答案。",
        "options": [
            {"key": "T", "text": "正确"},
            {"key": "F", "text": "错误"},
        ],
        "answer": ["T"],
        "explanation": "RAG 的「检索—增强—生成」顺序是固定的，检索结果就是生成阶段的输入。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "easy",
    },
]


@pytest.fixture
def sample_questions() -> list[dict]:
    """一份合法题库的题目列表（深拷贝，避免测试间互相污染）。"""
    import copy

    return copy.deepcopy(SAMPLE_QUESTIONS)


@pytest.fixture
def sample_quiz_payload(sample_questions: list[dict]) -> dict:
    """可直接喂给 `Quiz.model_validate()` 的完整题库字典。"""
    return {
        "quiz_id": "quiz_test",
        "title": "RAG 入门闯关",
        "summary": "围绕 RAG 基础概念与应用场景生成的题库",
        "source_type": "text",
        "user_input": "我想学习什么是 RAG，以及它和传统搜索有什么区别",
        "knowledge_points": None,  # 交给 Quiz 从题目派生
        "questions": sample_questions,
    }


@pytest.fixture
def sample_draft_payload(sample_questions: list[dict]) -> dict:
    """LLM 结构化输出的形状（外层的 quiz_id / user_input / source_type 由服务端补）。"""
    return {
        "title": "RAG 入门闯关",
        "summary": "围绕 RAG 基础概念与应用场景生成的题库",
        "knowledge_points": None,
        "questions": sample_questions,
    }


# -----------------------------------------------------------------------------
# 数据库夹具（用户系统）
# -----------------------------------------------------------------------------
# 设计原则：
# 1. **绝不碰业务库**。所有用例走 `TEST_DATABASE_URL`，未配置时整体 skip
#    而不是回退到业务库 —— 回退会让 pytest 的清表操作抹掉真实数据。
# 2. 引擎在**会话级**建一次（连接池复用），表用 `create_all` 幂等确保存在
#    （表已由 backend/sql/01_schema.sql 建好，这里是兜底，不是建表主路径）。
# 3. 每个用例开始前 TRUNCATE 全部 10 张表，保证用例之间绝对隔离。
#    用 `SET FOREIGN_KEY_CHECKS=0` 绕开外键顺序问题；走 AUTOCOMMIT 连接
#    是因为 MySQL 的 TRUNCATE 会隐式提交，混在显式事务里会破坏事务边界。

#: 需要清空的表在 `app.db.tables.ALL_TABLES` 里定义，这里只按名字取用
def _truncate_all(engine) -> None:  # noqa: ANN001 - Engine
    """清空全部业务表并重置自增（AUTO_INCREMENT = 1）。"""
    from sqlalchemy import text

    from app.db.tables import ALL_TABLES

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for table in ALL_TABLES:
                # 表名来自代码常量（非用户输入），不存在注入面
                conn.execute(text(f"TRUNCATE TABLE `{table.__tablename__}`"))
        finally:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture(scope="session")
def test_engine():  # noqa: ANN201 - Iterator[Engine]
    """测试库引擎（会话级）。未配置 `TEST_DATABASE_URL` 时跳过相关用例。"""
    from sqlalchemy import create_engine, event

    from app.core.config import Settings
    from app.db import tables  # noqa: F401  导入即注册全部表元数据
    from app.db.base import Base

    url = Settings().effective_test_database_url
    if not url:
        pytest.skip("未配置 TEST_DATABASE_URL，跳过需要数据库的用例")

    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)

    @event.listens_for(engine, "connect")
    def _force_utc(dbapi_connection, _record) -> None:  # noqa: ANN001
        """与 `app/db/session.py` 一致：连接上强制 UTC。

        本机 MySQL 的 `@@session.time_zone` 是 SYSTEM（北京），不显式设置的话
        `CURRENT_TIMESTAMP` 会写北京时间，与「库里存 UTC」的约定冲突。
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()

    with engine.begin() as conn:
        Base.metadata.create_all(conn)

    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_login_limiter() -> Iterator[None]:
    """登录限流器是**进程内全局状态**，必须逐用例清零。

    否则「先跑了 10 次登录的用例」会让后面的用例莫名其妙拿到 4290 ——
    这种只在全量跑时出现的失败最难定位。
    """
    from app.core import ratelimit

    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


@pytest.fixture
def tmp_uploads(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """把上传根目录指到临时目录。

    为什么所有接口用例都要带它：默认路径是 `backend/uploads`，
    测试会**真的写文件**进去，跑几次之后仓库里就多出一堆垃圾头像。
    同时它也让「静态目录挂在哪」这件事在测试里可验证。
    """
    from app.core.config import get_settings

    target = tmp_path / "uploads"
    monkeypatch.setenv("UPLOADS_DIR", str(target))
    get_settings.cache_clear()
    yield target
    get_settings.cache_clear()


@pytest.fixture
def db_engine(test_engine):
    """每个用例一份干净的库。"""
    _truncate_all(test_engine)
    return test_engine


@pytest.fixture
def db_session(db_engine):  # noqa: ANN201 - Iterator[Session]
    """直连测试库的会话（用于不经接口的 service 层单测）。

    ⚠️ **「读 → 接口写 → 再读」会读到旧快照**：MySQL 默认隔离级别是
    REPEATABLE READ，会话的第一次读就定下了整个事务的快照。如果用例先查一次，
    再让接口（另一个连接）写库，然后又用**同一个**会话查 —— 第二次看到的
    仍是第一次的快照，`expire_all()` 也救不了（它只让对象过期，不换快照）。
    实测症状是「断言到一个明明是刚写进去的旧值」。

    要在写之后重新读，必须**结束当前事务**再查：

        db_session.rollback()          # 结束只读事务 → 下一次查询拿新快照
        row = db_session.get(Row, pk)

    另一种写法是让用例只查一次、或在查询前不碰会话。这里不把隔离级别改成
    READ COMMITTED，是因为生产用的是默认级别 —— 测试应当跑在与线上同一套
    语义下，代价是这个坑必须写在能被搜到的地方。
    """
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_scope(db_engine, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """把**后台线程里的落库会话**指向测试库。

    出题是异步任务，落库发生在后台线程里 —— 那里没有请求级会话，只能自己开一个
    （`quiz_service._open_session`，默认是 `session_scope`）。而 `db_client`
    覆盖的是 `get_db` 依赖，**管不到后台路径**。不替换的话，接口测试会真的往
    业务库里写卷轴。

    这正是本项目反复强调的那条约定：服务层一律显式接收 session，
    只有后台线程这一个例外，所以它必须有一个显式的替换点。

    ⚠️ **每新增一个会在后台线程里写库的服务，都必须加进下面的 `modules`。**
    漏掉的症状很隐蔽：接口测试照样通过（它走 `get_db`），
    但会**悄悄往业务库里写数据** —— 下一次有人跑开发环境时才会发现多了一堆脏数据。
    """
    from contextlib import contextmanager

    from sqlalchemy.orm import sessionmaker

    from app.services import kb_service, quiz_service, report_service

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)

    @contextmanager
    def scope():  # noqa: ANN202
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    for module in (quiz_service, report_service, kb_service):
        monkeypatch.setattr(module, "_open_session", scope)
    return scope


@pytest.fixture
def db_client(db_engine, tmp_uploads):  # noqa: ANN201, ARG001 - Iterator[TestClient]
    """把 `get_db` 依赖指向测试库的接口客户端。

    为什么重写依赖而不是改配置：`get_db` 是**唯一**的请求级会话入口，
    覆盖它就等于「所有请求都写测试库」，比改全局配置更不容易漏。
    后台线程里的 `session_scope()` 不在此列 —— 所以服务层一律**显式接收
    session**，不用全局工厂，这样后台路径在测试里也能被注入。
    """
    from sqlalchemy.orm import sessionmaker

    from app.db.session import get_db
    from app.main import create_app

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    app = create_app()

    def _override_get_db():  # noqa: ANN202
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def dev_login(db_client: TestClient):  # noqa: ANN201
    """走调试通道登录，返回 `{token, expires_in, user}`。"""

    def _login(device_id: str = "pytest-device") -> dict:
        resp = db_client.post("/api/v1/auth/dev", json={"device_id": device_id})
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    return _login


@pytest.fixture
def auth_headers(dev_login) -> dict[str, str]:  # noqa: ANN001
    """默认用户的鉴权头。"""
    return {"Authorization": f"Bearer {dev_login()['token']}"}


@pytest.fixture
def other_auth_headers(dev_login) -> dict[str, str]:  # noqa: ANN001
    """**另一个**用户的鉴权头，专供越权用例。"""
    return {"Authorization": f"Bearer {dev_login('pytest-device-2')['token']}"}


# -----------------------------------------------------------------------------
# 图片样本（头像上传用例）
# -----------------------------------------------------------------------------
#: 最小的合法图片字节：只保留魔数 + 少量数据，足够让「按魔数判类型」通过。
#: 不能用任意字节 —— 那正是要拦的「伪造扩展名」输入。
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x78\x9c\x63\x00\x01\x00\x00\x05\x00"
    b"\x01\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
TINY_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xd9"
TINY_WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00" + b"\x00" * 24


@pytest.fixture
def tiny_png() -> bytes:
    return TINY_PNG


@pytest.fixture
def tiny_jpeg() -> bytes:
    return TINY_JPEG


@pytest.fixture
def tiny_webp() -> bytes:
    return TINY_WEBP


# -----------------------------------------------------------------------------
# 私有知识库夹具
# -----------------------------------------------------------------------------
# 为什么这一组**不 autouse**：它们会把 `KNOWLEDGE_BASE_ENABLED` 打开、
# 把上传目录与向量库目录换掉，而那会改变「钉默认值」类用例的前提
# （`test_config_search.py` 就是钉默认关闭的）。所以由各 KB 测试模块
# 自己声明一条 autouse 夹具去请求 `kb_harness`（见 `test_kb_service.py`）——
# 「这个文件里每条用例都在 KB 环境里跑」这件事因此是**显式**的。
#
# 这一组也是本次唯一把「后端线程 + 外部服务」两件事同时替掉的地方：
#   - `kb_session_scope` 替掉后端线程的会话（同 `db_scope` 之于出题链）
#   - `kb_fake_embeddings` 替掉向量化（同「LLM 一律 mock」那条红线）
# 两者都做成可注入的模块级接缝（见 `kb_service` 模块头）。


@pytest.fixture
def kb_env(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """开启知识库并把两个目录都指到临时目录。

    返回一个「改配置再取一次」的小工厂：用例里要改上限（比如把单文件上限压到
    100 字节来验超限）时不必各自写一遍清缓存。
    """

    def _configure(**env: object):  # noqa: ANN202
        from app.core.config import get_settings

        baseline = {
            "KNOWLEDGE_BASE_ENABLED": "true",
            # 假 key：`build_embeddings` 只检查它非空，不会用它发请求
            "DASHSCOPE_API_KEY": "sk-fake-for-tests",
            "UPLOADS_DIR": str(tmp_path / "uploads"),
            "VECTORSTORE_DIR": str(tmp_path / "vectorstore"),
        }
        baseline.update({key: str(value) for key, value in env.items()})
        for key, value in baseline.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield _configure
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def kb_fake_embeddings(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """把向量化换成**确定性、零网络**的替身。

    存在的理由是那条红线：「绝不允许测试发出真实 LLM 请求」。知识库链路上唯一的
    外部调用就是向量化，换掉它之后，分块 / 存储 / 解析状态机可以真跑 ——
    而它们才是本能力真正要验的逻辑。
    """
    from app.services import kb_service
    from tests.helpers import BagEmbeddings

    fake = BagEmbeddings()
    monkeypatch.setattr(kb_service, "_build_embeddings", lambda _settings: fake)
    return fake


@pytest.fixture
def kb_session_scope(db_engine, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """把**解析线程里的落库会话**指向测试库。

    同 `db_scope` 的理由：后台线程没有请求级会话，只能自己开一个
    （`kb_service._open_session`，默认是 `session_scope`），而它按 `DATABASE_URL`
    建引擎 —— 不替换的话，任何一次「上传并解析」都会**真的往业务库写几行**，
    而接口测试照样通过（它走 `get_db`）。
    """
    from contextlib import contextmanager

    from sqlalchemy.orm import sessionmaker

    from app.services import kb_service

    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)

    @contextmanager
    def scope():  # noqa: ANN202
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(kb_service, "_open_session", scope)
    return scope


@pytest.fixture
def kb_inline_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """解析在**本线程**执行（确定性；同 `inline_submit` 之于出题链）。"""
    from app.services import kb_service

    monkeypatch.setattr(kb_service, "_submit", lambda fn, *, settings: (fn(), True)[1])


@pytest.fixture
def kb_harness(kb_env, kb_fake_embeddings, kb_session_scope):  # noqa: ANN001, ANN201, ARG001
    """一次凑齐知识库用例需要的那套替身与环境，并保证收尾。

    各 KB 测试模块用一条 autouse 夹具请求它：

        @pytest.fixture(autouse=True)
        def _kb(kb_harness):
            return kb_harness

    解析池是**进程内全局状态**（`kb_tasks`），所以收尾统一在这里做 ——
    `test_upload_returns_before_parse` 这类用例会真的留下一个后台线程。
    """
    from app.services import kb_service

    yield kb_env()
    kb_service.shutdown(wait=True)

