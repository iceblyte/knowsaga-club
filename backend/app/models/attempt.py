"""结算（`POST /attempts`）的请求与响应契约。

## 一个必须说清的设计：题目 id 是**数据库 id 的字符串形式**

出题落库时，`questions.id`（BIGINT 自增）会被回写成题库里每道题的 id
（`q1` → `"41"`，见 `services/quiz_repository` 的模块说明）。
所以前端回传的 `question_id` 就是数据库主键，服务端可以直接反查题目快照，
不需要任何映射表 —— 也正因如此，本题库以外的主键一律按参数错误拒绝。

## 客户端时间是**不可信输入**

`started_at` / `finished_at` 是客户端为了算用时上报的，服务端只做换算与合理性
夹取（见 `attempt_service`），**不用它判定任何业务归属**：
连续天数用的是服务端时间落到业务时区后的日期。
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.quiz import Quiz
from app.models.user import UserPublic

#: 选项键：`A`–`E` 与判断题的 `T`/`F`。放宽到 8 个字符是为了将来出现
#: 「组合选项」这类题型时不必改契约，但仍然挡掉超长垃圾。
OptionKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8)
]

#: 题号 / 卷轴 id（数据库 id 的字符串形式）。上限 32 位远超 BIGINT UNSIGNED 的 20 位，
#: 留出余量但不允许任意长字符串。
IdStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]

#: 交卷令牌：对应 `attempts.client_token VARCHAR(36)`，恰好容得下 UUID。
#:
#: 只收十六进制与连字符：UUID 的两种常见写法都落在这里面，而随机垃圾进不来。
#: 这个值会进唯一索引，形状太自由的话等于让别人往索引里塞任意内容。
_CLIENT_TOKEN_RE = re.compile(r"^[0-9a-fA-F-]{8,36}$")


def require_numeric_id(value: str) -> str:
    """校验「数据库 id 的字符串形式」。

    为什么不用 `str.isdigit()`：它对上标与部分 Unicode 数字（`²`、`٣`）也返回 True，
    而 `int("²")` 会直接抛 `ValueError` —— 那就变成 500 而不是 4000。
    必须同时要求 ASCII。

    公开而非私有：报告接口（`models/report.py`）也要用同一套判定。
    两处各写一份的话，总有一天会有一处被改松，而这类校验松掉是**静默**的。
    """
    if not (value.isascii() and value.isdigit()) or int(value) <= 0:
        raise ValueError("必须是数据库 id 的十进制字符串形式")
    return value


class AttemptAnswerRequest(BaseModel):
    """一道题的作答。"""

    model_config = ConfigDict(extra="ignore")

    question_id: IdStr = Field(description="题目 id（数据库主键的字符串形式）")
    selected: list[OptionKey] = Field(default_factory=list, description="选中的选项键")
    time_spent_ms: int = Field(default=0, ge=0, description="该题用时（毫秒）")

    @field_validator("question_id")
    @classmethod
    def _check_question_id(cls, value: str) -> str:
        return require_numeric_id(value)


class AttemptSubmitRequest(BaseModel):
    """`POST /attempts` 入参。

    `answers` **允许缺题**：没出现的题按「未作答」计 0 分。
    这样中途退出再交卷不会因为少传一道题就整个失败 —— 而按题量做分母算正确率，
    少答的题本来也不会让正确率变好看（见 `scoring.accuracy_of`）。
    """

    model_config = ConfigDict(extra="ignore")

    quiz_id: IdStr = Field(description="卷轴 id（数据库主键的字符串形式）")
    client_token: str = Field(
        description="一次性交卷令牌。网络重试必须复用同一个值，服务端据此幂等去重"
    )
    started_at: int = Field(ge=0, description="开始时刻（客户端毫秒时间戳）")
    finished_at: int = Field(ge=0, description="结束时刻（客户端毫秒时间戳）")
    answers: list[AttemptAnswerRequest] = Field(
        default_factory=list, max_length=50, description="逐题作答"
    )

    @field_validator("quiz_id")
    @classmethod
    def _check_quiz_id(cls, value: str) -> str:
        return require_numeric_id(value)

    @field_validator("client_token")
    @classmethod
    def _check_client_token(cls, value: str) -> str:
        """统一成小写。

        同一个令牌的不同大小写写法必须被视为同一个 —— 否则一次重试就能
        绕过幂等去重，产生第二条挑战记录，正是 `client_token` 要防的那件事。
        """
        cleaned = value.strip().lower()
        if not _CLIENT_TOKEN_RE.match(cleaned):
            raise ValueError("交卷令牌形状不合法")
        return cleaned

    @model_validator(mode="after")
    def _check_shape(self) -> "AttemptSubmitRequest":
        """形状层面的交叉校验。

        这些都属于「参数不对」（4000）而不是「内容不合规」（4001）：
        前者是前端的 bug，后者的提示语是写给用户看的。
        """
        if self.finished_at < self.started_at:
            raise ValueError("结束时刻不能早于开始时刻")

        # 同一道题出现两次会让「这道题算哪一次」变得不确定。
        # 去重取最后一条是能实现，但那是在替前端掩盖 bug —— 不如直接拒。
        ids = [answer.question_id for answer in self.answers]
        if len(set(ids)) != len(ids):
            raise ValueError("同一道题不能提交多次作答")

        return self


class AttemptAnswerResult(BaseModel):
    """一道题的判定结果。`answer` 与 `explanation` 一起回传，供报告页回放。"""

    question_id: str
    seq: int
    type: str
    stem: str
    selected: list[str]
    answer: list[str]
    outcome: str = Field(description="correct / partial / wrong")
    earned_xp: int
    max_xp: int
    explanation: str
    knowledge_point: str


#: 一局的「自我比较」状态。**闭集**，前端按值决定渲染哪一句话与哪枚胶囊。
#:
#: 取值的顺序有意义（判定的优先级），不按字母序：`first` > `record` > `tie_best`
#: > `better` / `same` / `worse`。完整规则见 `app/services/progress_service.judge`。
ProgressState = Literal["first", "record", "tie_best", "better", "same", "worse"]


class AttemptScorePoint(BaseModel):
    """历史某一局的成绩点：答对几题 / 共几题。

    刻意只有这两个数 —— 这一格的全部文案都是「答对 4 / 5 题」这种绝对量说法，
    **不带正确率**。正确率（百分比）正是本次要撤掉的东西：一旦它进了这个契约，
    总有人会顺手拿它去比较，于是「比上一局高 3 个百分点」就会回来。

    `total` 也要带上：5 题答对 5 与 10 题答对 6 之间比「答对题数」并不公平，
    所以文案里必须让分母可见（见 design.md 的 Risks）。
    """

    correct: int = Field(ge=0, description="完全答对；多选部分正确不计入")
    total: int = Field(ge=0)


class AttemptProgress(BaseModel):
    """本局与**该用户自己的**历史记录的比较结果。

    ## 为什么是嵌套一层，而不是在 `summary` 里平铺六个字段

    语义成组（删除时是一个整体）、且差值由服务端给出后**前端连减法都不用做** ——
    结算页与冒险日志页读同一份数据、走同一个「状态 → 文案」映射，
    两屏不可能出现两种说法（这是本项目反复强调的那条红线）。

    ## 为什么不落库

    状态是**读的时候按「截至该局之前的历史」重算**的，不是写进 `attempts` 的列。
    落库会变成假话：用户后来又刷新了纪录，旧那一局的报告仍旧宣称
    「这是你的最好成绩」。同理，历史报告的基准只算它**之前**的记录，
    不随时间漂移。见 design.md 的 D1。
    """

    state: ProgressState
    #: 这是**该用户**的第几局（含本局）。
    #:
    #: ⚠️ 与顶层 `attempt_no`（「**该卷轴**的第几次挑战」）是两个量，
    #: 名字必须区分开 —— 两个「第几局」放进同一个响应里会互相打架。
    attempt_count: int = Field(ge=1, description="这是该用户的第几局（含本局）")
    #: 本局 − **上一局** 的答对题数。正数为进步。首局没有上一局，恒为 `0`
    #: （`state == "first"` 时前端不会读它）。
    delta_vs_prev: int = Field(default=0, description="本局 − 上一局的答对题数")
    #: 本局 − **此前最好** 的答对题数。只有 `record` 时为正数 —— 其余状态下
    #: 历史最好 ≥ 本局。首局没有基准，恒为 `0`。
    #:
    #: 与 `delta_vs_prev` 一起由服务端给，是为了让「刷新了自己的纪录」那句说明
    #: （「比之前最好的一局多答对 N 题」）不需要前端做减法。
    delta_vs_best: int = Field(default=0, description="本局 − 此前最好的答对题数")
    #: 此前最好的一局；**首局为 `None`**（没有基准就不给基准）
    best: AttemptScorePoint | None = None
    #: 紧邻的上一局；**首局为 `None`**
    previous: AttemptScorePoint | None = None


class AttemptSummary(BaseModel):
    """一局的汇总。全部指标以**服务端**为准（方案 §6.5）。"""

    correct_count: int = Field(description="完全答对；多选的部分正确不计入")
    wrong_count: int = Field(description="含未作答")
    partial_count: int = Field(description="多选题部分正确")
    total_count: int
    accuracy: int = Field(description="0–100 整数，分母是题量")
    xp_gained: int
    max_xp: int
    coins_gained: int
    #: 本局与**该用户自己**历史的比较结果（见 `progress_service`）。
    #:
    #: 必填而不是可空：这一格是结算页与冒险日志页共用的内容，
    #: 「这次没算出来」不该是一种状态 —— 算不出来就是一次服务端故障。
    progress: AttemptProgress
    duration_ms: int
    avg_seconds_per_question: float = Field(description="保留两位小数")


class AttemptSubmitResponse(BaseModel):
    """结算结果。"""

    attempt_id: str
    attempt_no: int = Field(description="该卷轴的第几次尝试，首次 = 1")
    quiz_id: str
    quiz_title: str
    results: list[AttemptAnswerResult]
    summary: AttemptSummary
    #: 结算后的最新用户快照（XP 已累加、等级已重算）。结算页直接用它覆盖本地值。
    user: UserPublic
    #: 本次新解锁的勋章键。Phase D 接入规则引擎前恒为空数组。
    new_badges: list[str] = Field(default_factory=list)
    #: 本次因答错而（重新）入队的错题数。重复提交时为 0 —— 因为确实没新入队。
    wrong_queued_count: int = 0
    #: 是否是一次重复提交（同一个 `client_token`）。前端据此跳过二次动画。
    duplicate: bool = False


class AttemptRetryResponse(BaseModel):
    """`POST /attempts/{id}/retry`：重做同一卷轴所需的题库快照。

    直接复用出题链的 `Quiz` 契约，前端拿到就能 `start()` —— 不需要为
    「重做」定义第二套题库形状。题目 id 仍是数据库主键的字符串形式，
    所以重做之后的交卷与第一次走的是同一条路径。
    """

    attempt_id: str
    attempt_no: int = Field(description="这一局是重做的第几次")
    quiz: Quiz
