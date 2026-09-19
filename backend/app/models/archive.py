"""冒险者档案四个接口的契约（原型 04 的第 3 / 4 / 7 / 9 屏）。

| 页面 | 接口 | 本文件的契约 |
|---|---|---|
| 04·3 数据看板 | `GET /users/me/dashboard` | `DashboardResponse` |
| 04·4 知识树 | `GET /users/me/knowledge-tree` | `KnowledgeTreeResponse` |
| 04·7 旧识重温 | `GET /users/me/wrong-questions` | `WrongQuestionsResponse` |
| 04·9 勋章墙 | `GET /users/me/badges` | `BadgeListResponse` |
| （组卷） | `POST /review/start` | `ReviewStartResponse` |

## 这里**不**放三态文案与「较上周」这类句子

`state` 是闭集（`lit` / `growing` / `not_started`），文案与胶囊配色由前端
`constants/copy.ts` 决定。理由：这三句是**静态界面用语**（跟「答对」「金币」
同一类），不是随数据变化的叙述。若由后端下发，后端与前端各有一半的映射表，
换一个措辞就要两边同时改，而对不上的时候界面上是看不出来的
（只会显示成一句语气不对的话）。

同一道理适用于「较上周 +18%」：后端给 `week_delta_percent` 这个**数**，
句子由前端拼 —— 数字是事实，措辞是界面。

## 时间一律带 UTC 偏移

`UtcDatetime` 保证输出的 ISO 串带上 `+00:00`。库里存的是 naive UTC，
直接序列化会得到 `2026-09-19T03:00:00` 这种**不带偏移**的串 ——
而 JavaScript 的 `new Date()` 规范上把它当**本地时间**解释，
界面上的日期会整体偏 8 小时，跨零点时就是错一天。
报告页的 `finished_at` 踩过一次，这里用类型固定住，不靠人记。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models.quiz import Quiz
from app.utils.timeutil import as_aware_utc

#: 序列化时补上 UTC 偏移的 datetime（见模块说明）
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda value: as_aware_utc(value).isoformat(), return_type=str),
]

#: 看板的统计区间。原型导览栏右侧的「近 30 天」去掉（全站右侧不放文字），
#: 改由本页的一个切换控件承担，所以区间是显式入参。
DashboardRange = Literal["7d", "30d"]

#: 知识领域的三态。**判定必须先把「未开始」摘出来**：
#: `total_count = 0` 的领域不是「0% 掌握」，它只是还没碰过（方案 §8.3）。
KnowledgeState = Literal["lit", "growing", "not_started"]


# -----------------------------------------------------------------------------
# 04·3 数据看板
# -----------------------------------------------------------------------------
class DashboardBar(BaseModel):
    """柱状图的一根柱。

    `count` 是**答题数**；柱高由前端按最大值折算 —— 那是版面换算，不是业务口径。
    """

    #: 星期几的单字（一…日），原型柱下标签
    label: str
    #: 业务时区日期（`YYYY-MM-DD`），便于排查「这根柱子是哪天」
    date: str
    count: int


class DomainMastery(BaseModel):
    """各知识领域掌握度（看板底部的进度条组）。"""

    name: str
    mastery: int
    total_count: int
    correct_count: int


class DashboardResponse(BaseModel):
    """`GET /users/me/dashboard?range=7d|30d`。

    ## 柱状图恒为 7 根，与 `range` 无关

    原型图注写明「柱状图只展示最近 7 天，避免移动端柱子过密不可读」，
    所以区间参数只影响**正确率 / 平均用时**这两项的统计窗口，
    柱子固定是最近 7 天。两件事分开后，「切到 30 天」不会让柱子变糊。
    """

    range: DashboardRange
    #: 整个统计区间内一局都没有 —— 前端据此出空态，而不是画一排 0
    has_data: bool
    #: **所选窗口内**有没有挑战。
    #:
    #: 与 `has_data` 是两件事，两个都需要：一个打了两周、恰好这周没来的用户，
    #: 不该看到「还没有开始冒险」（他明明有档案），但正确率与平均用时在空窗口里
    #: 都是 0 —— 直接渲染就是「正确率 0% · 用时 0 秒」，读起来像考砸了。
    #: 所以窗口内无记录时前端显示「—」+「这个区间还没有记录」。
    range_has_data: bool = False

    #: 恰好 7 项，按日期升序
    bars: list[DashboardBar] = Field(default_factory=list)
    #: 7 天答题合计
    week_answers: int = 0
    #: 与上一个等长的 7 天相比的变化百分比；上周期无数据时为 `None`（不编造对比）
    week_delta_percent: int | None = None

    #: 区间内平均正确率（0–100）
    accuracy: int = 0
    #: 与上一个等长周期相比的**百分点**变化；上周期无数据时为 `None`
    accuracy_delta: int | None = None

    #: 区间内平均单局用时
    avg_duration_ms: int = 0
    #: 与上一个等长周期相比的变化（毫秒，正数 = 变慢）；上周期无数据时为 `None`
    duration_delta_ms: int | None = None

    #: 各知识领域掌握度，按掌握度降序（同分按名称，保证顺序稳定）
    domains: list[DomainMastery] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# 04·4 知识树
# -----------------------------------------------------------------------------
class KnowledgeNode(BaseModel):
    """知识树上的一个领域。"""

    name: str
    mastery: int
    total_count: int
    correct_count: int
    state: KnowledgeState


class KnowledgeTreeResponse(BaseModel):
    """`GET /users/me/knowledge-tree`。

    `suggestion` 是一句**按事实生成**的建议（「X 已经点亮了 80%，再闯一次…」），
    与 `next_target` 配对使用：`suggestion` 是文案，`next_target` 是它提到的领域名
    （前端据此高亮那个节点）。没有可建议的目标时两者一起为空/None ——
    宁可不说，也不编一句「继续加油」。
    """

    nodes: list[KnowledgeNode] = Field(default_factory=list)
    lit_count: int = 0
    growing_count: int = 0
    not_started_count: int = 0
    suggestion: str = ""
    next_target: str | None = None


# -----------------------------------------------------------------------------
# 04·7 旧识重温（错题本）
# -----------------------------------------------------------------------------
class WrongQuestionItem(BaseModel):
    """错题本里的一道题。"""

    question_id: str
    stem: str
    knowledge_point: str
    #: 这道题来自哪份卷轴（用户需要这个上下文才知道「错在哪儿」）
    quiz_title: str
    wrong_count: int
    #: 复习阶段 0–5，对应间隔 1/2/4/7/15/30 天（方案 §8.4）
    stage: int
    #: 现在是否已经到期
    due: bool
    #: 下次到期时刻（带 UTC 偏移）
    next_review_at: UtcDatetime
    #: 面向用户的到期说法（「已经到期」「明天」「3 天后」）。
    #: 由后端按**业务时区**从 `next_review_at` 派生 —— 换到前端算的话，
    #: 客户端时区与业务时区不一致的用户会看到错误的天数。
    next_review_label: str


class WrongQuestionsResponse(BaseModel):
    """`GET /users/me/wrong-questions?due=1`。

    `due=1` 只回到期的；不传则回全部**未移出队列**的错题（含未到期的），
    页面用 `due` 逐个标注 4·7 那两种胶囊（「重做」/「待复习」）。
    """

    #: 到期的题数（与 `items` 的长度可能不同 —— 不传 `due` 时含未到期的）
    due_count: int = 0
    #: 队列总题数（不含已攻克的）
    total_count: int = 0
    items: list[WrongQuestionItem] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# 04·9 勋章墙
# -----------------------------------------------------------------------------
class BadgeItem(BaseModel):
    """一枚勋章。未解锁的也带名称与条件（原型要求「保留轮廓与名称」）。"""

    key: str
    name: str
    desc: str
    icon: str
    tier: str
    unlocked: bool
    unlocked_at: UtcDatetime | None = None


class BadgeListResponse(BaseModel):
    """`GET /users/me/badges`。`items` 恒为全部 18 枚，顺序即注册表顺序。"""

    unlocked_count: int
    total: int
    items: list[BadgeItem]


# -----------------------------------------------------------------------------
# POST /review/start
# -----------------------------------------------------------------------------
class ReviewStartResponse(BaseModel):
    """用到期错题组一局复习关卡。

    返回的就是**普通题库契约** `Quiz`，所以前端可以把它直接喂给既有的
    「确认 → 答题 → 交卷」链路，不需要第二条交卷路径。

    `source_type` 为 `review`，题目是原错题的**副本**（`questions` 有
    `UNIQUE(quiz_id, seq)`，题目不能跨卷轴共享），副本通过
    `origin_question_id` 指回原题 —— 所以复习答对推进的是原错题的阶段。
    """

    model_config = ConfigDict(extra="ignore")

    quiz: Quiz
    #: 本局用到的到期错题数（= `quiz.questions` 的长度）
    question_count: int
