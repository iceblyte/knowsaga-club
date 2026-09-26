"""题目配图配额服务用例（TDD：先写测试跑红）。

这一层要守住四件事：

1. **不超额**：预扣超过当天剩余额度时拒绝，且**不留痕**（不能扣一半）；
2. **并发不超发**：同一用户同时预扣，成功数恰好等于额度；
3. **按实际用量结算**：没生成出来的张数要退回去，否则用户会为失败的图买单；
4. **业务日口径**：跨日按 `APP_TIMEZONE` 重置，且退款要退到**扣减的那一天**，
   而不是退款时刻所在的那一天。

第 4 条容易被忽略：预扣发生在提交请求时，结算是几十秒后的后台线程里。
如果按「退款时的今天」记，跨零点的那一次运行会把额度退进第二天的桶。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError, ErrorCode
from app.db.tables import ImageQuotaUsage
from app.services import image_quota_service
from app.utils.timeutil import business_date
from tests.helpers import at, make_user


def _used_count(session, *, user_id: int, day: date) -> int:
    """**直接读表**取当天用量。

    刻意不复用服务的读数函数：用它来断言它自己，等于让实现给自己判卷。
    """
    value = session.execute(
        select(ImageQuotaUsage.used_count).where(
            ImageQuotaUsage.user_id == user_id,
            ImageQuotaUsage.biz_date == day,
        )
    ).scalar_one_or_none()
    return int(value or 0)


@pytest.fixture
def quota_user(db_session):  # noqa: ANN001, ANN201
    """一个真实用户（`image_quota_usage` 有指向 `users.id` 的外键）。"""
    return make_user(db_session, openid="openid-quota")


# -----------------------------------------------------------------------------
# reserve：正常路径
# -----------------------------------------------------------------------------
def test_reserve_within_quota_succeeds_and_reports_remaining(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)

    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings
    )

    assert hold.reserved == 2
    assert hold.remaining == 3
    assert hold.biz_date == business_date()
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 2


def test_reserve_exactly_consumes_quota(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)

    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=5, settings=settings
    )

    assert hold.remaining == 0
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 5


def test_reserve_accumulates_across_calls(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)

    image_quota_service.reserve(db_session, user_id=quota_user.id, count=3, settings=settings)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings
    )

    assert hold.remaining == 0
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 5


# -----------------------------------------------------------------------------
# reserve：拒绝路径
# -----------------------------------------------------------------------------
def test_reserve_beyond_remaining_is_rejected(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    image_quota_service.reserve(db_session, user_id=quota_user.id, count=4, settings=settings)

    with pytest.raises(AppError) as excinfo:
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=3, settings=settings
        )

    assert excinfo.value.code == ErrorCode.RATE_LIMITED
    # 关键：被拒的那一次**一分都不许扣**
    assert _used_count(db_session, user_id=quota_user.id, day=business_date()) == 4


def test_reserve_larger_than_quota_leaves_no_trace(db_session, image_env, quota_user):
    """整批预扣超过额度时，连一笔都不留（不能扣掉一半再报错）。"""
    settings = image_env(IMAGE_DAILY_QUOTA=3)

    with pytest.raises(AppError):
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=5, settings=settings
        )

    assert _used_count(db_session, user_id=quota_user.id, day=business_date()) == 0


def test_rejection_message_tells_user_how_to_proceed(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    image_quota_service.reserve(db_session, user_id=quota_user.id, count=5, settings=settings)

    with pytest.raises(AppError) as excinfo:
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=1, settings=settings
        )

    message = excinfo.value.message
    assert "配图" in message
    assert "5" in message  # 把上限说清楚
    assert "关掉配图" in message  # 给出可执行的下一步


def test_partial_remaining_message_states_the_remainder(db_session, image_env, quota_user):
    """还剩几张时说「只剩 N 张」，而不是笼统地说「用完了」。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    image_quota_service.reserve(db_session, user_id=quota_user.id, count=4, settings=settings)

    with pytest.raises(AppError) as excinfo:
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=2, settings=settings
        )

    assert "1" in excinfo.value.message
    assert "关掉配图" in excinfo.value.message


def test_zero_quota_rejects_everything(db_session, image_env, quota_user):
    """配额配成 0 就等于关掉这条能力 —— 不能变成「无限制」。"""
    settings = image_env(IMAGE_DAILY_QUOTA=0)

    with pytest.raises(AppError):
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=1, settings=settings
        )


