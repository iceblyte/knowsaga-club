"""用户资料、设置与复习提醒的业务逻辑。

## 这一层不碰 HTTP

不引 `Request`、不抛 `HTTPException`、不拼响应体。所有输入都是已校验的
Pydantic 对象或原始字节，所有输出都是 Pydantic 契约或 ORM 行。
好处是这些规则可以在没有 HTTP 层的测试里直接调用（`db_session` 夹具），
定位问题时不必先构造一个请求。
"""

from __future__ import annotations

import math
from datetime import date, time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import (
    BADGE_TOTAL,
    NICKNAME_UI_MAX_LEN,
    SECONDS_PER_REVIEW_QUESTION,
    XP_PER_REVIEW_QUESTION,
)
from app.core.exceptions import invalid_input
from app.db.tables import (
    Attempt,
    QuestionRecord,
    QuizRecord,
    User,
    UserBadge,
    UserKnowledgeStat,
    UserSetting,
    WrongQuestion,
)
from app.models.user import (
    ProfileResponse,
    ProfileStats,
    ProfileUpdateRequest,
    ReminderHint,
    RemindersTodayResponse,
    UserPublic,
    UserSettingsPublic,
    UserSettingsUpdateRequest,
)
from app.services.level_service import level_progress
from app.utils.crypto import NicknameError, new_avatar_filename, normalize_nickname
from app.utils.image_check import validate_avatar_bytes
from app.utils.timeutil import business_date, utcnow

#: 时间字符串的解析格式（由 Pydantic 层保证形状为 `HH:MM`）
_TIME_FORMAT = "%H:%M"


# -----------------------------------------------------------------------------
# 用户视图
# -----------------------------------------------------------------------------
def to_user_public(user: User) -> UserPublic:
    """ORM 行 → 对外视图。等级与进度在这里由 `xp_total` 派生。"""
    progress = level_progress(int(user.xp_total))

    return UserPublic(
        id=int(user.id),
        nickname=user.nickname,
        avatar_key=user.avatar_key,
        avatar_url=user.avatar_url,
        xp_total=int(user.xp_total),
        coins=int(user.coins),
        streak_days=int(user.streak_days),
        longest_streak=int(user.longest_streak),
        level=progress.level,
        level_title=progress.title,
        next_level_xp=progress.next_threshold,
        xp_to_next_level=progress.xp_to_next,
        level_progress=progress.percent,
        created_at=user.created_at,
    )


def build_profile(session: Session, user: User) -> ProfileResponse:
    """个人中心（原型 04·1）：身份 + 三宫格 + 三个入口行的计数。

    全部计数都在这里一次取齐。**没有数据时给 0 而不是报错** ——
    新用户的个人中心必须能正常渲染成「全是 0」的样子。
    """
    user_id = int(user.id)

    # 「闯关副本」与「历史卷轴」是同一个数（原型 04·1 两处都写 12），
    # 且必须等于历史卷轴列表的长度 —— 所以**排除已软删除的挑战**。
    # 平均正确率则刻意不排除：FR-B5 验收标准点名「正确率不变」，
    # 它与看板那条实时聚合是同一个口径（见 scroll_service 模块说明的对照表）。
    attempt_count = _count(
        session, Attempt, Attempt.user_id == user_id, Attempt.deleted_at.is_(None)
    )
    avg = session.scalar(select(func.avg(Attempt.accuracy)).where(Attempt.user_id == user_id))

    return ProfileResponse(
        user=to_user_public(user),
        stats=ProfileStats(
            attempt_count=attempt_count,
            # AVG 在 MySQL 上返回 Decimal；四舍五入成整数百分比与原型「83%」一致
            avg_accuracy=int(round(float(avg))) if avg is not None else 0,
            lit_kp_count=_count(
                session, UserKnowledgeStat, UserKnowledgeStat.user_id == user_id,
                UserKnowledgeStat.lit.is_(True),
            ),
            # 「历史卷轴」按挑战记录计数（方案 §5.5 的裁决：列表项 = 一次挑战）
            scroll_count=attempt_count,
            badge_unlocked=_count(session, UserBadge, UserBadge.user_id == user_id),
            badge_total=BADGE_TOTAL,
        ),
    )


