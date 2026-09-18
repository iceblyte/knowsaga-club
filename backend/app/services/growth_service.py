"""成长体系的数据写入：经验、连续天数、金币、错题队列、知识领域统计。

## 为什么和 `attempt_service` 分开

`attempt_service` 回答的是「这一局打了多少分」（把选择变成分数），
本文件回答的是「这些分数对档案做了什么」（把分数变成长期状态）。
两者的失败模式完全不同：前者错了是算错分，后者错了是档案里的数字悄悄不对，
而档案是用户唯一能看见的「我进步了」的证据。

## 「今天」一律是业务时区的日期

`business_date()` 而不是 UTC 日期。用 UTC 判日的话，北京时间晚上 8 点之后的
学习会被算到第二天 —— 连续天数会莫名断掉，而用户完全无从理解（方案 §8.7）。

## 迟到的记录不会倒退连续天数

`finished_at` 来自客户端，理论上可以是一周前。所以更新 `last_active_date` 时
要判方向：**只在「这次的活动日期不早于已有记录」时才推进**。否则补交一次
旧记录就会把连续天数打回 1。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    MASTERY_LIT_THRESHOLD,
    REVIEW_INTERVALS_DAYS,
    REVIEW_MASTERED_STAGE,
)
from app.core.logging import get_logger
from app.db.tables import User, UserKnowledgeStat, WrongQuestion
from app.services import scoring
from app.utils.timeutil import add_days, business_date, utcnow

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GradedItem:
    """一道题的判定结果在成长体系里的投影。

    只带成长体系真正需要的三个字段。**刻意不复用 `AttemptAnswerResult`**：
    那个契约是给前端看的，字段会随界面变；成长规则不该被界面的字段增删牵动。
    """

    question_id: int
    outcome: str
    knowledge_point: str


@dataclass(frozen=True, slots=True)
class GrowthOutcome:
    """本次结算对档案做了什么，供响应体与测试读取。"""

    streak_days: int
    longest_streak: int
    wrong_queued_count: int
    lit_knowledge_points: int


def apply_attempt(
    session: Session,
    user: User,
    *,
    items: list[GradedItem],
    xp_gained: int,
    coins_gained: int,
    finished_at: datetime,
    now: datetime | None = None,
) -> GrowthOutcome:
    """把一局的结果写进档案。

    调用方负责事务边界（本函数只 flush/不 commit），这样「结算」整体要么全成，
    要么全不成 —— 出现过「XP 加了但错题没入队」这种半截状态，
    用户看到的就是档案自相矛盾。

    Args:
        session: 直连会话。
        user: 已加载的用户行（会被就地修改）。
        items: 逐题判定投影。
        xp_gained: 本局获得经验。
        coins_gained: 本局获得金币。
        finished_at: 本局结束时刻（naive UTC），用于判「今天」。
        now: 写入时刻；不传取 `utcnow()`。测试用它固定时间。
    """
    moment = now or utcnow()
    active_date = business_date(finished_at)

    _apply_xp_and_coins(user, xp_gained=xp_gained, coins_gained=coins_gained)
    streak, longest = _apply_streak(user, active_date=active_date)
    _touch(user, moment)

    queued = _queue_wrong_questions(session, user_id=int(user.id), items=items, now=moment)
    lit = _update_knowledge_stats(session, user_id=int(user.id), items=items, now=moment)

    return GrowthOutcome(
        streak_days=streak,
        longest_streak=longest,
        wrong_queued_count=queued,
        lit_knowledge_points=lit,
    )


# -----------------------------------------------------------------------------
# 经验、金币、连续天数
# -----------------------------------------------------------------------------
def _apply_xp_and_coins(user: User, *, xp_gained: int, coins_gained: int) -> None:
    """累加经验与金币。

    只做加法、**不做上限截断**：`xp_total` 列的 `INT UNSIGNED` 上限是
    42 亿，而一局最多 200 XP —— 要撞上限需要两千万局。
    这里不设人为天花板，是因为「经验上限」属于玩法设计，不属于防御性编程。
    """
    user.xp_total = int(user.xp_total) + max(0, int(xp_gained))
    user.coins = int(user.coins) + max(0, int(coins_gained))


def _apply_streak(user: User, *, active_date: date) -> tuple[int, int]:
    """按「上一次活动日期」推进连续天数（方案 §8.8）。

    ```
    同一天        → 不变
    正好是昨天    → +1
    更早 / 为空   → 重置为 1
    比已有记录更早 → 不变（迟到的旧记录）
    ```

    Returns:
        `(当前连续天数, 历史最长连续天数)`
    """
    last: date | None = user.last_active_date
    streak = int(user.streak_days)
    longest = int(user.longest_streak)

    if last is None:
        streak = 1
    elif active_date == last:
        # 今天已经打过卡了，不再累加
        streak = max(streak, 1)
    elif active_date > last:
        streak = streak + 1 if (active_date - last).days == 1 else 1
    else:
        # 迟到的一次补交：它属于过去，不该改写现在的连续天数
        logger.info(
            "用户 %s 补交了一次更早的记录（%s < %s），连续天数保持不变",
            user.id,
            active_date,
            last,
        )
        return streak, longest

    longest = max(longest, streak)
    user.streak_days = streak
    user.longest_streak = longest
    user.last_active_date = active_date
    return streak, longest


def _touch(user: User, moment: datetime) -> None:
    user.updated_at = moment


# -----------------------------------------------------------------------------
# 错题队列（方案 §8.4）
# -----------------------------------------------------------------------------
def _queue_wrong_questions(
    session: Session,
    *,
    user_id: int,
    items: list[GradedItem],
    now: datetime,
) -> int:
    """维护错题本，返回本次「因答错而（重新）入队」的题数。

    规则（间隔表见 `core.constants.REVIEW_INTERVALS_DAYS`）：

    - **答错 / 部分正确** → `wrong_count + 1`，阶段**回到 0**，
      下次到期 = 现在 + 1 天。（部分正确也入队：多选题少选说明掌握不牢。）
    - **答对且已在队列里** → 阶段 +1，下次到期按新阶段的间隔；
      阶段达到 `REVIEW_MASTERED_STAGE`（连续两次答对）即移出队列。
    - **答对但不在队列里** → 什么也不做。答对一道从来没做错过的题
      不该在错题本里凭空出现一行。
    """
    queued = 0
    for item in items:
        row = _get_wrong_question(session, user_id=user_id, question_id=item.question_id)

        if item.outcome != "correct":
            if row is None:
                row = WrongQuestion(
                    user_id=user_id,
                    question_id=item.question_id,
                    wrong_count=1,
                    stage=0,
                    next_review_at=add_days(now, REVIEW_INTERVALS_DAYS[0]),
                    last_review_at=None,
                    last_wrong_at=now,
                    mastered=False,
                )
                session.add(row)
            else:
                row.wrong_count = int(row.wrong_count) + 1
                # 阶段归零是这套规则的核心：一次答错就重新开始，而不是「稳步前进」
                row.stage = 0
                row.next_review_at = add_days(now, REVIEW_INTERVALS_DAYS[0])
                row.last_wrong_at = now
                row.mastered = False
            row.updated_at = now
            queued += 1
            continue

        if row is None:
            continue

        stage = min(int(row.stage) + 1, len(REVIEW_INTERVALS_DAYS) - 1)
        row.stage = stage
        row.last_review_at = now
        row.next_review_at = add_days(now, REVIEW_INTERVALS_DAYS[stage])
        if stage >= REVIEW_MASTERED_STAGE:
            row.mastered = True
        row.updated_at = now

    session.flush()
    return queued


def _get_wrong_question(session: Session, *, user_id: int, question_id: int) -> WrongQuestion | None:
    return session.scalar(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.question_id == question_id,
        )
    )


# -----------------------------------------------------------------------------
# 知识领域统计（方案 §8.3）
# -----------------------------------------------------------------------------
def _update_knowledge_stats(
    session: Session,
    *,
    user_id: int,
    items: list[GradedItem],
    now: datetime,
) -> int:
    """累加各知识领域的答题与正确数，返回本局**新点亮**的领域数。

    `mastery = round(correct_count / total_count × 100)`，
    `≥ 90` 置 `lit`。

    `total_count` 与 `correct_count` 都只按**实际作答过的题**累加，
    所以「未开始的领域」在表里根本不会出现行 —— 这正是三态判定要
    「先判空」的原因（方案 §8.3）：没有行 = 未开始，而不是 0%。

    同一局的多个题目可能落在**同一个**知识领域上，所以这里按领域名缓存行对象：
    既保证同领域的每一道题都各记一次（不能因为「已经处理过这个领域」就跳过），
    也保证新插入的行只建一次（连续 `session.add` 同名行会撞唯一键）。
    """
    newly_lit = 0
    rows: dict[str, UserKnowledgeStat] = {}

    for item in items:
        name = (item.knowledge_point or "").strip()
        if not name:
            continue

        row = rows.get(name)
        if row is None:
            row = session.scalar(
                select(UserKnowledgeStat).where(
                    UserKnowledgeStat.user_id == user_id,
                    UserKnowledgeStat.kp_name == name,
                )
            )
            if row is None:
                row = UserKnowledgeStat(
                    user_id=user_id,
                    kp_name=name,
                    total_count=0,
                    correct_count=0,
                    mastery=0,
                    lit=False,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(row)
            rows[name] = row

        row.total_count = int(row.total_count) + 1
        if item.outcome == "correct":
            # 多选题的部分正确不计入正确数 —— 与「4 / 5」的口径一致
            row.correct_count = int(row.correct_count) + 1

        row.mastery = scoring.accuracy_of(int(row.correct_count), int(row.total_count))
        was_lit = bool(row.lit)
        row.lit = int(row.mastery) >= MASTERY_LIT_THRESHOLD
        if row.lit and not was_lit:
            newly_lit += 1
        row.last_seen_at = now
        row.updated_at = now

    session.flush()
    return newly_lit