def test_non_positive_count_is_a_programming_error(db_session, image_env, quota_user):
    """`count <= 0` 是调用方写错，不该被当成「用户超额」混在同一个异常里。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)

    with pytest.raises(ValueError):
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=0, settings=settings
        )


# -----------------------------------------------------------------------------
# 并发：同一用户同时预扣不超发
# -----------------------------------------------------------------------------
def test_concurrent_reserve_does_not_over_issue(db_engine, image_env):  # noqa: ANN001
    """8 个人同时抢 5 张额度 ⇒ 恰好 5 次成功。

    这条用例是**原子性**的判据：若实现是「先读后写」，这里会成功 6~8 次。
    `outcomes` 里混进 `error:*` 说明实现撞了死锁 —— 那也是失败，不许忽略。
    """
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)

    with factory() as seed:
        user = make_user(seed, openid="openid-quota-conc")
        user_id = int(user.id)

    def reserve_one(_index: int) -> str:
        session = factory()
        try:
            image_quota_service.reserve(
                session, user_id=user_id, count=1, settings=settings
            )
            session.commit()
            return "ok"
        except AppError:
            session.rollback()
            return "rejected"
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            return f"error:{type(exc).__name__}"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve_one, range(8)))

    assert outcomes.count("ok") == 5, outcomes
    assert outcomes.count("rejected") == 3, outcomes

    # 换一个会话读回，确认落库的确实是 5（不是靠内存里对齐的）
    with factory() as verify:
        assert _used_count(verify, user_id=user_id, day=business_date()) == 5


# -----------------------------------------------------------------------------
# settle：按实际成功张数结算
# -----------------------------------------------------------------------------
def test_settle_refunds_the_failed_images(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=5, settings=settings
    )

    refunded = image_quota_service.settle(db_session, hold=hold, succeeded=3)

    assert refunded == 2
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 3


def test_settle_with_all_successes_refunds_nothing(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=3, settings=settings
    )

    assert image_quota_service.settle(db_session, hold=hold, succeeded=3) == 0
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 3


def test_settle_with_zero_successes_refunds_everything(db_session, image_env, quota_user):
    """整段生图全挂 ⇒ 这一批完全不该计费。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=5, settings=settings
    )

    assert image_quota_service.settle(db_session, hold=hold, succeeded=0) == 5
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 0


def test_settle_more_than_reserved_refunds_nothing(db_session, image_env, quota_user):
    """`succeeded > reserved` 是调用方算错了：此时**不退**（对着垃圾输入宁可少退，
    也不多给额度）。要验证的是它既不下溢报错，也不会把额度白送出去。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings
    )

    assert image_quota_service.settle(db_session, hold=hold, succeeded=99) == 0
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 2


def test_settle_negative_successes_refunds_everything(db_session, image_env, quota_user):
    """`succeeded < 0` 同样收敛：按「一张都没成」全额退回，而不是退得比预扣还多。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings
    )

    assert image_quota_service.settle(db_session, hold=hold, succeeded=-1) == 2
    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 0


# -----------------------------------------------------------------------------
# release：任务整体失败 / 取消时全额退回
# -----------------------------------------------------------------------------
def test_release_refunds_the_whole_hold(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=4, settings=settings
    )

    image_quota_service.release(db_session, hold=hold)

    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 0


def test_release_more_than_used_stays_at_zero(db_session, image_env, quota_user):
    """重复退还（或额度被别处改小）时只退到 0，绝不越过下界报错。

    这条是「`GREATEST` 拦不住 UNSIGNED 下溢」那件事的判据 —— 若退还写成了
    `GREATEST(used_count - N, 0)`，第二次退还会直接抛 1690。
    """
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings
    )
    image_quota_service.release(db_session, hold=hold)

    # 同一张凭据再退一次：不该抛错，也不该变成 -2
    image_quota_service.release(db_session, hold=hold)

    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 0


def test_release_on_a_day_without_row_is_a_noop(db_session, image_env, quota_user):
    """跨天后才来退（或压根没预扣成功）⇒ 静默无操作，不报错。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings, moment=at(-3)
    )
    db_session.execute(
        ImageQuotaUsage.__table__.delete().where(
            ImageQuotaUsage.user_id == quota_user.id
        )
    )

    image_quota_service.release(db_session, hold=hold)


# -----------------------------------------------------------------------------
# 业务日口径
# -----------------------------------------------------------------------------
def test_quota_resets_on_the_next_business_day(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=2)

    yesterday = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings, moment=at(-1)
    )
    with pytest.raises(AppError):
        image_quota_service.reserve(
            db_session, user_id=quota_user.id, count=1, settings=settings, moment=at(-1)
        )

    today = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=2, settings=settings, moment=at(0)
    )

    assert yesterday.biz_date != today.biz_date
    assert _used_count(db_session, user_id=quota_user.id, day=yesterday.biz_date) == 2
    assert _used_count(db_session, user_id=quota_user.id, day=today.biz_date) == 2


def test_refund_goes_back_to_the_day_it_was_taken_from(db_session, image_env, quota_user):
    """跨零点的那一次运行：退款必须退进**预扣那天**的桶。

    否则额度会从昨天的桶里漏掉、又凭空多进今天的桶 —— 两个方向都错。
    """
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    hold = image_quota_service.reserve(
        db_session, user_id=quota_user.id, count=3, settings=settings, moment=at(-1)
    )

    # 结算发生在第二天（此刻的「今天」已经不是 hold.biz_date 了）
    image_quota_service.settle(db_session, hold=hold, succeeded=1)

    assert _used_count(db_session, user_id=quota_user.id, day=hold.biz_date) == 1
    assert _used_count(db_session, user_id=quota_user.id, day=business_date()) == 0


# -----------------------------------------------------------------------------
# 读数
# -----------------------------------------------------------------------------
def test_used_today_reads_zero_for_a_fresh_user(db_session, image_env, quota_user):
    image_env(IMAGE_DAILY_QUOTA=5)

    assert image_quota_service.used_today(db_session, user_id=quota_user.id) == 0


def test_used_today_reflects_reservations(db_session, image_env, quota_user):
    settings = image_env(IMAGE_DAILY_QUOTA=5)
    image_quota_service.reserve(db_session, user_id=quota_user.id, count=3, settings=settings)

    assert image_quota_service.used_today(db_session, user_id=quota_user.id) == 3
