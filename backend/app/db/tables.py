"""10 张表的 ORM 映射。

**这份定义必须与 `backend/sql/01_schema.sql` 逐列一致** —— 那份 SQL 是表结构的
权威来源（表已由它建好），这里只是让代码能安全地读写它。测试里有一条
「映射与真实库逐列比对」的用例守着这条一致性。

## 几处容易写错的地方

| 坑 | 这里的处理 |
|---|---|
| `BIGINT UNSIGNED` 主键 | 显式用 `mysql.BIGINT(unsigned=True)`；否则取值范围比真实列大，理论上能构造出存不进去的值 |
| `TINYINT(1)` 布尔列 | 用 `Boolean`（在 MySQL 上就是 TINYINT(1)），Python 侧直接是 `bool` |
| `TINYINT UNSIGNED` 数值列（accuracy / mastery / stage） | 用 `mysql.TINYINT(unsigned=True)`，**不要**用 Boolean |
| JSON 列 | 注解写 `Mapped[Any]` + 显式 `JSON`；写 `Mapped[list[str]]` 会让 SQLAlchemy 找不到类型而报错 |
| `DECIMAL(6,2)` 平均用时 | 用 `Numeric(6, 2)`，Python 侧是 `Decimal`，**不用浮点** |
| 时间列 | 一律 `mysql.DATETIME(fsp=3)`；`created_at/updated_at` 的默认值与 `onupdate` 都在 Python 侧给（显式写 UTC），DDL 里的 `CURRENT_TIMESTAMP(3)` 只作兜底 |
| NOT NULL 的 JSON 默认值 | DDL 的 `DEFAULT (JSON_ARRAY(...))` 只在服务端生效，ORM 插入时若传 `None` 会被严格模式拒绝 → Python 侧也要给 `default` |
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.utils.timeutil import utcnow

# 主键：BIGINT UNSIGNED AUTO_INCREMENT
PK = mysql.BIGINT(unsigned=True)
UINT = mysql.INTEGER(unsigned=True)
USMALL = mysql.SMALLINT(unsigned=True)
UTINY = mysql.TINYINT(unsigned=True)
DT3 = mysql.DATETIME(fsp=3)
#: JSON 列的注解统一用它：SQLAlchemy 无法从 `list[str]` 推导类型，必须显式给 JSON
JsonAny = Any


def _pk() -> Mapped[int]:
    return mapped_column(PK, primary_key=True, autoincrement=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DT3, nullable=False, default=utcnow, server_default=None)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DT3, nullable=False, default=utcnow, onupdate=utcnow, server_default=None)


# -----------------------------------------------------------------------------
# 1. users —— 冒险者
# -----------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("openid", name="uk_users_openid"),
        Index("idx_users_unionid", "unionid"),
    )

    id: Mapped[int] = _pk()
    openid: Mapped[str] = mapped_column(String(64), nullable=False)
    unionid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nickname: Mapped[str] = mapped_column(String(32), nullable=False)
    avatar_key: Mapped[str] = mapped_column(String(32), nullable=False, default="scholar")
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    xp_total: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    coins: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    streak_days: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    last_active_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    token_version: Mapped[int] = mapped_column(UINT, nullable=False, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 2. user_settings —— 用户设置（1:1）
# -----------------------------------------------------------------------------
class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        PK, ForeignKey("users.id", name="fk_user_settings_user", ondelete="CASCADE"), primary_key=True
    )
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reminder_time: Mapped[time] = mapped_column(mysql.TIME, nullable=False, default=time(20, 0))
    reminder_days: Mapped[JsonAny] = mapped_column(
        mysql.JSON, nullable=False, default=lambda: [1, 2, 3, 4, 5]
    )
    remind_streak_break: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remind_review_due: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remind_snooze_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_load_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eye_care: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    subscribe_quota: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 3. quizzes —— 卷轴
# -----------------------------------------------------------------------------
class QuizRecord(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        Index("idx_quizzes_user_created", "user_id", "created_at"),
        Index("idx_quizzes_user_hash", "user_id", "source_hash"),
    )

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        PK, ForeignKey("users.id", name="fk_quizzes_user", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_hash: Mapped[str | None] = mapped_column(mysql.CHAR(64), nullable=True)
    question_count: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="mixed")
    #: 本次出题的**外部取材状态**。三态必须分得开（`sql/04_quiz_search_reference.sql`）：
    #: `off` = 没去取（开关关 / 用户关）｜`degraded` = 取了但一条没取到｜`hit` = 取到了。
    #: 「没去取」是配置问题，「取了没取到」是主题问题 —— 排查路径完全不同，所以是两列不是一列。
    search_state: Mapped[str] = mapped_column(String(16), nullable=False, default="off")
    #: 取材到的资料快照。每条只留 `title`/`url`/`snippet`(已按上限截断)/`kind`/`source`。
    #: ⚠️ 它**不是**资料的权威副本（权威副本在原始网页上），也不该存整页正文 ——
    #: 实测单页可达 74,801 字符，整篇存进去会让这张表迅速膨胀。
    #: ⚠️ `REFERENCES` 是 MySQL 保留字，手写 SQL 时必须写成 `` `references` ``。
    references: Mapped[JsonAny | None] = mapped_column(mysql.JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 4. questions —— 题目快照
# -----------------------------------------------------------------------------
class QuestionRecord(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "seq", name="uk_questions_quiz_seq"),
        Index("idx_questions_quiz_kp", "quiz_id", "knowledge_point"),
    )

    id: Mapped[int] = _pk()
    quiz_id: Mapped[int] = mapped_column(
        PK, ForeignKey("quizzes.id", name="fk_questions_quiz", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(USMALL, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=False)
    answer: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_point: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="easy")
    #: 复习关卡的**副本题**指回原错题；原题为 `NULL`。
    #:
    #: 见 `sql/02_questions_origin.sql` 的说明：错题本按
    #: `COALESCE(origin_question_id, id)` 归并，所以复习答对推进的是原题。
    #: 自引用外键 + `ON DELETE SET NULL`：原题消失时副本退化成它自己。
    origin_question_id: Mapped[int | None] = mapped_column(
        PK,
        ForeignKey(
            "questions.id", name="fk_questions_origin", ondelete="SET NULL"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 5. attempts —— 一次挑战
# -----------------------------------------------------------------------------
class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("client_token", name="uk_attempts_client_token"),
        Index("idx_attempts_user_finished", "user_id", "finished_at"),
        Index("idx_attempts_quiz", "quiz_id"),
    )

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        PK, ForeignKey("users.id", name="fk_attempts_user", ondelete="CASCADE"), nullable=False
    )
    quiz_id: Mapped[int] = mapped_column(
        PK, ForeignKey("quizzes.id", name="fk_attempts_quiz", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(USMALL, nullable=False, default=1)
    client_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    duration_ms: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    partial_count: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    accuracy: Mapped[int] = mapped_column(UTINY, nullable=False, default=0)
    max_xp: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    xp_gained: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    coins_gained: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    avg_seconds_per_question: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("0.00")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="finished")
    #: 历史卷轴里被删除的时刻（软删除）；`None` = 未删除。
    #:
    #: **只影响列表与详情，不影响任何聚合查询**。见 `sql/03_attempts_deleted_at.sql`：
    #: 需求 FR-B5 要求「记录消失但正确率 / XP / 等级不变」，而正确率是实时聚合出来的，
    #: 硬删会连带 `CASCADE` 掉 `answers` 与 `reports`，用户看到的是自己的正确率被改写。
    deleted_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 6. answers —— 逐题作答
# -----------------------------------------------------------------------------
class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uk_answers_attempt_question"),
    )

    id: Mapped[int] = _pk()
    attempt_id: Mapped[int] = mapped_column(
        PK, ForeignKey("attempts.id", name="fk_answers_attempt", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        PK, ForeignKey("questions.id", name="fk_answers_question", ondelete="CASCADE"), nullable=False
    )
    selected: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    earned_xp: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    max_xp: Mapped[int] = mapped_column(USMALL, nullable=False, default=0)
    time_spent_ms: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    answered_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 7. reports —— 冒险日志（1:1 于 attempt）
# -----------------------------------------------------------------------------
class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uk_reports_attempt"),
        Index("idx_reports_user_status", "user_id", "status"),
    )

    id: Mapped[int] = _pk()
    attempt_id: Mapped[int] = mapped_column(
        PK, ForeignKey("attempts.id", name="fk_reports_attempt", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        PK, ForeignKey("users.id", name="fk_reports_user", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    summary_lines: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=True)
    strong_points: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=True)
    weak_points: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=True)
    suggestions: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_code: Mapped[int | None] = mapped_column(mysql.INTEGER, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 8. wrong_questions —— 错题本
# -----------------------------------------------------------------------------
class WrongQuestion(Base):
    __tablename__ = "wrong_questions"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uk_wrong_questions_user_question"),
        Index("idx_wrong_questions_user_due", "user_id", "mastered", "next_review_at"),
    )

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        PK, ForeignKey("users.id", name="fk_wrong_questions_user", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[int] = mapped_column(
        PK,
        ForeignKey("questions.id", name="fk_wrong_questions_question", ondelete="CASCADE"),
        nullable=False,
    )
    wrong_count: Mapped[int] = mapped_column(USMALL, nullable=False, default=1)
    stage: Mapped[int] = mapped_column(UTINY, nullable=False, default=0)
    next_review_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    last_review_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True)
    last_wrong_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    mastered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 9. user_knowledge_stats —— 知识树聚合
# -----------------------------------------------------------------------------
class UserKnowledgeStat(Base):
    __tablename__ = "user_knowledge_stats"
    __table_args__ = (
        UniqueConstraint("user_id", "kp_name", name="uk_user_knowledge_stats_user_kp"),
        Index("idx_user_knowledge_stats_user_lit", "user_id", "lit"),
    )

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        PK,
        ForeignKey("users.id", name="fk_user_knowledge_stats_user", ondelete="CASCADE"),
        nullable=False,
    )
    kp_name: Mapped[str] = mapped_column(String(64), nullable=False)
    total_count: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    mastery: Mapped[int] = mapped_column(UTINY, nullable=False, default=0)
    lit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 10. user_badges —— 勋章解锁记录
# -----------------------------------------------------------------------------
class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_key", name="uk_user_badges_user_key"),)

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        PK, ForeignKey("users.id", name="fk_user_badges_user", ondelete="CASCADE"), nullable=False
    )
    badge_key: Mapped[str] = mapped_column(String(48), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DT3, nullable=False)
    progress_snapshot: Mapped[JsonAny] = mapped_column(mysql.JSON, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 11. knowledge_bases —— 私有知识库
# -----------------------------------------------------------------------------
class KnowledgeBase(Base):
    """用户上传资料的容器（原型 05 第 5 / 6 / 7 屏）。

    与 `knowledge_documents` 分两张表：库是「从哪儿出题」的选择单位，
    而文档有自己的解析状态机 —— 两者的生命周期不同，合成一张表会让
    「库存在但一份文档都没有」这个合法状态表达不出来。
    """

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        Index("idx_kb_user_id", "user_id", "id"),
        UniqueConstraint("user_id", "name", name="uk_kb_user_name"),
    )

    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(
        PK,
        ForeignKey("users.id", name="fk_knowledge_bases_user", ondelete="CASCADE"),
        nullable=False,
    )
    #: 2–40 字，同一用户下唯一（否则用户在列表里分不清该选哪个）
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 用途描述（可选）；它同时参与出题语义
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# -----------------------------------------------------------------------------
# 12. knowledge_documents —— 库里的文档（含解析状态）
# -----------------------------------------------------------------------------
class KnowledgeDocument(Base):
    """一份文档及其解析状态。

    ⚠️ `status` 是**唯一真相**，它刻意不放在 `task_service` 的进程内任务表里：
    那份表有 600 秒 TTL 且进程重启即丢，而用户完全可能隔一夜才回来看
    「解析好了没有」（design D3）。
    """

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("idx_kdoc_kb_id", "kb_id", "id"),
        Index("idx_kdoc_user", "user_id"),
        Index("idx_kdoc_status", "status"),
    )

    id: Mapped[int] = _pk()
    kb_id: Mapped[int] = mapped_column(
        PK,
        ForeignKey("knowledge_bases.id", name="fk_knowledge_documents_kb", ondelete="CASCADE"),
        nullable=False,
    )
    #: 冗余的属主：越权判断要走最短的查询路径，不为了拿它去 JOIN（见 07_*.sql 文件头）
    user_id: Mapped[int] = mapped_column(
        PK,
        ForeignKey("users.id", name="fk_knowledge_documents_user", ondelete="CASCADE"),
        nullable=False,
    )
    #: 客户端提供的原始文件名。展示用，也是扩展名准入的判据
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 小写扩展名（pdf / docx / md / txt），单独一列避免每次从 filename 现切
    ext: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), nullable=False, default=0)
    #: pending / parsing / ready / failed；**只有 ready 参与检索**
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    #: 入库片段数。仅 ready 时非零 —— 解析产出为空会被判 failed，而不是 ready + 0
    chunk_count: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    #: 页数（PDF / Word 拿得到时）。取不到为 0，不假装知道
    page_count: Mapped[int] = mapped_column(UINT, nullable=False, default=0)
    #: 失败分类，供排查聚合；`error_code` 给聚合看，`error_message` 给用户看
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    #: 解析结束（成功或失败）的时刻；解析中为 NULL
    parsed_at: Mapped[datetime | None] = mapped_column(DT3, nullable=True)


#: 全部表（供测试与迁移核对）
ALL_TABLES = (
    User,
    UserSetting,
    QuizRecord,
    QuestionRecord,
    Attempt,
    Answer,
    Report,
    WrongQuestion,
    UserKnowledgeStat,
    UserBadge,
    KnowledgeBase,
    KnowledgeDocument,
)