def update_profile(
    session: Session,
    user: User,
    payload: ProfileUpdateRequest,
) -> UserPublic:
    """改昵称与预置头像。

    选了预置头像就**清掉自定义头像地址**：两个字段同时存在时读取以
    `avatar_url` 优先（方案 §5.1），不清掉的话用户点了预置头像却看不到变化。
    """
    if payload.nickname is not None:
        try:
            user.nickname = normalize_nickname(payload.nickname, max_len=NICKNAME_UI_MAX_LEN)
        except NicknameError as exc:
            raise invalid_input(str(exc)) from exc

    if payload.avatar_key is not None:
        user.avatar_key = payload.avatar_key
        user.avatar_url = None

    user.updated_at = utcnow()
    session.commit()
    return to_user_public(user)


def save_avatar(
    session: Session,
    user: User,
    *,
    data: bytes,
    max_bytes: int,
) -> UserPublic:
    """校验并落盘自定义头像，返回更新后的用户视图。

    落盘名由 `new_avatar_filename` 生成（`u{id}_{时间戳}_{随机}.{后缀}`），
    **绝不使用客户端提供的文件名** —— 那是能拼出 `../` 的输入。

    刻意不做「删除旧头像文件」：那是唯一一处为清理而删除用户数据的动作，
    收益（省几 MB）远小于风险（误删、权限、沙箱策略）。等真有存储压力
    再做一次带校验的清理任务。
    """
    validation = validate_avatar_bytes(data, max_bytes)

    target_dir = _ensure_dir(_avatars_dir())
    filename = new_avatar_filename(int(user.id), validation.suffix)
    (target_dir / filename).write_bytes(data)

    # 静态路径由 main.py 的挂载点决定（`/static/avatars`），这里必须与它一致
    user.avatar_url = f"/static/avatars/{filename}"
    user.updated_at = utcnow()
    session.commit()
    return to_user_public(user)


# -----------------------------------------------------------------------------
# 设置
# -----------------------------------------------------------------------------
def get_settings_public(session: Session, user: User) -> UserSettingsPublic:
    row = ensure_settings_row(session, user)
    return _to_settings_public(row)


def update_settings(
    session: Session,
    user: User,
    payload: UserSettingsUpdateRequest,
) -> UserSettingsPublic:
    """按字段更新。只写传了的字段（`None` 表示「本次不改」）。

    这里用 `exclude_unset` 语义而不是「非 None」：布尔开关的 `False`
    是一个合法的目标值，不能与「未提交」混为一谈。
    由于契约里所有字段默认都是 `None`，两者恰好等价 ——
    但显式写出来是为了将来有人加一个 `bool = False` 默认值时不会静默出错。
    """
    row = ensure_settings_row(session, user)
    changed = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "reminder_time" in changed:
        row.reminder_time = _parse_hhmm(changed["reminder_time"])

    if "reminder_days" in changed:
        row.reminder_days = list(changed["reminder_days"])

    for field in (
        "reminder_enabled",
        "remind_streak_break",
        "remind_review_due",
        "sound_enabled",
        "auto_load_images",
        "eye_care",
    ):
        if field in changed:
            setattr(row, field, bool(changed[field]))

    row.updated_at = utcnow()
    session.commit()
    return _to_settings_public(row)


def ensure_settings_row(session: Session, user: User) -> UserSetting:
    """取设置行；缺失时补建。

    正常路径下设置行由建档时一起创建，这里是为了兜住「表建好之前就存在的
    用户」以及手工插数据的情况 —— 少一行设置不该让整个设置页 500。
    """
    row = session.get(UserSetting, int(user.id))
    if row is None:
        row = UserSetting(user_id=int(user.id))
        session.add(row)
        session.commit()
    return row


# -----------------------------------------------------------------------------
# 复习提醒（原型 04·8）
# -----------------------------------------------------------------------------
def reminders_today(session: Session, user: User) -> RemindersTodayResponse:
    """今日到期错题的三宫格数据。

    估算是**下限**：XP 按题型最低满分 20 计（判断题），实际结算只会更多。
    把预期说低、兑现时超出，比反过来让人失望要好。

    `hint` 回答原型那句「为什么是今天」。有多个到期错题时取**等得最久**的
    那一道：其它题只会更晚，而这一道超过自己的排期最久，它才是「现在就该
    做」的那个理由。没有到期错题时是 `None` —— 理由必须对应事实。
    """
    user_id = int(user.id)
    due_condition = (
        WrongQuestion.user_id == user_id,
        WrongQuestion.mastered.is_(False),
        WrongQuestion.next_review_at <= utcnow(),
    )
    due_count = _count(session, WrongQuestion, *due_condition)

    row = ensure_settings_row(session, user)
    return RemindersTodayResponse(
        due_count=due_count,
        estimated_minutes=math.ceil(due_count * SECONDS_PER_REVIEW_QUESTION / 60),
        available_xp=due_count * XP_PER_REVIEW_QUESTION,
        snoozed_today=_is_snoozed(row),
        hint=_reminder_hint(session, due_condition),
    )


