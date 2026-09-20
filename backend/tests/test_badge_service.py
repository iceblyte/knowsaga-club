"""勋章规则引擎的单元与集成测试（方案设计 §8.6 的 18 枚）。

## 为什么逐枚断言而不是抽查几个

勋章是**一次性的、不可撤销的**用户资产：解锁后不会回收，弹窗也不会重复弹。
一条写错的条件不会报错，只会在某个用户的档案里留下一枚名不副实的勋章 ——
或者更常见的反面：某枚勋章**永远解锁不了**，而没人会发现。

所以 18 枚逐枚都要有一个「满足」和一个「不满足」的用例，边界值单独再钉一次。

## 两个口径必须写死在测试里

1. **注册表长度 = `BADGE_TOTAL`（18）**。原型「6 / 18」的分母来自个人中心接口，
   任何一边改了而另一边没改，用户就会看到「已解锁 6 / 18」之外的另一个分母。
2. **神秘成就在其余 17 枚之后判定**。它是唯一一枚「依赖其它勋章状态」的勋章，
   判定顺序错了会导致它永远晚一步解锁（要等下一次结算才补上）。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from app.core.constants import BADGE_TOTAL
from app.db.tables import (
    Answer,
    Attempt,
    QuestionRecord,
    QuizRecord,
    User,
    UserBadge,
    WrongQuestion,
)
from app.services import badge_service
from app.services.badge_service import AttemptItem, AttemptSignal, BadgeFacts
from app.utils.timeutil import utcnow
from tests.helpers import at, current_user_id, make_quiz, settle

#: 什么都不满足的基准事实。每一条用例只改它与该枚勋章相关的字段 ——
#: 这样断言失败时可以直接看出是哪个字段的判定写错了。
EMPTY = BadgeFacts()

#: 其余 17 枚的键（神秘成就除外），用于「已解锁全部」的用例
OTHER_KEYS = frozenset(spec.key for spec in badge_service.BADGES if spec.key != badge_service.SECRET_KEY)


def with_facts(**changes: object) -> BadgeFacts:
    return dataclasses.replace(EMPTY, **changes)  # type: ignore[arg-type]


def spec_of(key: str) -> badge_service.BadgeSpec:
    return badge_service.BADGE_BY_KEY[key]


# -----------------------------------------------------------------------------
# 注册表本身
# -----------------------------------------------------------------------------
def test_registry_matches_badge_total() -> None:
    """分母与注册表长度必须一致，否则个人中心会显示「6 / 18」之外的分母。"""
    assert len(badge_service.BADGES) == BADGE_TOTAL == 18
    assert len(badge_service.BADGE_BY_KEY) == 18


def test_registry_keys_are_database_safe() -> None:
    """`badge_key` 是 VARCHAR(48)；超长会在严格模式下写库失败。"""
    for spec in badge_service.BADGES:
        assert spec.key.isascii(), spec.key
        assert len(spec.key) <= 48, spec.key
        assert spec.key == spec.key.lower(), spec.key
        assert spec.name and spec.desc and len(spec.icon) == 1, spec.key
        assert spec.tier in {"gold", "rare"}, spec.key


def test_prototype_named_badges_come_first_in_prototype_order() -> None:
    """原型 04·9 已给名的 8 枚排在最前，顺序与原型一致（勋章墙第一行照原型画）。"""
    assert [spec.name for spec in badge_service.BADGES[:8]] == [
        "初次启程",
        "五连答对",
        "百题达成",
        "满分通关",
        "七日不辍",
        "深夜求知",
        "卷轴百卷",
        "神秘成就",
    ]


def test_prototype_tiers_are_kept() -> None:
    """原型里「百题达成」与「神秘成就」用的是稀有底（`.badge.rare`）。"""
    assert spec_of("hundred_questions").tier == "rare"
    assert spec_of(badge_service.SECRET_KEY).tier == "rare"


# -----------------------------------------------------------------------------
# 18 枚逐枚判定：满足 / 不满足
# -----------------------------------------------------------------------------
# (键, 满足它的事实, 不满足它的事实)
CASES: list[tuple[str, BadgeFacts, BadgeFacts]] = [
    ("first_quest", with_facts(attempt_count=1), with_facts(attempt_count=0)),
    ("five_in_a_row", with_facts(best_correct_streak=5), with_facts(best_correct_streak=4)),
    ("hundred_questions", with_facts(answered_count=100), with_facts(answered_count=99)),
    ("perfect_clear", with_facts(perfect_attempt=True), with_facts(perfect_attempt=False)),
    ("seven_day_streak", with_facts(longest_streak=7), with_facts(longest_streak=6)),
    # 深夜：22:00–次日 2:00（右开）。1 点在区间内，2 点已出界
    ("midnight_learner", with_facts(finished_hour=1), with_facts(finished_hour=2)),
    ("hundred_scrolls", with_facts(attempt_count=100), with_facts(attempt_count=99)),
    ("scroll_collector", with_facts(distinct_quiz_titles=10), with_facts(distinct_quiz_titles=9)),
    ("multiple_master", with_facts(multiple_perfect_total=10), with_facts(multiple_perfect_total=9)),
    ("judge_master", with_facts(judge_perfect_streak=20), with_facts(judge_perfect_streak=19)),
    ("wrong_question_slayer", with_facts(mastered_wrong_count=30), with_facts(mastered_wrong_count=29)),
    ("first_forest", with_facts(lit_points=1), with_facts(lit_points=0)),
    ("full_knowledge_tree", with_facts(lit_points=5), with_facts(lit_points=4)),
    ("fifty_a_day", with_facts(answers_today=50), with_facts(answers_today=49)),
    ("thirty_day_streak", with_facts(longest_streak=30), with_facts(longest_streak=29)),
    # 闪电通卷：满分 **且** 平均每题 < 5 秒（5.0 秒不算快）
    (
        "lightning_clear",
        with_facts(perfect_attempt=True, avg_seconds_per_question=4.99),
        with_facts(perfect_attempt=True, avg_seconds_per_question=5.0),
    ),    # 早起：6:00–8:00（右开）。7 点在区间内，8 点已出界
    ("early_riser", with_facts(finished_hour=7), with_facts(finished_hour=8)),
    (
        badge_service.SECRET_KEY,
        with_facts(unlocked_keys=OTHER_KEYS),
        with_facts(unlocked_keys=frozenset(list(OTHER_KEYS)[:16])),
    ),
]


@pytest.mark.parametrize("key,met,not_met", CASES, ids=[case[0] for case in CASES])
def test_badge_condition(key: str, met: BadgeFacts, not_met: BadgeFacts) -> None:
    spec = spec_of(key)

    assert spec.met(met) is True, f"{spec.name} 应当解锁"
    assert spec.met(not_met) is False, f"{spec.name} 不该解锁"


def test_every_badge_has_a_case() -> None:
    """新增勋章必须同时补一条用例 —— 这条守着的就是这个。"""
    covered = {case[0] for case in CASES}

    assert covered == {spec.key for spec in badge_service.BADGES}


@pytest.mark.parametrize("hour", [22, 23, 0, 1])
def test_midnight_window_is_inclusive(hour: int) -> None:
    assert spec_of("midnight_learner").met(with_facts(finished_hour=hour))


@pytest.mark.parametrize("hour", [10, 18, 20, 21, 2, 3])
def test_midnight_window_excludes_other_hours(hour: int) -> None:
    assert not spec_of("midnight_learner").met(with_facts(finished_hour=hour))


@pytest.mark.parametrize("hour", [6, 7])
def test_early_window_is_inclusive(hour: int) -> None:
    assert spec_of("early_riser").met(with_facts(finished_hour=hour))


@pytest.mark.parametrize("hour", [5, 8, 9, 12])
def test_early_window_excludes_other_hours(hour: int) -> None:
    assert not spec_of("early_riser").met(with_facts(finished_hour=hour))


def test_no_hour_means_time_based_badges_do_not_unlock() -> None:
    """`finished_hour=None` 表示「本次没有一局完成时刻可用」。

    这在手动读勋章时会发生。此时时间类勋章一律不解锁，
    **不能**把 None 当成 0 点 —— 那会让任何一次读取都误发「深夜求知」。
    """
    facts = with_facts(finished_hour=None)

    assert not spec_of("midnight_learner").met(facts)
    assert not spec_of("early_riser").met(facts)


def test_unknown_duration_does_not_unlock_lightning_clear() -> None:
    """用时未知 ≠ 很快。

    `avg_seconds_per_question` 的缺省值刻意是 `None` 而不是 `0.0`：
    后者会让「平均每题 < 5 秒」在任何没有本局的判定里无条件成立 ——
    0 秒当然小于 5 秒 —— 于是 18 枚里最难的这枚会白送给所有人。
    """
    assert BadgeFacts().avg_seconds_per_question is None
    assert not spec_of("lightning_clear").met(with_facts(perfect_attempt=True))
    assert not spec_of("lightning_clear").met(BadgeFacts())


# -----------------------------------------------------------------------------
# 从「本局判定」派生的事实
# -----------------------------------------------------------------------------
def signal(
    *pairs: tuple[str, str],
    seconds: float = 10.0,
    finished_at: datetime | None = None,
) -> AttemptSignal:
    """把 (题型, 判定) 序列转成一次结算信号。

    `finished_at` 是 naive UTC（与库列同口径），只在验证「完成小时按业务时区折算」
    时才需要显式传 —— 其余用例取当下即可。
    """
    return AttemptSignal(
        items=tuple(AttemptItem(question_type=t, outcome=o) for t, o in pairs),
        avg_seconds_per_question=seconds,
        finished_at=finished_at or utcnow(),
    )


def test_five_in_a_row_is_derived_from_item_order() -> None:
    """「连续 5 题全对」看的是**本局题序**上的最长连击数。"""
    facts = badge_service.facts_from_signal(
        signal(
            ("single", "wrong"),
            ("single", "correct"),
            ("single", "correct"),
            ("multiple", "correct"),
            ("judge", "correct"),
            ("judge", "correct"),
        )
    )

    assert facts.best_correct_streak == 5


def test_partial_breaks_the_streak() -> None:
    """多选题只选对一半不算答对 —— 连击必须断在这里。"""
    facts = badge_service.facts_from_signal(
        signal(("single", "correct"), ("multiple", "partial"), ("single", "correct"))
    )

    assert facts.best_correct_streak == 1


def test_perfect_attempt_requires_a_non_empty_session() -> None:
    """空局不叫满分 —— 否则任何异常的数据都会白送一枚「满分通关」。"""
    assert badge_service.facts_from_signal(signal()).perfect_attempt is False
    assert badge_service.facts_from_signal(signal(("single", "correct"))).perfect_attempt is True


def test_perfect_attempt_is_false_when_anything_is_unanswered() -> None:
    """未作答记 `wrong`，所以「全对」不可能与「有未作答」同时成立。"""
    facts = badge_service.facts_from_signal(signal(("single", "correct"), ("single", "wrong")))

    assert facts.perfect_attempt is False


# -----------------------------------------------------------------------------
# 解锁与幂等（走真库）
# -----------------------------------------------------------------------------
def make_user(session, openid: str = "openid-badge") -> User:
    user = User(openid=openid, nickname="冒险者 · 测试", avatar_key="scholar")
    session.add(user)
    session.flush()
    return user


def test_unlock_writes_rows_and_returns_new_keys(db_session) -> None:
    user = make_user(db_session)
    facts = with_facts(attempt_count=1, perfect_attempt=True, lit_points=1)

    newly = badge_service.unlock(db_session, user, facts=facts)
    db_session.commit()

    assert set(newly) == {"first_quest", "perfect_clear", "first_forest"}
    rows = db_session.query(UserBadge).filter(UserBadge.user_id == int(user.id)).all()
    assert {row.badge_key for row in rows} == set(newly)
    for row in rows:
        assert row.unlocked_at is not None


def test_unlock_is_idempotent(db_session) -> None:
    """重复触发不重复写、不重复返回 —— 否则勋章墙会重复弹窗。"""
    user = make_user(db_session)
    facts = with_facts(attempt_count=1)

    first = badge_service.unlock(db_session, user, facts=facts)
    db_session.commit()
    second = badge_service.unlock(db_session, user, facts=facts)
    db_session.commit()

    assert first == ["first_quest"]
    assert second == []
    assert db_session.query(UserBadge).count() == 1


def test_unlock_records_progress_snapshot(db_session) -> None:
    """`progress_snapshot` 记下解锁时的关键数字，用于将来解释「当时是什么水平」。"""
    user = make_user(db_session)

    badge_service.unlock(db_session, user, facts=with_facts(answered_count=100))
    db_session.commit()

    row = db_session.query(UserBadge).filter(UserBadge.badge_key == "hundred_questions").one()
    assert row.progress_snapshot["answered_count"] == 100


def test_secret_badge_unlocks_in_the_same_call_as_the_last_one(db_session) -> None:
    """17 枚已有、本次补上最后 1 枚 → 神秘成就必须**同一次**解锁。

    否则用户要再打一局才拿到它，而那一局与它毫无关系。
    """
    user = make_user(db_session)
    for key in sorted(OTHER_KEYS - {"first_forest"}):
        db_session.add(UserBadge(user_id=int(user.id), badge_key=key, unlocked_at=utcnow()))
    db_session.flush()

    newly = badge_service.unlock(db_session, user, facts=with_facts(lit_points=1))
    db_session.commit()

    assert set(newly) == {"first_forest", badge_service.SECRET_KEY}


def test_secret_badge_does_not_unlock_early(db_session) -> None:
    """缺任意一枚都拿不到它 —— 即使本次解锁了别的勋章。"""
    user = make_user(db_session)
    for key in sorted(OTHER_KEYS - {"first_forest", "perfect_clear"}):
        db_session.add(UserBadge(user_id=int(user.id), badge_key=key, unlocked_at=utcnow()))
    db_session.flush()

    # 本次点亮第 1 个领域 → 16 枚，仍差「满分通关」一枚
    newly = badge_service.unlock(db_session, user, facts=with_facts(lit_points=1))
    db_session.commit()

    assert newly == ["first_forest"]
    assert badge_service.SECRET_KEY not in newly


# -----------------------------------------------------------------------------
# 从库里收集事实
# -----------------------------------------------------------------------------
def seed_attempt(
    session,
    user: User,
    *,
    title: str = "RAG 入门闯关",
    types: tuple[str, ...] = ("single", "single", "judge"),
    outcomes: tuple[str, ...] = ("correct", "correct", "correct"),
    finished_at: datetime | None = None,
    total_count: int | None = None,
) -> Attempt:
    """造一局：卷轴 + 题目 + 挑战 + 逐题作答（都按最小必填字段填）。"""
    moment = finished_at or utcnow()
    quiz = QuizRecord(
        user_id=int(user.id),
        title=title,
        summary="测试用卷轴",
        source_type="text",
        source_name="测试输入",
        question_count=len(types),
        difficulty="mixed",
        status="ready",
    )
    session.add(quiz)
    session.flush()

    attempt = Attempt(
        user_id=int(user.id),
        quiz_id=int(quiz.id),
        attempt_no=1,
        started_at=moment,
        finished_at=moment,
        duration_ms=60_000,
        correct_count=sum(1 for o in outcomes if o == "correct"),
        wrong_count=sum(1 for o in outcomes if o == "wrong"),
        partial_count=sum(1 for o in outcomes if o == "partial"),
        total_count=total_count if total_count is not None else len(types),
        accuracy=0,
        max_xp=100,
        xp_gained=0,
        coins_gained=0,
        percentile=0,
        avg_seconds_per_question=10,
        status="finished",
    )
    session.add(attempt)
    session.flush()

    for seq, (qtype, outcome) in enumerate(zip(types, outcomes, strict=True), start=1):
        options = (
            [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]
            if qtype == "judge"
            else [
                {"key": "A", "text": "选项 A"},
                {"key": "B", "text": "选项 B"},
                {"key": "C", "text": "选项 C"},
            ]
        )
        question = QuestionRecord(
            quiz_id=int(quiz.id),
            seq=seq,
            type=qtype,
            stem=f"第 {seq} 题",
            options=options,
            answer=["T"] if qtype == "judge" else ["A"],
            explanation="讲解",
            knowledge_point="RAG 基本定义",
            difficulty="easy",
        )
        session.add(question)
        session.flush()
        session.add(
            Answer(
                attempt_id=int(attempt.id),
                question_id=int(question.id),
                selected=["A"],
                outcome=outcome,
                earned_xp=0,
                max_xp=0,
                time_spent_ms=1000,
                answered_at=moment,
            )
        )
    session.flush()
    return attempt


def test_collect_facts_reads_cumulative_state(db_session) -> None:
    user = make_user(db_session)
    seed_attempt(db_session, user, title="卷轴 A")
    second = seed_attempt(
        db_session, user, title="卷轴 B", types=("multiple",), outcomes=("correct",)
    )
    # 错题本按「原题」记，所以这里必须用真实存在的题目 id（外键）
    question_id = db_session.query(Answer).filter(Answer.attempt_id == int(second.id)).one().question_id
    db_session.add(
        WrongQuestion(
            user_id=int(user.id),
            question_id=int(question_id),
            wrong_count=1,
            stage=2,
            next_review_at=utcnow(),
            last_wrong_at=utcnow(),
            mastered=True,
        )
    )
    db_session.flush()

    facts = badge_service.collect_facts(db_session, user)

    assert facts.attempt_count == 2
    assert facts.answered_count == 4
    assert facts.distinct_quiz_titles == 2
    assert facts.multiple_perfect_total == 1
    assert facts.mastered_wrong_count == 1


def test_collect_facts_counts_only_the_users_own_rows(db_session) -> None:
    """另一个用户的数据绝不能进到我的勋章判定里。"""
    me = make_user(db_session, openid="openid-me")
    other = make_user(db_session, openid="openid-other")
    seed_attempt(db_session, other)

    facts = badge_service.collect_facts(db_session, me)

    assert facts.attempt_count == 0
    assert facts.answered_count == 0
    assert facts.distinct_quiz_titles == 0


def test_judge_streak_is_broken_by_an_older_wrong_answer(db_session) -> None:
    user = make_user(db_session)
    old = utcnow().replace(year=2020)
    seed_attempt(db_session, user, types=("judge",), outcomes=("wrong",), finished_at=old)
    seed_attempt(db_session, user, types=("judge",), outcomes=("correct",))

    facts = badge_service.collect_facts(db_session, user)

    assert facts.judge_perfect_streak == 1


def test_judge_streak_ignores_other_question_types(db_session) -> None:
    """连对 20 道判断题，用的是判断题；中间夹杂的单选不该把它打断。"""
    user = make_user(db_session)
    seed_attempt(
        db_session,
        user,
        types=("judge", "single", "judge"),
        outcomes=("correct", "wrong", "correct"),
    )

    facts = badge_service.collect_facts(db_session, user)

    assert facts.judge_perfect_streak == 2


def test_finished_hour_uses_business_timezone() -> None:
    """业务时区 23:00 完成的一局 = UTC 15:00 —— 必须按 23 判，不能按 15。

    小时取自**本局**（有 `AttemptSignal` 时才有值）。不用库里的历史记录兜底：
    那会让「没有本局」的读取也拿到一个完成小时，时间类勋章的语义就散了。
    """
    facts = badge_service.facts_from_signal(
        signal(("single", "correct"), finished_at=datetime(2026, 9, 18, 15, 0, 0))
    )

    assert facts.finished_hour == 23


def test_signal_without_finished_at_hour_stays_none() -> None:
    """`collect_facts` 在没有本局信号时不猜完成小时。"""
    assert BadgeFacts().finished_hour is None


def test_answers_today_counts_only_the_business_day(db_session) -> None:
    """「今天」按业务时区算，业务日边界之前的一瞬属于昨天。

    UTC 16:00 其实是北京时间**次日** 0 点，所以「今天」绝不能按 UTC 日期切 ——
    这也是 `business_day_bounds` 存在的原因。
    """
    from datetime import timedelta

    from app.utils.timeutil import business_date, business_day_bounds

    user = make_user(db_session)
    start, _ = business_day_bounds(business_date())
    seed_attempt(
        db_session,
        user,
        types=("single", "judge"),
        outcomes=("correct", "wrong"),
        finished_at=start,
    )
    seed_attempt(
        db_session,
        user,
        types=("single",),
        outcomes=("correct",),
        finished_at=start - timedelta(milliseconds=1),
    )

    facts = badge_service.collect_facts(db_session, user)

    assert facts.answers_today == 2, "只有落在今天那一局的两道题该被算进来"


def test_attempt_signal_overrides_derived_facts(db_session) -> None:
    """传了本局信号时，满分 / 连击 / 完成小时都取自本局。"""
    user = make_user(db_session)

    facts = badge_service.collect_facts(
        db_session, user, signal=signal(("single", "correct"), ("single", "correct"))
    )

    assert facts.perfect_attempt is True
    assert facts.best_correct_streak == 2
    assert facts.finished_hour is not None


# -----------------------------------------------------------------------------
# 勋章墙读取
# -----------------------------------------------------------------------------
def test_list_badges_returns_all_with_state(db_session) -> None:
    user = make_user(db_session)
    db_session.add(
        UserBadge(user_id=int(user.id), badge_key="first_quest", unlocked_at=utcnow())
    )
    db_session.flush()

    payload = badge_service.list_badges(db_session, user)

    assert payload.unlocked_count == 1
    assert payload.total == BADGE_TOTAL
    assert len(payload.items) == BADGE_TOTAL
    # 顺序即注册表顺序 —— 勋章墙按它排布，前端不重排
    assert [item.key for item in payload.items] == [spec.key for spec in badge_service.BADGES]

    first = payload.items[0]
    assert first.key == "first_quest"
    assert first.unlocked is True
    assert first.name == "初次启程"
    assert first.unlocked_at is not None

    locked = [item for item in payload.items if not item.unlocked]
    assert len(locked) == BADGE_TOTAL - 1
    # 未解锁的也要有名字与条件：原型要求「保留轮廓与名称，让用户知道还有什么可追求」
    assert all(item.name and item.desc for item in locked)
    assert all(item.unlocked_at is None for item in locked)


# =============================================================================
# 结算接入：勋章在 `POST /attempts` 里解锁
# =============================================================================
# 上面测的是「引擎算得对」，这里测的是「引擎真的被结算调用了」。
# 两者都必要：条件写对但没人调用的引擎，用户一枚勋章也拿不到。
#
# 这里用 HTTP 造数（不走 `db_session` 直插）——勋章的出现时机依赖结算内部
# 各步的顺序（成长体系先写、勋章后判），只有走真实路径才能验证那个顺序。


def unlocked_keys(client, headers) -> set[str]:
    body = client.get("/api/v1/users/me/badges", headers=headers).json()["data"]
    return {item["key"] for item in body["items"] if item["unlocked"]}


#: 默认交卷时刻：**昨天 10:00**（业务时区）。
#:
#: 为什么不能用 `at(0)`（今天 10:00）：`POST /attempts` 的 `_resolve_timing` 会把
#: **晚于服务端当前时刻**的 `finished_at` 夹到「现在」。今天 10:00 在上午 10 点之前
#: 都属于「未来」，一夹就变成了「测试跑在哪一刻」—— 本局完成小时不再是稳定的 10 点，
#: 而是随墙钟漂移，于是下面那条**反面**断言（普通时刻不该拿时间类勋章）只在一天中的
#: 部分时段成立：
#:   · 业务时间 00:00–02:00 跑 → 夹到 0/1 点 → 落进「深夜求知」（22–2 右开）窗口
#:   · 业务时间 06:00–08:00 跑 → 夹到 6/7 点 → 落进「早起冒险者」（6–8 右开）窗口
#: 取**昨天** 10:00：永远早于当前时刻（`min` 恒等，不会被夹），且离两个窗口都很远。
#: 见 `test_default_settlement_moment_is_always_in_the_past`。
SETTLED_AT = at(-1, hour=10)


def settle_one(
    client,
    session,
    headers,
    *,
    outcomes: tuple[str, ...] = ("wrong",),
    finished_at: datetime | None = None,
    client_token: str | None = None,
) -> dict:
    """建一份与 `outcomes` 等长的卷轴并结算一局。

    `finished_at` 缺省用 `SETTLED_AT` 而不是「今天」—— 理由见该常量的说明：
    只有当交卷时刻**必定已过去**时，完成小时才是可预期的。
    """
    quiz = make_quiz(
        session,
        current_user_id(client, headers),
        kps=tuple(f"领域{index}" for index in range(len(outcomes))),
    )
    return settle(
        client,
        headers,
        session,
        quiz,
        outcomes=outcomes,
        finished_at=finished_at or SETTLED_AT,
        client_token=client_token,
    )


def test_first_settlement_unlocks_first_quest(db_client, db_session, auth_headers) -> None:
    """首局结算解锁「初次启程」，并且**这次响应里就带着它**。

    `new_badges` 若是空的，前端就没法在结算页弹「新勋章」——用户要退出去
    翻勋章墙才发现，那时惊喜已经没了。
    """
    result = settle_one(db_client, db_session, auth_headers)

    assert "first_quest" in result["new_badges"]
    assert "first_quest" in unlocked_keys(db_client, auth_headers)


def test_new_badges_is_empty_when_nothing_new_is_unlocked(
    db_client, db_session, auth_headers
) -> None:
    """第二次结算不重复返回已解锁的勋章 —— 否则每次交卷都弹一次「新勋章」。"""
    first = settle_one(db_client, db_session, auth_headers)
    second = settle_one(db_client, db_session, auth_headers)

    assert "first_quest" in first["new_badges"]
    assert second["new_badges"] == []


def test_perfect_settlement_unlocks_perfect_clear(db_client, db_session, auth_headers) -> None:
    """单局全对 → 「满分通关」。它靠的是**本局信号**，不是累计状态。"""
    result = settle_one(
        db_client, db_session, auth_headers, outcomes=("correct", "correct")
    )

    assert "perfect_clear" in result["new_badges"]


def test_new_badges_are_returned_in_registry_order(db_client, db_session, auth_headers) -> None:
    """顺序即注册表顺序 —— 结算页按它依次弹出，前端不重排。"""
    result = settle_one(db_client, db_session, auth_headers)

    order = [spec.key for spec in badge_service.BADGES]
    positions = [order.index(key) for key in result["new_badges"]]
    assert positions == sorted(positions)


def test_settlement_reads_the_finish_hour_in_business_timezone(
    db_client, db_session, auth_headers
) -> None:
    """业务时区 23:00 交卷 → 解锁「深夜求知」。用 UTC 小时判会永远发不出去。

    23:00（UTC+8）等于同日 15:00 UTC，而 15 不在 22–2 的窗口里。

    刻意用**昨天** 23:00：交卷时刻晚于服务端当前时间时会被夹到「现在」
    （`_resolve_timing`），今天 23:00 在白天跑测试时还没到，会被夹走。
    """
    result = settle_one(db_client, db_session, auth_headers, finished_at=at(-1, hour=23))

    assert "midnight_learner" in result["new_badges"]


def test_settlement_does_not_unlock_time_badges_at_an_ordinary_hour(
    db_client, db_session, auth_headers
) -> None:
    """反面：一个普通时刻交卷不该拿到「深夜求知」或「早起冒险者」——否则判定是恒真的。

    ⚠️ 这条断言曾经**只在一天中的部分时段成立**：默认交卷时刻是「今天 10:00」，
    上午 10 点前它是未来时刻，被 `_resolve_timing` 夹到「现在」；若此刻恰在
    00:00–02:00 或 06:00–08:00，夹出来的完成小时就落进了时间窗口。现在默认取
    昨天 10:00（`SETTLED_AT`），与运行时刻无关。
    """
    result = settle_one(db_client, db_session, auth_headers)

    assert "midnight_learner" not in result["new_badges"]
    assert "early_riser" not in result["new_badges"]


def test_default_settlement_moment_is_always_in_the_past() -> None:
    """守住 `SETTLED_AT` 的两个不变量 —— 它们才是上面那条反面断言的前提。

    1. **必定已过去**：否则 `_resolve_timing` 的 `min(..., now)` 会把它夹到「现在」，
       完成小时变成「测试跑在哪一刻」。
    2. **不在任何时间窗口内**：万一将来有人把它改成别的时刻，也不该恰好落在
       22–2 或 6–8 里。

    第 1 条正是这次修掉的脆弱点：把 `SETTLED_AT` 换回 `at(0)`，本用例会在
    上午 10 点之前失败 —— 这就是一个跑得出来、且不需要等半夜的回归守门。
    """
    assert SETTLED_AT < utcnow(), "默认交卷时刻落在未来，会被夹到「现在」"

    hour = badge_service.facts_from_signal(
        signal(("single", "correct"), finished_at=SETTLED_AT)
    ).finished_hour
    assert hour is not None
    assert not spec_of("midnight_learner").met(with_facts(finished_hour=hour))
    assert not spec_of("early_riser").met(with_facts(finished_hour=hour))


def test_replaying_a_submission_does_not_unlock_anything(
    db_client, db_session, auth_headers
) -> None:
    """重复提交（同一 `client_token`）返回 `new_badges=[]`，也不重复落库。

    回放走的是**另一段**组装代码（从库里重建响应），很容易被漏掉 ——
    漏掉的症状是「网络抖动重试一次，结算页又弹一遍同样的勋章」。
    """
    # 交卷令牌必须能通过 UUID 形状校验（客户端生成的本来就是 UUID）
    token = "11111111-1111-1111-1111-111111111111"
    settle_one(db_client, db_session, auth_headers, client_token=token)
    replay = settle_one(db_client, db_session, auth_headers, client_token=token)

    assert replay["duplicate"] is True
    assert replay["new_badges"] == []
    assert unlocked_keys(db_client, auth_headers) == {"first_quest"}
