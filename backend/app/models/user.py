"""用户域的请求 / 响应契约（Pydantic）。

## 与 `app/db/tables.py` 的分工

`tables.py` 是**数据库表**（SQLAlchemy），这里是**接口契约**（Pydantic）。
两者刻意不共用：表结构会因为索引、列类型而调整，接口契约会因为界面而调整，
混成一个类的后果是「改界面顺手改了列类型」。

## 一处必须说清的事

`UserPublic` 里**没有** `openid`、`session_key`、`token_version`。
这不是漏了 —— 前两个是登录凭据与敏感材料，第三个是内部撤销机制。
它们在模型层面就不存在，所以不存在「某个接口忘了排除」的风险。
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: `HH:MM`（24 小时制）。原型 07·6 的 chips 是 08:00 / 12:30 / 20:00 / 22:00。
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

#: 星期取值范围：1 = 周一 … 7 = 周日（与 `user_settings.reminder_days` 的注释一致）
_MIN_WEEKDAY = 1
_MAX_WEEKDAY = 7


# -----------------------------------------------------------------------------
# 用户
# -----------------------------------------------------------------------------
class UserPublic(BaseModel):
    """可对外暴露的用户视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    avatar_key: str
    #: 自定义头像；**读取时优先于 `avatar_key`**
    avatar_url: str | None = None
    xp_total: int
    coins: int
    streak_days: int
    longest_streak: int

    # 以下是派生字段，由 `services.level_service` 依据 `xp_total` 算出
    level: int
    level_title: str
    #: 下一级门槛（进度条分母）
    next_level_xp: int
    #: 距下一级还差多少
    xp_to_next_level: int
    #: 0–100，直接当 CSS 宽度
    level_progress: int

    created_at: datetime


class ProfileStats(BaseModel):
    """个人中心三宫格与三个入口行的计数（原型 04·1）。"""

    #: 闯关副本
    attempt_count: int
    #: 平均正确率（0–100 整数）
    avg_accuracy: int
    #: 知识树：已点亮领域数
    lit_kp_count: int
    #: 历史卷轴：条目数（= 挑战次数，口径见方案 §5.5）
    scroll_count: int
    #: 勋章墙：已解锁数
    badge_unlocked: int
    #: 勋章墙：总数（原型「6 / 18」的分母）
    badge_total: int


class ProfileResponse(BaseModel):
    user: UserPublic
    stats: ProfileStats


class ProfileUpdateRequest(BaseModel):
    """`PATCH /users/me`。

    字段全部可选：只传要改的那个。**没有 `avatar_url`** ——
    头像地址只能由上传接口产生，不接受客户端指定，否则可以指向外部图床。

    `nickname` 刻意**不在这一层做校验**（没有 `min_length`、没有格式校验）：
    昵称的不合规统一由 `utils.crypto.normalize_nickname` 判定并抛 4001
    （方案 §4.6「昵称不合规复用 4001」）。若这里也拦一道，空字符串与超长
    会先被 Pydantic 变成 4000，同一类错误出现两个码 —— 前端就得分两种情况处理。
    """

    nickname: str | None = None
    avatar_key: str | None = None

    @field_validator("avatar_key")
    @classmethod
    def _check_avatar_key(cls, value: str | None) -> str | None:
        """预置头像只接受 6 个已知键。

        白名单而不是「非空字符串」：这个值会直接决定前端渲染哪个精灵，
        放任意字符串进去等于让客户端决定渲染什么。
        这里的失败是 4000（参数形状不对），与内容合规的 4001 区分开。
        """
        if value is None:
            return None
        from app.utils.crypto import AVATAR_KEYS

        if value not in AVATAR_KEYS:
            raise ValueError(f"未知的预置头像：{value}，可选 {', '.join(AVATAR_KEYS)}")
        return value


# -----------------------------------------------------------------------------
# 登录
# -----------------------------------------------------------------------------
class WechatLoginRequest(BaseModel):
    """`POST /auth/wechat` 入参。

    `code` 来自 `wx.login()`，是一次性、5 分钟有效的临时凭证。
    这里只做长度护栏（防超长垃圾），**合法性与是否用过由上游判定**。
    """

    code: str = Field(min_length=1, max_length=512)


