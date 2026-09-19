"""ORM 映射与真实库的一致性守卫。

表结构的**权威来源**是 `backend/sql/01_schema.sql`（表已由它建好），
`app/db/tables.py` 只是让代码能读写它。两者一旦漂移，症状会非常隐蔽：
例如少映射一列 → 写入时静默用默认值；多映射一列 → 运行时才报
`Unknown column`。所以在测试里做一次逐列比对，比任何注释都可靠。
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.db.tables import ALL_TABLES

EXPECTED_TABLES = {
    "users",
    "user_settings",
    "quizzes",
    "questions",
    "attempts",
    "answers",
    "reports",
    "wrong_questions",
    "user_knowledge_stats",
    "user_badges",
}

#: 方案设计 §9.1 实测的外键数量（13），Phase D 新增 1 个：
#: `questions.fk_questions_origin` —— 复习关卡的副本指回原错题（见
#: `sql/02_questions_origin.sql`）。
EXPECTED_FK_COUNT = 14


def test_ten_tables_defined() -> None:
    assert len(ALL_TABLES) == 10
    assert {t.__tablename__ for t in ALL_TABLES} == EXPECTED_TABLES


def test_all_tables_exist_in_test_db(test_engine) -> None:  # noqa: ANN001
    existing = set(inspect(test_engine).get_table_names())

    assert EXPECTED_TABLES <= existing, sorted(EXPECTED_TABLES - existing)


def test_columns_match_database(test_engine) -> None:  # noqa: ANN001
    inspector = inspect(test_engine)
    mismatches: list[str] = []

    for table in ALL_TABLES:
        name = table.__tablename__
        db_columns = {c["name"] for c in inspector.get_columns(name)}
        orm_columns = {c.name for c in table.__table__.columns}

        if db_columns != orm_columns:
            mismatches.append(
                f"{name}: 库中多={sorted(db_columns - orm_columns)} "
                f"ORM中多={sorted(orm_columns - db_columns)}"
            )

    assert not mismatches, "\n".join(mismatches)


def test_column_order_matches_database(test_engine) -> None:  # noqa: ANN001
    """顺序一致能让人一眼对照 DDL；不一致不致命，但说明映射是手抄的。"""
    inspector = inspect(test_engine)

    for table in ALL_TABLES:
        name = table.__tablename__
        db_order = [c["name"] for c in inspector.get_columns(name)]
        orm_order = [c.name for c in table.__table__.columns]
        assert db_order == orm_order, name


def test_no_extra_tables_are_defined(test_engine) -> None:  # noqa: ANN001
    """这条不是「防止库里有别的表」，而是防止 ORM 里混进本轮范围外的表。"""
    from app.db.base import Base

    assert {t.name for t in Base.metadata.sorted_tables} == EXPECTED_TABLES


def test_unique_constraints_match_database(test_engine) -> None:  # noqa: ANN001
    """唯一约束是「幂等解锁勋章」「同一资料不重复建卷轴」等规则的最后一道防线。"""
    inspector = inspect(test_engine)

    for table in ALL_TABLES:
        name = table.__tablename__
        db_unique = {
            tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints(name)
        }
        orm_unique = {
            tuple(sorted(col.name for col in constraint.columns))
            for constraint in table.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert orm_unique <= db_unique, f"{name}: ORM 有库里没有的唯一约束 {orm_unique - db_unique}"


def test_foreign_key_count(test_engine) -> None:  # noqa: ANN001
    inspector = inspect(test_engine)
    total = sum(len(inspector.get_foreign_keys(t.__tablename__)) for t in ALL_TABLES)

    assert total == EXPECTED_FK_COUNT, f"外键数量 {total} ≠ 预期的 {EXPECTED_FK_COUNT}"


def test_indexes_referenced_by_queries_exist(test_engine) -> None:  # noqa: ANN001
    """列出本轮会命中的索引，确认它们真的建出来了（删掉会让列表页随数据量变慢）。"""
    inspector = inspect(test_engine)
    expected = {
        "users": {"uk_users_openid"},
        "quizzes": {"idx_quizzes_user_created"},
        "attempts": {"idx_attempts_user_finished", "idx_attempts_quiz"},
        "wrong_questions": {"idx_wrong_questions_user_due"},
        "user_knowledge_stats": {"idx_user_knowledge_stats_user_lit"},
        "reports": {"idx_reports_user_status"},
    }

    for table, names in expected.items():
        actual = {idx["name"] for idx in inspector.get_indexes(table)}
        assert names <= actual, f"{table} 缺少索引 {names - actual}"


def test_datetime_precision_is_millis(test_engine) -> None:  # noqa: ANN001
    """`DATETIME(3)` 是本项目的统一口径；精度变了会让「写进去=读出来」的断言失效。

    直接读 `information_schema` 的 `DATETIME_PRECISION` 列，而不是调用
    `DATETIME_PRECISION()` 函数 —— 后者在 MySQL 里解析成了当前库的自定义函数，
    报 `FUNCTION <db>.DATETIME_PRECISION does not exist`。
    """
    with test_engine.connect() as conn:
        precision = conn.execute(
            text(
                "SELECT DATETIME_PRECISION FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'users' "
                "AND column_name = 'created_at'"
            )
        ).scalar()

    assert precision == 3, f"users.created_at 精度应为 3（毫秒），实际 {precision}"


def test_collation_is_0900_ai_ci(test_engine) -> None:  # noqa: ANN001
    """排序规则不统一会在跨表 JOIN 时报 `Illegal mix of collations`（方案 §2.2 D1）。"""
    with test_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT table_collation FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name IN "
                "('users','attempts','answers','quizzes')"
            )
        ).scalars().all()

    assert rows == ["utf8mb4_0900_ai_ci"]


def test_engine_is_innodb(test_engine) -> None:  # noqa: ANN001
    with test_engine.connect() as conn:
        engines = conn.execute(
            text(
                "SELECT DISTINCT engine FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
        ).scalars().all()

    assert engines == ["InnoDB"]


def test_json_default_for_reminder_days(test_engine) -> None:  # noqa: ANN001
    """DDL 里的 JSON 默认值必须真的生效，否则新建设置行会缺字段。"""
    with test_engine.connect() as conn:
        default = conn.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'user_settings' "
                "AND column_name = 'reminder_days'"
            )
        ).scalar()

    assert default is not None and "1" in str(default)


def test_session_is_clean_between_tests(db_session) -> None:  # noqa: ANN001
    """确认清表真的生效：如果这条失败，说明用例之间会互相污染。"""
    from app.db.tables import User

    assert db_session.query(User).count() == 0


@pytest.mark.parametrize(
    "table_name",
    ["users", "user_settings", "quizzes", "questions", "attempts", "answers", "reports"],
)
def test_created_at_and_updated_at_present(test_engine, table_name: str) -> None:  # noqa: ANN001
    """公共列约定（方案 §5.0）：每表都带 `created_at` / `updated_at`。"""
    columns = {c["name"] for c in inspect(test_engine).get_columns(table_name)}

    assert {"created_at", "updated_at"} <= columns
