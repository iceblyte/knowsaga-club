"""引擎与会话。

## 三个刻意的设计

**1. 连接上显式 `SET time_zone = '+00:00'`。**
本机 MySQL 的 `@@session.time_zone` 实测是 `SYSTEM`（即服务器本地时间，北京）。
约定是「数据库统一存 UTC」，如果不显式设置，所有由 `CURRENT_TIMESTAMP` 生成的
默认值都会写成北京时间 —— 于是「今天」「连续天数」「错题到期」在晚上 8 点之后
会整体偏移一天。这类错误不会报错，只会让统计悄悄算错。

**2. 引擎惰性创建且可按 URL 缓存。**
测试要指向 `TEST_DATABASE_URL`，而配置在测试里是会被 monkeypatch 改的。
把「当前引擎对应哪个 URL」记下来，URL 变了就重建，避免出现
「测试跑到一半发现自己在写业务库」这种最坏情况。

**3. 事件监听器在引擎上注册，不在全局。**
`listen(Engine, "connect")` 会影响所有引擎；这里用 `event.listens_for(engine, "connect")`
只作用于这一个实例。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

#: 业务库引擎与它当前绑定的 URL
_engine: Engine | None = None
_engine_url: str | None = None

#: 当前 sessionmaker（跟随引擎一起重建）
_session_factory: sessionmaker[Session] | None = None


def _create_engine(url: str) -> Engine:
    """按统一参数建引擎，并挂上 UTC 时区钩子。"""
    engine = create_engine(
        url,
        # 连接被服务端回收后，池里的旧连接第一次用会报错；pre_ping 先探活再交付
        pool_pre_ping=True,
        # 小于服务端 wait_timeout（默认 28800s），避免拿到已被回收的连接
        pool_recycle=1800,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _force_utc(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        """每个新连接都强制 UTC，让 DATETIME 的语义与约定一致。"""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()

    return engine


def get_engine(url: str | None = None, *, settings: Settings | None = None) -> Engine:
    """取当前引擎；URL 变化时自动重建。

    Raises:
        RuntimeError: 未配置连接串。宁可显式失败，也不要连到一个猜出来的库。
    """
    global _engine, _engine_url, _session_factory

    s = settings or get_settings()
    resolved = (url or s.database_url or "").strip()
    if not resolved:
        raise RuntimeError(
            "未配置 DATABASE_URL：请在仓库根目录的 .env 中填写 MySQL 连接串"
        )

    if _engine is None or _engine_url != resolved:
        if _engine is not None:
            _engine.dispose()
        _engine = _create_engine(resolved)
        _engine_url = resolved
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)

    return _engine


def get_session_factory(*, settings: Settings | None = None) -> sessionmaker[Session]:
    """取当前会话工厂（顺带保证引擎已就绪）。"""
    get_engine(settings=settings)
    assert _session_factory is not None  # get_engine 已保证
    return _session_factory


def reset_engine() -> None:
    """丢弃当前引擎（测试用；切换库或收尾时必须调用）。"""
    global _engine, _engine_url, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None
    _session_factory = None


@contextmanager
def session_scope(*, settings: Settings | None = None) -> Iterator[Session]:
    """一个事务作用域的会话。

    **提交与回滚都由它负责**，调用方只管写业务：成功自动 commit，
    抛异常自动 rollback，最后一定 close。后台线程里也用它 ——
    这正是选同步驱动的好处，不需要任何事件循环桥接。
    """
    session = get_session_factory(settings=settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个会话。

    路由函数是同步 `def`，FastAPI 会把它丢进线程池执行，所以这里用同步生成器即可。
    需要显式事务的路由可以用 `Depends(get_db)` 后在服务层自己 commit；
    只读路由不必 commit（close 时会自动 rollback 掉空事务）。
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