def _reminder_hint(session: Session, due_condition) -> ReminderHint | None:  # noqa: ANN001
    """取「等得最久」的到期错题，拼出「N 天前在「X」上失手」的两个事实。

    `ORDER BY last_wrong_at, id` 里的 `id` 只为**确定性**：同一秒入队的两道题
    排序不该随数据库的执行计划变，否则同一次刷新可能换一句话。
    """
    row = session.execute(
        select(
            WrongQuestion.last_wrong_at,
            QuestionRecord.knowledge_point,
            QuizRecord.title,
        )
        .join(QuestionRecord, WrongQuestion.question_id == QuestionRecord.id)
        .join(QuizRecord, QuestionRecord.quiz_id == QuizRecord.id)
        .where(*due_condition)
        .order_by(WrongQuestion.last_wrong_at, WrongQuestion.id)
        .limit(1)
    ).first()
    if row is None:
        return None

    # 知识点缺失时退化为卷轴标题：宁可说得粗一点，也不要渲染出「你在「」上失手」
    topic = str(row[1] or "").strip() or str(row[2] or "").strip()
    if not topic:
        return None

    days_ago = (business_date() - business_date(row[0])).days
    # 服务器间时钟偏差可能让刚写入的行落进「明天」；负数天数读不通，夹到 0
    return ReminderHint(days_ago=max(0, days_ago), topic=topic)


def snooze_today(session: Session, user: User) -> None:
    """「今天先不复习」：只记忽略日期，不动错题排期。"""
    row = ensure_settings_row(session, user)
    row.remind_snooze_date = business_date()
    row.updated_at = utcnow()
    session.commit()


def is_snoozed_today(session: Session, user: User) -> bool:
    """给大厅/个人中心的页内提示入口用：被忽略过就不再打扰。"""
    return _is_snoozed(ensure_settings_row(session, user))


def _is_snoozed(row: UserSetting) -> bool:
    """是否已忽略今天。

    只比日期、不比时间：这是「今天不再提示」的语义。
    跨天后 `remind_snooze_date` 自然不等于今天的日期，提示自动恢复 ——
    不需要任何定时任务去清理它。
    """
    snooze_date: date | None = row.remind_snooze_date
    return snooze_date is not None and snooze_date == business_date()


# -----------------------------------------------------------------------------
# 内部工具
# -----------------------------------------------------------------------------
def _count(session: Session, model, *conditions) -> int:  # noqa: ANN001
    """`SELECT COUNT(*)` 的薄封装，失败即 0。"""
    total = session.scalar(select(func.count()).select_from(model).where(*conditions))
    return int(total or 0)


def _parse_hhmm(value: str) -> time:
    """`"20:00"` → `datetime.time(20, 0)`。

    不引 `datetime.strptime`：它要求格式串与输入逐字符匹配，
    而这里形状已由 Pydantic 的正则保证过，直接切分更不易出错。
    """
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _to_settings_public(row: UserSetting) -> UserSettingsPublic:
    return UserSettingsPublic(
        reminder_enabled=bool(row.reminder_enabled),
        reminder_time=row.reminder_time.strftime(_TIME_FORMAT),
        reminder_days=[int(d) for d in (row.reminder_days or [])],
        remind_streak_break=bool(row.remind_streak_break),
        remind_review_due=bool(row.remind_review_due),
        sound_enabled=bool(row.sound_enabled),
        auto_load_images=bool(row.auto_load_images),
        eye_care=bool(row.eye_care),
    )


def _avatars_dir() -> Path:
    """头像目录（来自配置）。运行期取值而不是 import 时固化，便于测试重定向。"""
    from app.core.config import get_settings

    return get_settings().avatars_path


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
