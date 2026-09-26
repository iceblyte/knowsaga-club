"""ORM 映射与真实库的一致性守卫。

表结构的**权威来源**是 `backend/sql/` 下的 DDL（`01_schema.sql` 建表，其后
`02`…`07` 逐个增量补列/补表），`app/db/tables.py` 只是让代码能读写它。两者一旦漂移，症状会非常隐蔽：
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
    # 私有知识库（`sql/07_knowledge_base.sql`）。两张表而不是一张的理由见该 DDL 文件头。
    "knowledge_bases",
    "knowledge_documents",
    # 题目配图的日额度（`sql/08_question_image.sql`）。不放在 `user_settings` 上：
    # 额度要按天重置、要原子自增，与「用户偏好」是两种读写模式。
    "image_quota_usage",
}

#: 方案设计 §9.1 实测的外键数量（13），Phase D 新增 1 个：
#: `questions.fk_questions_origin` —— 复习关卡的副本指回原错题（见
#: `sql/02_questions_origin.sql`）。
#: 私有知识库再新增 3 个（见 `sql/07_knowledge_base.sql`）：
#: `fk_knowledge_bases_user`、`fk_knowledge_documents_kb`、`fk_knowledge_documents_user`。
#: 题目配图再新增 1 个（见 `sql/08_question_image.sql`）：`fk_image_quota_usage_user`。
#: （`questions.image_url` 只是一个可空的字符串列，**不引入外键**。）
EXPECTED_FK_COUNT = 18


def test_thirteen_tables_defined() -> None:
    assert len(ALL_TABLES) == 13
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


def test_questions_image_url_column(test_engine) -> None:  # noqa: ANN001
    """`questions.image_url`：可空、够长、位置紧跟 `difficulty`。

    三件事都要验：
    - **可空**是「这道题没有配图」的表达方式（生图失败 / 没勾选 / 未启用都落到 NULL），
      设成 NOT NULL 会让「没生成出图」变成写入失败，把降级路径直接堵死；
    - 长度必须装得下我们自己拼的 COS URL（桶名 + 键），768 只是防御；
    - 位置与 `test_column_order_matches_database` 有关：DDL 用的是 `AFTER difficulty`，
      ORM 里也必须插在同一处，否则顺序断言会红。
    """
    columns = inspect(test_engine).get_columns("questions")
    names = [c["name"] for c in columns]
    col = next(c for c in columns if c["name"] == "image_url")

    assert col["nullable"] is True
    assert col["type"].length == 512
    assert "image_url" in names
    assert names.index("image_url") == names.index("difficulty") + 1


def test_image_quota_usage_shape(test_engine) -> None:
    """额度表的结构：业务日 + 复合主键 + 级联删除。

    复合主键 `(user_id, biz_date)` 不只是唯一约束，它就是「查某人今天用量」
    的索引 —— 少了它这个查询会走全表扫描，而这句查询每次出题都要跑。
    """
    inspector = inspect(test_engine)
    columns = {c["name"]: c for c in inspector.get_columns("image_quota_usage")}

    assert set(columns) == {"user_id", "biz_date", "used_count", "created_at", "updated_at"}
    assert columns["biz_date"]["type"].__class__.__name__ == "DATE"
    assert columns["used_count"]["nullable"] is False

    pk = inspector.get_pk_constraint("image_quota_usage")
    assert sorted(pk["constrained_columns"]) == ["biz_date", "user_id"]

    fks = inspector.get_foreign_keys("image_quota_usage")
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "users"
    # 用户被删时额度行一并消失（它是纯计数行，没有留档价值）
    assert fks[0]["options"].get("ondelete", "").upper() == "CASCADE"


def test_session_is_clean_between_tests(db_session) -> None:  # noqa: ANN001
    """确认清表真的生效：如果这条失败，说明用例之间会互相污染。"""
    from app.db.tables import User

    assert db_session.query(User).count() == 0


@pytest.mark.parametrize(
    "table_name",
    [
        "users",
        "user_settings",
        "quizzes",
        "questions",
        "attempts",
        "answers",
        "reports",
        "knowledge_bases",
        "knowledge_documents",
        "image_quota_usage",
    ],
)
def test_created_at_and_updated_at_present(test_engine, table_name: str) -> None:  # noqa: ANN001
    """公共列约定（方案 §5.0）：每表都带 `created_at` / `updated_at`。"""
    columns = {c["name"] for c in inspect(test_engine).get_columns(table_name)}

    assert {"created_at", "updated_at"} <= columns
