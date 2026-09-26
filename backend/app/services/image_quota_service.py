"""题目配图的**每日配额**。

## 为什么另建一张表，而不是复用 `app/core/ratelimit.py`

那个限流器是**进程内滑动窗口**。做「每人每天 20 张」会有两个不能接受的后果：
进程重启即清零、多实例部署时各算各的。配额是**要花钱**的东西，
所以计数必须落库 —— 见 `image_quota_usage`（`sql/08_question_image.sql`）。

## 三段式

| 入口 | 时机 | 作用 |
|---|---|---|
| `reserve` | `create_task` **之前** | 预扣。不足则抛 `AppError` 并给出可执行的下一步 |
| `settle` | 出题任务成功后 | 按**实际成功张数**结算，把没生成出来的张数退回去 |
| `release` | 任务整体失败 / 被取消 | 全额退回 |

预扣放在建任务之前，是为了让用户**立刻**知道没额度，而不是等十几秒才收到一句失败
（与 `quiz_service._resolve_kb_scope` 的「建任务前校验」同一纪律）。

## 为什么不是「先读后写」

先读后写会超发：两个并发请求都读到 `used=18`（上限 20），各自都认为"还剩 2 张"，
于是总共扣出 22 张。而配额一旦超发就无法回收（钱已经花了）。

## 原子性怎么做的（含两个实测结论）

**结论一：不能用 `ON DUPLICATE KEY UPDATE` 的受影响行数当超额判据。**
本机 MySQL 实测（pymysql，`SELECT ROW_COUNT()` 与驱动的 `rowcount` 一致）：

| 情形 | rowcount |
|---|---|
| 新插入 | 1 |
| 真正更新了值 | 2 |
| 命中重复键但**值没变**（被 `IF` 钳住） | **1** |

也就是说「新插入」与「被钳住」都返回 1，无法区分 —— 官方文档说的
「值未改变时为 0」在这台服务器上不成立。**所以不要照抄那个判据。**

**结论二：改成「无条件自增 → 同事务回读 → 超额则原样减回」。**
自增是无条件的一句 `ON DUPLICATE KEY UPDATE used_count = used_count + N`，
它直接对该行加 X 锁并**持有到事务结束**；紧跟着的回读与（可能的）减回
都在同一把锁下，读到的必然是自己刚写进去的值。
`used > cap` 时把这次的自增原样减掉再把请求拒掉 ——
所以「拒绝」的请求在库里**一分都不留**。

## 退还为什么不能写成 `GREATEST(used_count - N, 0)`

`used_count` 是 `INT UNSIGNED`。实测（同上环境）：

```
UPDATE ... SET used_count = GREATEST(used_count - 99, 0)   -- 当前值 2
→ (1690, "BIGINT UNSIGNED value is out of range")
```

MySQL **先算减法再算 `GREATEST`**，减法本身已经下溢报错，`GREATEST` 根本没机会兜底。
所以一律写成 `IF(used_count >= N, used_count - N, 0)`：
`N` 大于当前值时才不执行减法。这条在 `tests/test_image_quota.py` 里有对应用例
（`test_release_more_than_used_stays_at_zero`）。

## 业务日

`biz_date` 按 `APP_TIMEZONE` 判定（与「连续天数」「错题到期」同一口径）。
用 UTC 日期的话，中国用户的额度会在**早上 8 点**重置，而且晚上 8 点后
用掉的额度会被算到第二天。

`QuotaHold` 携带 `biz_date` 就是为了让 `settle` / `release` 退到
**扣减的那一天**：预扣发生在提交请求时，结算在几十秒后的后台线程里，
跨零点的那一次运行若按「退款时的今天」记，额度会从昨天的桶里漏进今天的桶。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, ErrorCode
from app.utils.timeutil import business_date

#: 无条件自增（原子）。命中重复键时直接 `+N`，不判额度 ——
#: 判额度靠紧随其后的回读，见模块头「结论二」。
_UPSERT = text(
    """
    INSERT INTO image_quota_usage (user_id, biz_date, used_count)
    VALUES (:user_id, :biz_date, :count)
    ON DUPLICATE KEY UPDATE used_count = used_count + :count
    """
)

_SELECT_USED = text(
    """
    SELECT used_count FROM image_quota_usage
    WHERE user_id = :user_id AND biz_date = :biz_date
    """
)

#: 退还。`IF` 是防 UNSIGNED 下溢的**必需**写法，不能换成 `GREATEST`（见模块头）。
_REFUND = text(
    """
    UPDATE image_quota_usage
    SET used_count = IF(used_count >= :count, used_count - :count, 0)
    WHERE user_id = :user_id AND biz_date = :biz_date
    """
)


@dataclass(frozen=True, slots=True)
class QuotaHold:
    """一次预扣的凭据。

    `settle` / `release` 只认这个对象，而不是只认 `user_id` —— 因为
    「退给哪一天」必须跟着预扣走，不能按退款时刻重算（见模块头「业务日」）。
    """

    user_id: int
    biz_date: date
    #: 这次预扣掉的张数
    reserved: int
    #: 预扣之后，当天还剩多少张
    remaining: int


def _daily_quota(settings: Settings) -> int:
    """当天上限。负数按 0 处理 —— 配成 0 等于关掉这条能力，绝不能变成「无限制」。"""
    return max(0, int(settings.image_daily_quota))


def _refund(session: Session, *, user_id: int, biz_date: date, count: int) -> None:
    if count <= 0:
        return
    session.execute(
        _REFUND, {"user_id": user_id, "biz_date": biz_date, "count": int(count)}
    )


def reserve(
    session: Session,
    *,
    user_id: int,
    count: int,
    settings: Settings | None = None,
    moment: datetime | None = None,
) -> QuotaHold:
    """预扣 `count` 张配图额度。

    Args:
        session: 调用方的事务会话。**本函数不 commit** —— 预扣跟着调用方的事务走，
            这样「建任务失败」时预扣会随事务一起回滚，不会漏扣。
        user_id: 用户。
        count: 要预扣的张数（= 题目数量）。
        settings: 取上限用；不传则用全局单例。
        moment: 判定业务日用的时刻；不传取当前时刻。

    Returns:
        预扣凭据（含扣减后的当天剩余）。

    Raises:
        ValueError: `count <= 0`（调用方写错，不是用户超额，所以不混进 `AppError`）。
        AppError: `ErrorCode.RATE_LIMITED`（HTTP 429），文案说明「今天还剩几张 / 怎么继续」，
            并且**不会**扣掉任何额度。
    """
    if count <= 0:
        raise ValueError(f"预扣张数必须为正整数，收到 {count!r}")

    resolved = settings or get_settings()
    cap = _daily_quota(resolved)
    day = business_date(moment)

    # 无条件自增：一句原子语句，直接拿 X 锁
    session.execute(
        _UPSERT, {"user_id": user_id, "biz_date": day, "count": int(count)}
    )
    # 同一把锁下回读 —— 读到的是「含本次自增」的值
    used = int(
        session.execute(
            _SELECT_USED, {"user_id": user_id, "biz_date": day}
        ).scalar_one()
    )

    if used > cap:
        # 把本次自增原样减掉，再拒绝 —— 拒绝的请求一分都不留
        _refund(session, user_id=user_id, biz_date=day, count=count)
        remaining = max(0, cap - (used - count))
        raise AppError(ErrorCode.RATE_LIMITED, _exceeded_message(cap, remaining))

    return QuotaHold(
        user_id=user_id, biz_date=day, reserved=count, remaining=cap - used
    )


def _exceeded_message(cap: int, remaining: int) -> str:
    """超额文案：说清上限、还剩多少、以及**下一步能做什么**。

    只写「额度不足」是没用的 —— 用户需要知道「关掉配图仍能出题」，
    否则他会以为自己今天不能用了。
    """
    if remaining <= 0:
        return f"今天的配图额度已用完（每天 {cap} 张），关掉配图后仍可照常出题"
    return (
        f"今天的配图额度只剩下 {remaining} 张（每天 {cap} 张），"
        "减少题目数量或关掉配图后再试"
    )


def settle(
    session: Session, *, hold: QuotaHold, succeeded: int
) -> int:
    """按**实际成功张数**结算，把没生成出来的张数退回去。

    生图失败时不该让用户为没拿到的图片买单（design D8：单张失败只影响该题）。

    Args:
        succeeded: 真正生成成功的张数。超过 `hold.reserved` 或为负数时都收敛到
            `[0, reserved]` —— 对着垃圾输入宁可少退，也不多给额度。

    Returns:
        实际退回的张数。
    """
    used_images = max(0, min(int(succeeded), hold.reserved))
    refund = hold.reserved - used_images
    _refund(session, user_id=hold.user_id, biz_date=hold.biz_date, count=refund)
    return refund


def release(session: Session, *, hold: QuotaHold) -> None:
    """任务整体失败 / 被取消 ⇒ 全额退回。

    可安全重复调用（重复时只会退到 0，不会下溢）。
    """
    _refund(
        session,
        user_id=hold.user_id,
        biz_date=hold.biz_date,
        count=hold.reserved,
    )


def used_today(
    session: Session, *, user_id: int, moment: datetime | None = None
) -> int:
    """当天已用张数（读不到行即 0）。

    只给展示与测试用 —— **判断能不能用要走 `reserve`**，不要拿这个读数自己算。
    """
    value = session.execute(
        _SELECT_USED,
        {"user_id": user_id, "biz_date": business_date(moment)},
    ).scalar_one_or_none()
    return int(value or 0)
