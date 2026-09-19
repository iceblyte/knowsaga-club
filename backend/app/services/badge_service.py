"""勋章规则引擎（方案设计 §8.6 的 18 枚）。

## 为什么勋章定义放在代码里而不是建一张表

解锁条件需要**代码表达** —— 「单局满分**且**平均每题 < 5 秒」这种条件，
塞进表里只能存一段字符串再解释它，等于自造一套 DSL，还得为它写解析器与测试。
18 枚是稳定的，所以常量注册表是合适取舍（方案 §5.10 已裁决）。

副作用是新增勋章要改代码 + 发版。对单人开发、勋章集稳定的项目可以接受。

## 判定分两层：事实 → 条件

- `BadgeFacts` 是一份**事实快照**（累计局数、最长连击、完成时刻的小时……）
- `BadgeSpec.met` 是**纯函数**：`BadgeFacts -> bool`

这样拆开的好处直接体现在测试上：18 枚逐一验证只需构造一个 dataclass，
不需要为每一枚准备一整套库表数据。真正查库的地方只有 `collect_facts` 一处。

## 神秘成就必须在其余 17 枚之后判

它的条件是「其余 17 枚都解锁了」，所以判定时要把**本次刚解锁的那几枚**也算进去
（`unlocked_keys` 是探测值，不是库里的值）。顺序反了的话，用户打完第 17 枚时
拿不到它，要再打一局才补上 —— 而那一局与它毫无关系。

## 时间类勋章看的是**业务时区**的小时

「深夜求知 22:00–次日 2:00」指的是用户所在时区的 22 点。用 UTC 小时判会把
北京时间凌晨 1 点算成「下午 5 点」，这枚勋章就永远发给错的人。
窗口右开（22/23/0/1 在区间内，2 点出界），与原型「22:00–次日 2:00」的读法一致。

## 幂等与并发

`user_badges` 有 `UNIQUE(user_id, badge_key)`。这里的做法是**先查已解锁集合再插**，
并把唯一键当作兜底 —— 兜底真被触发时，整个结算事务会回滚（勋章与结算同事务），
客户端拿同一个 `client_token` 重试即可从零重跑，不会留下「结算成功但勋章丢了」的
半截状态。这比加一层 SAVEPOINT 更简单，且失败路径是可解释的。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.constants import BADGE_TOTAL
from app.db.tables import (
    Answer,
    Attempt,
    QuestionRecord,
    QuizRecord,
    User,
    UserBadge,
    UserKnowledgeStat,
    WrongQuestion,
)
from app.models.archive import BadgeItem, BadgeListResponse
from app.utils.timeutil import (
    as_aware_utc,
    business_date,
    business_day_bounds,
    business_tz,
    utcnow,
)

# -----------------------------------------------------------------------------
# 阈值（原型已给名的 8 枚取原型数字，其余 10 枚为方案 §8.6 的自拟值）
# -----------------------------------------------------------------------------
#: 单局内连续答对多少题 → 五连答对
STREAK_IN_ROW = 5
#: 累计答题多少道 → 百题达成
QUESTIONS_MILESTONE = 100
#: 连续多少天有挑战 → 七日不辍
STREAK_DAYS = 7
#: 「深夜求知」的窗口（业务时区小时，右开）
MIDNIGHT_HOURS = frozenset({22, 23, 0, 1})
#: 累计完成多少局 → 卷轴百卷
SCROLL_MILESTONE = 100
#: 多少张不同标题的卷轴 → 卷轴收藏家
TITLE_VARIETY = 10
#: 多选题全对累计多少次 → 多选高手
MULTIPLE_PERFECT_MILESTONE = 10
#: 判断题连续答对多少题 → 判断达人（也是扫描上限，见 `_judge_perfect_streak`）
JUDGE_STREAK = 20
#: 攻克多少道错题 → 错题终结者
MASTERED_MILESTONE = 30
#: 同时点亮多少个知识领域 → 知识树满枝
LIT_MILESTONE = 5
#: 单日答题多少道 → 一日千里
DAILY_QUESTIONS = 50
#: 连续多少天 → 月余不辍
LONG_STREAK_DAYS = 30
#: 「闪电通卷」的平均每题秒数上限（严格小于）
LIGHTNING_SECONDS = 5.0
#: 「早起冒险者」的窗口（业务时区小时，右开）
EARLY_HOURS = frozenset({6, 7})

#: 「神秘成就」的键。判定顺序依赖它，所以单独成常量而不是散在注册表里。
SECRET_KEY = "secret_achievement"


# -----------------------------------------------------------------------------
# 事实
# -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AttemptItem:
    """本局一道题的判定投影。勋章只看题型与结果两个字段。"""

    question_type: str
    outcome: str


@dataclass(frozen=True, slots=True)
class AttemptSignal:
    """一次结算里只有调用方知道的事实（本局逐题判定 + 用时 + 完成时刻）。"""

    items: tuple[AttemptItem, ...]
    avg_seconds_per_question: float
    #: naive UTC，与库里的列同一口径
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class BadgeFacts:
    """判定全部 18 枚所需的事实快照。默认值 = 「新用户，什么都没做过」。"""

    # ---- 累计（查库） ----
    attempt_count: int = 0
    answered_count: int = 0
    answers_today: int = 0
    multiple_perfect_total: int = 0
    judge_perfect_streak: int = 0
    distinct_quiz_titles: int = 0
    lit_points: int = 0
    longest_streak: int = 0
    mastered_wrong_count: int = 0

    # ---- 本局（来自 `AttemptSignal`；没有本局时为中性值） ----
    perfect_attempt: bool = False
    best_correct_streak: int = 0
    #: 本局平均每题秒数；`None` = **未知**（没有本局），不是「很快」。
    #: 用 0.0 当缺省会让「闪电通卷」（平均 < 5 秒）无条件成立 —— 见 `_lightning_clear`。
    avg_seconds_per_question: float | None = None
    #: 本局完成时刻的业务时区小时；`None` = 没有本局（手动读取时发生）
    finished_hour: int | None = None

    # ---- 探测值：仅用于判定「神秘成就」，不落库 ----
    unlocked_keys: frozenset[str] = frozenset()


# -----------------------------------------------------------------------------
# 注册表
# -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BadgeSpec:
    """一枚勋章的定义。`met` 是纯函数，便于逐枚单测。"""

    key: str
    name: str
    #: 解锁条件的一句话说明，勋章墙上显示在未解锁的那几枚下面
    desc: str
    #: 圆底上的单字（设计系统 `.badge` 用文字而不是图标）
    icon: str
    #: `gold` | `rare`；对应 `.badge` / `.badge.rare`
    tier: str
    met: Callable[[BadgeFacts], bool]


def _lightning_clear(facts: BadgeFacts) -> bool:
    """「单局满分且平均每题不到 5 秒」。

    单独成函数而不是一行 lambda，是因为这里有一个**必须显式处理**的情形：
    用时未知（`avg_seconds_per_question is None`，即没有本局）。

    若把未知当 0 秒，这枚勋章会在任何一次「没有本局」的判定里无条件成立 ——
    而它本该是 18 枚里最难拿的一枚。
    """
    if not facts.perfect_attempt:
        return False
    seconds = facts.avg_seconds_per_question
    return seconds is not None and seconds < LIGHTNING_SECONDS


#: 原型 04·9 已给名的 8 枚排在最前、顺序与原型一致 —— 勋章墙按注册表顺序排布。
BADGES: tuple[BadgeSpec, ...] = (
    BadgeSpec(
        "first_quest", "初次启程", "完成首局挑战", "启", "gold",
        lambda f: f.attempt_count >= 1,
    ),
    BadgeSpec(
        "five_in_a_row", "五连答对", "单局内连续 5 题全对", "连", "gold",
        lambda f: f.best_correct_streak >= STREAK_IN_ROW,
    ),
    BadgeSpec(
        "hundred_questions", "百题达成", "累计答题 100 道", "百", "rare",
        lambda f: f.answered_count >= QUESTIONS_MILESTONE,
    ),
    BadgeSpec(
        "perfect_clear", "满分通关", "单局全部答对", "满", "gold",
        lambda f: f.perfect_attempt,
    ),
    BadgeSpec(
        "seven_day_streak", "七日不辍", "连续 7 天有挑战记录", "七", "gold",
        lambda f: f.longest_streak >= STREAK_DAYS,
    ),
    BadgeSpec(
        "midnight_learner", "深夜求知", "22:00–次日 2:00 之间完成一局", "夜", "gold",
        lambda f: f.finished_hour in MIDNIGHT_HOURS,
    ),
    BadgeSpec(
        "hundred_scrolls", "卷轴百卷", "累计完成 100 局挑战", "卷", "gold",
        lambda f: f.attempt_count >= SCROLL_MILESTONE,
    ),
    # 注册表顺序 ≠ 判定顺序：这一枚在 `unlock()` 里被单独押到最后（见模块说明）
    BadgeSpec(
        SECRET_KEY, "神秘成就", "解锁其余 17 枚后自动获得", "秘", "rare",
        lambda f: len(f.unlocked_keys) >= BADGE_TOTAL - 1,
    ),
    BadgeSpec(
        "scroll_collector", "卷轴收藏家", "领取 10 张不同标题的卷轴", "藏", "gold",
        lambda f: f.distinct_quiz_titles >= TITLE_VARIETY,
    ),
    BadgeSpec(
        "multiple_master", "多选高手", "多选题全对累计 10 次", "多", "gold",
        lambda f: f.multiple_perfect_total >= MULTIPLE_PERFECT_MILESTONE,
    ),
    BadgeSpec(
        "judge_master", "判断达人", "判断题连续 20 题全对", "判", "gold",
        lambda f: f.judge_perfect_streak >= JUDGE_STREAK,
    ),
    BadgeSpec(
        "wrong_question_slayer", "错题终结者", "复习并攻克 30 道错题", "破", "gold",
        lambda f: f.mastered_wrong_count >= MASTERED_MILESTONE,
    ),
    BadgeSpec(
        "first_forest", "初见森林", "点亮第 1 个知识领域", "森", "gold",
        lambda f: f.lit_points >= 1,
    ),
    BadgeSpec(
        "full_knowledge_tree", "知识树满枝", "同时点亮 5 个知识领域", "枝", "rare",
        lambda f: f.lit_points >= LIT_MILESTONE,
    ),
    BadgeSpec(
        "fifty_a_day", "一日千里", "单日答题 50 道", "千", "gold",
        lambda f: f.answers_today >= DAILY_QUESTIONS,
    ),
    BadgeSpec(
        "thirty_day_streak", "月余不辍", "连续 30 天有挑战记录", "月", "rare",
        lambda f: f.longest_streak >= LONG_STREAK_DAYS,
    ),
    BadgeSpec(
        "lightning_clear", "闪电通卷", "单局满分且平均每题不到 5 秒", "闪", "rare",
        _lightning_clear,
    ),
    BadgeSpec(
        "early_riser", "早起冒险者", "6:00–8:00 之间完成一局", "晨", "gold",
        lambda f: f.finished_hour in EARLY_HOURS,
    ),
)

#: 按 key 取定义（`unlock` 判神秘成就、接口层按 key 转名称都用它）
BADGE_BY_KEY: dict[str, BadgeSpec] = {spec.key: spec for spec in BADGES}


# -----------------------------------------------------------------------------
# 事实收集
# -----------------------------------------------------------------------------
def facts_from_signal(signal: AttemptSignal) -> BadgeFacts:
    """从「本局」派生出那部分事实（满分 / 最长连击 / 平均秒数 / 完成小时）。

    空局不算满分：`perfect_attempt` 要求题量 > 0。否则一份异常的空卷轴会白送
    一枚「满分通关」——「全部答对」在零道题上是没有意义的真命题。
    """
    outcomes = [item.outcome for item in signal.items]
    return BadgeFacts(
        perfect_attempt=bool(outcomes) and all(outcome == "correct" for outcome in outcomes),
        best_correct_streak=_best_correct_streak(outcomes),
        avg_seconds_per_question=float(signal.avg_seconds_per_question),
        finished_hour=_business_hour(signal.finished_at),
    )


def collect_facts(
    session: Session,
    user: User,
    *,
    signal: AttemptSignal | None = None,
    now: datetime | None = None,
) -> BadgeFacts:
    """把「这个用户到此刻为止是什么状态」查成一份事实快照。

    传 `signal` 时把本局那部分叠加上去。**查询全部按 `user_id` 过滤** ——
    少一处过滤就会把别人的数据算成自己的勋章，而这类错误在界面上看不出来。

    Args:
        session: 直连会话。
        user: 已加载的用户行（`longest_streak` 由 `growth_service` 在本事务内更新过）。
        signal: 本次结算的本局信号；手动读取时不传。
        now: 判定「今天」用的时刻；不传取 `utcnow()`。测试用它固定时间。
    """
    user_id = int(user.id)
    moment = now or utcnow()
    start, end = business_day_bounds(business_date(moment))

    base = facts_from_signal(signal) if signal is not None else BadgeFacts()

    return dataclasses.replace(
        base,
        attempt_count=_count(
            session, select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id)
        ),
        answered_count=_answers_query(session, user_id=user_id),
        answers_today=_answers_query(session, user_id=user_id, start=start, end=end),
        multiple_perfect_total=_count(
            session,
            select(func.count())
            .select_from(Answer)
            .join(Attempt, Answer.attempt_id == Attempt.id)
            .join(QuestionRecord, Answer.question_id == QuestionRecord.id)
            .where(
                Attempt.user_id == user_id,
                QuestionRecord.type == "multiple",
                Answer.outcome == "correct",
            ),
        ),
        judge_perfect_streak=_judge_perfect_streak(session, user_id=user_id),
        distinct_quiz_titles=_count(
            session,
            select(func.count(distinct(QuizRecord.title))).where(
                QuizRecord.user_id == user_id
            ),
        ),
        lit_points=_count(
            session,
            select(func.count())
            .select_from(UserKnowledgeStat)
            .where(UserKnowledgeStat.user_id == user_id, UserKnowledgeStat.lit.is_(True)),
        ),
        # 连续天数直接读用户行：`growth_service` 已经在同一事务里算完并写好了。
        # 这里不重算 —— 重算会变成两处实现，而它们迟早会在边界上分叉。
        longest_streak=int(user.longest_streak),
        mastered_wrong_count=_count(
            session,
            select(func.count())
            .select_from(WrongQuestion)
            .where(WrongQuestion.user_id == user_id, WrongQuestion.mastered.is_(True)),
        ),
    )


def _judge_perfect_streak(session: Session, *, user_id: int) -> int:
    """从最近的一次判断题作答往前数连续答对数。

    **扫描上限恰好是阈值（20）**：只需要知道它有没有到 20，所以取最近 20 条
    判断题的判定就足够 —— 全部答对即达成，否则一定不到。这样这道查询与
    「用户总共做了多少题」无关，数据量增长也不会让它变慢。

    排序用 `finished_at DESC, seq DESC` 而不是 `answered_at`：同一局里所有作答行
    的 `answered_at` 是同一个时刻，用它排序会给出不确定的顺序，连击数就成了随机值。
    """
    outcomes = session.scalars(
        select(Answer.outcome)
        .join(Attempt, Answer.attempt_id == Attempt.id)
        .join(QuestionRecord, Answer.question_id == QuestionRecord.id)
        .where(Attempt.user_id == user_id, QuestionRecord.type == "judge")
        .order_by(Attempt.finished_at.desc(), QuestionRecord.seq.desc())
        .limit(JUDGE_STREAK)
    ).all()

    streak = 0
    for outcome in outcomes:
        if outcome != "correct":
            break
        streak += 1
    return streak


# -----------------------------------------------------------------------------
# 解锁
# -----------------------------------------------------------------------------
def evaluate_after_attempt(
    session: Session,
    user: User,
    *,
    signal: AttemptSignal,
    now: datetime | None = None,
) -> list[str]:
    """结算后判定并写入新解锁的勋章，返回**本次新解锁**的键（按注册表顺序）。

    调用方负责事务边界（本函数只 flush）—— 勋章必须与结算同成同败。
    """
    facts = collect_facts(session, user, signal=signal, now=now)
    return unlock(session, user, facts=facts, now=now)


def unlock(
    session: Session,
    user: User,
    *,
    facts: BadgeFacts,
    now: datetime | None = None,
) -> list[str]:
    """按事实解锁勋章（幂等）。返回本次新解锁的键。"""
    moment = now or utcnow()
    user_id = int(user.id)
    existing = {
        str(key)
        for key in session.scalars(
            select(UserBadge.badge_key).where(UserBadge.user_id == user_id)
        ).all()
    }

    newly: list[str] = []
    for spec in BADGES:
        if spec.key == SECRET_KEY or spec.key in existing:
            continue
        if spec.met(facts):
            _add(session, user_id=user_id, spec=spec, moment=moment, facts=facts)
            newly.append(spec.key)

    # 神秘成就最后判：探测值里要含**本次刚解锁的**那几枚
    secret = BADGE_BY_KEY[SECRET_KEY]
    if secret.key not in existing:
        probe = dataclasses.replace(facts, unlocked_keys=frozenset(existing | set(newly)))
        if secret.met(probe):
            _add(session, user_id=user_id, spec=secret, moment=moment, facts=facts)
            newly.append(secret.key)

    session.flush()
    return newly


def _add(
    session: Session,
    *,
    user_id: int,
    spec: BadgeSpec,
    moment: datetime,
    facts: BadgeFacts,
) -> None:
    session.add(
        UserBadge(
            user_id=user_id,
            badge_key=spec.key,
            unlocked_at=moment,
            progress_snapshot=_snapshot(facts),
        )
    )


def _snapshot(facts: BadgeFacts) -> dict[str, object]:
    """解锁时刻的关键数字。

    为什么不存整份 `BadgeFacts`：`unlocked_keys` 是探测值、`finished_hour` 是
    一次性的，存下来只会让人误以为它们是持久事实。这里只留能被事后解释的量。
    """
    return {
        "attempt_count": int(facts.attempt_count),
        "answered_count": int(facts.answered_count),
        "answers_today": int(facts.answers_today),
        "multiple_perfect_total": int(facts.multiple_perfect_total),
        "judge_perfect_streak": int(facts.judge_perfect_streak),
        "distinct_quiz_titles": int(facts.distinct_quiz_titles),
        "lit_points": int(facts.lit_points),
        "longest_streak": int(facts.longest_streak),
        "mastered_wrong_count": int(facts.mastered_wrong_count),
        "best_correct_streak": int(facts.best_correct_streak),
        "perfect_attempt": bool(facts.perfect_attempt),
        "avg_seconds_per_question": (
            None
            if facts.avg_seconds_per_question is None
            else round(float(facts.avg_seconds_per_question), 2)
        ),
        "finished_hour": facts.finished_hour,
    }


# -----------------------------------------------------------------------------
# 勋章墙读取
# -----------------------------------------------------------------------------
def list_badges(session: Session, user: User) -> BadgeListResponse:
    """全部 18 枚 + 解锁状态（原型 04·9）。

    未解锁的也**必须**返回名称与条件 —— 原型图注明确要求「保留轮廓与名称，
    让用户知道还有什么可以追求」，只回已解锁的会让勋章墙变成一块越来越满的墙。
    """
    user_id = int(user.id)
    unlocked_at = {
        str(row.badge_key): row.unlocked_at
        for row in session.scalars(
            select(UserBadge).where(UserBadge.user_id == user_id)
        ).all()
    }

    items = [
        BadgeItem(
            key=spec.key,
            name=spec.name,
            desc=spec.desc,
            icon=spec.icon,
            tier=spec.tier,
            unlocked=spec.key in unlocked_at,
            unlocked_at=unlocked_at.get(spec.key),
        )
        for spec in BADGES
    ]

    return BadgeListResponse(
        unlocked_count=sum(1 for item in items if item.unlocked),
        total=BADGE_TOTAL,
        items=items,
    )


# -----------------------------------------------------------------------------
# 内部工具
# -----------------------------------------------------------------------------
def _count(session: Session, stmt) -> int:  # noqa: ANN001 - Select
    """`SELECT COUNT(...)` 的薄封装。"""
    return int(session.scalar(stmt) or 0)


def _answers_query(
    session: Session,
    *,
    user_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    """数作答**行数**（可按所属挑战的完成时刻区间过滤）。

    按行数而不是 `attempts.total_count` 求和：题目未作答也会落一行 0 分的记录
    （卷轴详情页要逐题展示），两者在正常路径上相等；但「答题量」这个说法指的
    是用户真的做了多少题，数行更贴近它的本意。
    """
    stmt = (
        select(func.count())
        .select_from(Answer)
        .join(Attempt, Answer.attempt_id == Attempt.id)
        .where(Attempt.user_id == user_id)
    )
    if start is not None and end is not None:
        stmt = stmt.where(Attempt.finished_at >= start, Attempt.finished_at < end)
    return _count(session, stmt)


def _best_correct_streak(outcomes: Sequence[str]) -> int:
    best = 0
    run = 0
    for outcome in outcomes:
        run = run + 1 if outcome == "correct" else 0
        best = max(best, run)
    return best


def _business_hour(moment: datetime) -> int:
    """naive UTC -> 业务时区的小时。"""
    return as_aware_utc(moment).astimezone(business_tz()).hour