class DevLoginRequest(BaseModel):
    """`POST /auth/dev` 入参。仅开发环境注册。"""

    device_id: str = Field(min_length=1, max_length=128)

    @field_validator("device_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("device_id 不能为空白")
        return cleaned


class LoginResponse(BaseModel):
    """登录成功返回。"""

    token: str
    #: 有效期（秒）
    expires_in: int
    user: UserPublic


# -----------------------------------------------------------------------------
# 设置
# -----------------------------------------------------------------------------
class UserSettingsPublic(BaseModel):
    """`GET /users/me/settings`（原型 07·5 / 07·6 的数据面）。

    `reminder_time` 用 `"HH:MM"` 字符串而不是 `time`：
    前端拿到就显示、改了就直接提交，不需要任何时区/格式转换。
    它表示的是**用户的本地时间**（业务时区），不是一个时间点。

    这里**没有** `subscribe_quota` —— 它是预留列，属于内部机制，
    不出现在面向用户的响应里。
    """

    model_config = ConfigDict(from_attributes=True)

    reminder_enabled: bool
    reminder_time: str
    reminder_days: list[int]
    remind_streak_break: bool
    remind_review_due: bool
    sound_enabled: bool
    auto_load_images: bool
    eye_care: bool


class UserSettingsUpdateRequest(BaseModel):
    """`PATCH /users/me/settings`：全部可选，只改传了的字段。"""

    reminder_enabled: bool | None = None
    reminder_time: str | None = None
    reminder_days: list[int] | None = None
    remind_streak_break: bool | None = None
    remind_review_due: bool | None = None
    sound_enabled: bool | None = None
    auto_load_images: bool | None = None
    eye_care: bool | None = None

    @field_validator("reminder_time")
    @classmethod
    def _check_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not _TIME_PATTERN.match(cleaned):
            raise ValueError("时间格式应为 HH:MM（24 小时制）")
        return cleaned

    @field_validator("reminder_days")
    @classmethod
    def _check_days(cls, value: list[int] | None) -> list[int] | None:
        """星期集合：非空、取值 1–7、**不重复**。

        为什么必须拦重复：`[1,1,1]` 在前端会渲染成三个一样的 chip，
        用户看不出哪里错了，而推送时段却会变成 1 个。
        """
        if value is None:
            return None
        if not value:
            raise ValueError("至少选择一天")
        out_of_range = [d for d in value if not _MIN_WEEKDAY <= d <= _MAX_WEEKDAY]
        if out_of_range:
            raise ValueError(f"星期取值应在 {_MIN_WEEKDAY}–{_MAX_WEEKDAY} 之间")
        if len(set(value)) != len(value):
            raise ValueError("星期不能重复")
        return sorted(set(value))


# -----------------------------------------------------------------------------
# 复习提醒（原型 04·8）
# -----------------------------------------------------------------------------
class ReminderHint(BaseModel):
    """「为什么是今天」的两个事实（原型 04·8 的第二句文案）。

    只给事实、不给整句：措辞属于面向用户的文案，由前端 `copy.ts` 统一持有
    （「今天 / 昨天 / N 天前」三种说法）。服务端只保证**天数**是按业务时区
    的**自然日**之差算出来的 —— 换到前端算，客户端时区不同的人会各算各的。

    与 `scroll_service.finished_label` 的差别是有意的：那里给整句，因为
    「今天 14:20」不含可选措辞，拼出来只有一种说法；这里要拼进一句带引号的
    知识点，留一个槽位给前端比传一整句更不容易在改动时走样。
    """

    #: 上次答错距今几个业务日（0 = 今天，1 = 昨天）
    days_ago: int
    #: 在哪个知识点上失手；题干没给知识点时退化为卷轴标题
    topic: str


class RemindersTodayResponse(BaseModel):
    """今日复习提醒的三宫格与入口开关。"""

    #: 待复习题数
    due_count: int
    #: 预计用时（分钟）
    estimated_minutes: int
    #: 可得 XP（按题型最低满分估算，只会少估不会多估）
    available_xp: int
    #: 今天是否已被「今天先不复习」忽略
    snoozed_today: bool
    #: 「为什么是今天」；没有到期错题时为 `None`（见 `ReminderHint`）
    hint: ReminderHint | None = None


class SnoozeResponse(BaseModel):
    snoozed_today: bool
