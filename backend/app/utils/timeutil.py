"""时间与时区工具。

## 为什么需要单独一层

项目里有两种「时间」，它们不能混：

| 用途 | 表示 | 例子 |
|---|---|---|
| 存储与比较 | **naive UTC**（`DATETIME(3)` 不含时区信息，存的就是 UTC 裸时间） | `attempts.finished_at` |
| 面向用户的「今天」 | **业务时区** `Asia/Shanghai` 的日期 | 连续天数、错题到期、看板按天分组 |

如果拿 UTC 的日期当「今天」，北京时间晚上 8 点之后完成的学习会被算到**第二天** ——
连续天数会莫名断掉，错题会在错误的日期到期。这类错误不抛异常，只是悄悄算错。

## 为什么需要 tzdata

Windows 没有系统的 IANA 时区库，`ZoneInfo("Asia/Shanghai")` 会抛
`ZoneInfoNotFoundError`。所以 `tzdata` 是运行依赖（见 requirements.txt）；
万一缺失，`business_tz()` 退化为固定 UTC+8 并记录警告 ——
对 1991 年后的中国（全年 UTC+8，无夏令时）结果完全一致。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: tzdata 缺失时的退路。中国自 1991 年起全年 UTC+8，无夏令时，等价。
_FALLBACK_TZ = timezone(timedelta(hours=8), name="UTC+08:00")

#: `DATETIME(3)` 的精度是毫秒。写入前先截断，保证「写进去什么、读出来就是什么」。
_MS = 1000


def utcnow() -> datetime:
    """当前 UTC 时刻（naive，毫秒精度）。

    为什么要截断微秒：`DATETIME(3)` 会把微秒四舍五入到毫秒，若不做截断，
    `obj.created_at == utcnow()` 这类断言在写库前后会不相等 —— 一个纯粹的精度假象。
    """
    now = datetime.now(timezone.utc)
    return now.replace(tzinfo=None, microsecond=(now.microsecond // _MS) * _MS)


def to_naive_utc(moment: datetime) -> datetime:
    """把任意 datetime 转成 naive UTC。

    带时区的直接换算；不带时区的**按 UTC 解释**（因为库里存的都是 UTC）。
    """
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def as_aware_utc(moment: datetime) -> datetime:
    """把库里的 naive datetime 标成 UTC（用于跨时区换算）。"""
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc)
    return moment.replace(tzinfo=timezone.utc)


def from_timestamp_ms(ms: int) -> datetime:
    """客户端上报的毫秒时间戳 -> naive UTC。

    客户端时间是**不可信输入**：这里只做换算，合法性（比如「不能晚于现在太多」）
    由业务层判断。
    """
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(
        tzinfo=None, microsecond=0
    )


def to_timestamp_ms(moment: datetime) -> int:
    """naive UTC -> 毫秒时间戳。"""
    return int(as_aware_utc(moment).timestamp() * 1000)


@lru_cache(maxsize=8)
def _zone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover - 取决于运行环境
        logger.warning(
            "时区 %s 不可用（Windows 需要 tzdata 包），已退化为固定 UTC+8", name
        )
        return _FALLBACK_TZ


def business_tz():
    """业务时区对象（来自 `APP_TIMEZONE`）。"""
    return _zone(get_settings().app_timezone or "Asia/Shanghai")


def business_now() -> datetime:
    """业务时区的当前时刻（带时区信息）。"""
    return datetime.now(business_tz())


def business_date(moment: datetime | None = None) -> date:
    """某个时刻对应的「业务日期」。

    传 naive datetime 时按 UTC 解释；不传则取当前时刻。
    """
    return as_aware_utc(moment or utcnow()).astimezone(business_tz()).date()


def business_day_bounds(day: date) -> tuple[datetime, datetime]:
    """某个业务日期的起止时刻，返回**naive UTC**（可直接与库里的列比较）。

    左闭右开：`[start, end)`。用它做「近 7 天」这类按天聚合，
    边界不会因为半开区间写错而重复或漏掉跨零点的记录。

    注意夏令时：`Asia/Shanghai` 现在没有夏令时，但对其他时区，
    `day + 1` 的零点是重新计算的，而不是简单加 24 小时 —— 加 24 小时在
    切换日会错一小时。所以这里独立取两个日期的零点。
    """
    tz = business_tz()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return to_naive_utc(start), to_naive_utc(end)


def add_days(moment: datetime, days: int) -> datetime:
    """在 naive UTC 时刻上加天数。

    「错题的 1/2/4/7/15/30 天后到期」按**自然日**推进 —— 用 UTC 加天数即可：
    业务时区固定 UTC+8，加整数天不会改变业务日期。
    """
    return moment + timedelta(days=days)
