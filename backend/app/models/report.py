"""冒险日志（复盘报告）的请求与响应契约。

## 一条必须说清的设计：报告由「两个来源」拼成

方案设计 §8.4 已经定了分工，这里只是把它变成代码：

| 字段 | 来源 | 为什么 |
|---|---|---|
| 正确率 / 答对答错数 / 用时 / XP / 金币 | `attempts` 表（`scoring` 确定性计算） | 必须与结算页**逐位相同**。同一局在结算页写 80%、在报告页写 85%，用户没法判断该信哪个 |
| 与自己比较的进度（`progress`） | `progress_service`（读取时按「该局之前的记录」重算） | 同一份报告的内容不许随用户后来的成绩改变 —— 见 `progress_service` 的模块说明 |
| 掌握点 / 薄弱点 / 三句话总结 / 复习建议 | `reports` 表（AI 生成 + 模板兜底） | 这些是「把已知数据讲成人话」，才需要模型 |

所以 `Report` 里的统计字段一律**从 `attempts` 读**，不从 `reports` 读 ——
`reports` 表里也刻意没有这些列（见 `backend/sql/01_schema.sql` 第 7 节）。

## 为什么 `ReportDraft` 与 `Report` 要分开

沿用 `output_schemas.QuizDraft` 与 `models/quiz.Quiz` 的分工：
`ReportDraft` 是模型**结构化输出的形状**（只含模型该产出的字段），
`Report` 是**服务端与前端的接口契约**（含服务端才知道的 id 与统计数字）。
把两者合成一个类，就必然要让模型回显 `attempt_id` 这类它根本不知道的值。

## 两道「事实一致性」校验

`Report` 上有两条跨字段校验（全对不得有薄弱点、全错不得有掌握点）。
服务层本来就会先做净化（`report_chain.complete_draft`），这里这道是**兜给
服务层忘了净化的那一刻**：宁可让请求失败，也不要发一份自相矛盾的报告出去。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.attempt import AttemptProgress, IdStr, require_numeric_id
from app.models.quiz import NonEmptyStr

#: 三句话总结 / 复习建议的固定条数。原型 03 的第 2、3 屏按固定条数排版卡片，
#: 少一条就塌版，所以写死在契约里而不是让调用方传。
SUMMARY_LINES = 3
ADVICE_COUNT = 3

#: 掌握点 / 薄弱点的条数上限。
#:
#: ⚠️ 这个值**不是** `ADVICE_COUNT`，虽然一度被写成了它。两者是不同性质的上界：
#: `ADVICE_COUNT` 是**版面**要求（原型就是三张卡），而知识点是**事实枚举** ——
#: 它的真实上界是「一次挑战最多能出现几个不同的知识点」＝ 题量上限。
#:
#: 把 3 套在知识点上会造成一种很隐蔽的故障：模型答「4 个薄弱点」是完全自然的
#: （5 道题错 4 道时就是这样），但契约判它为非法草稿 → 重试 → 再拒 → **整份报告降级成模板**。
#: 实测踩过：一次「5 题错 4 道」的报告连续 4 次尝试全部 `schema_mapping_failed`
#: （`mastered_points` 4 项、`weak_points` 4 项），用户拿到的是模板话术，
#: 而日志里只有一行 warning —— 降级是**可观测**的（`degraded` 标记），但原因指向
#: 的是「模型不稳定」而不是「我们把上限写错了」。
#:
#: 取 5 而不是「不限」：模型偶尔会吐 10 个以上的标签，那确实是模型跑偏了，
#: 该重试。这里留的是一个**有依据的**上界，而不是随手拍的数。
POINTS_MAX = 5

#: 建议卡文案的长度上限。`reports` 表的 JSON 列存得下更多，但这些上限保证
#: 移动端不会出现一张要滑三屏的卡片。超限即判定为不合格草稿并重试 ——
#: 重试比截断好：一句话被从中间切断读起来像 bug，而重试大概率能拿到更短的一版。
TITLE_MAX_LEN = 24
BODY_MAX_LEN = 120


class ReportActionKind(str, Enum):
    """复习建议卡上的动作类型。

    闭集，前端按值决定渲染成什么：
    - `retry_question` → 按钮「立即重做」，把 `question_id` 指向的题排到卷轴第一位
    - `review_plan`    → **胶囊**（状态展示，不可点）「已加入复习计划」
    - `new_scroll`     → 按钮「召唤新副本」，回社团大厅

    为什么 `review_plan` 不是按钮：它表达的是「系统已经替你排好了」这个既成事实，
    做成可点的按钮会让用户以为需要自己操作一次。

    为什么 `retry_question` 是「排到第一位」而不是「跳到第 N 题」：
    `POST /attempts/{id}/retry` 返回的是**整卷**（§6.3），而答题页只能线性前进，
    跳题会让被跳过的题以「未作答」计 0 分 —— 用户听从我们自己的建议，分数反而被扣。
    完整理由见 `frontend/src/pages/report/suggestions/index.tsx`。
    """

    RETRY_QUESTION = "retry_question"
    REVIEW_PLAN = "review_plan"
    NEW_SCROLL = "new_scroll"


class ReportAction(BaseModel):
    """建议卡上的动作。

    `kind` 由**服务层按真实事实**挂上（见 `report_service.build_actions`），
    不由模型产出 —— 让模型决定「建议重做第 3 题」而第 3 题其实答对了，
    就是一份假报告。
    """

    model_config = ConfigDict(extra="ignore")

    kind: ReportActionKind
    label: NonEmptyStr = Field(description="按钮 / 胶囊上的文字")
    question_id: IdStr | None = Field(
        default=None,
        description="`retry_question` 时指向具体题目（数据库主键的字符串形式）",
    )


class ReportAdviceDraft(BaseModel):
    """模型产出的单条建议：只有文案，没有动作。"""

    model_config = ConfigDict(extra="ignore")

    title: NonEmptyStr = Field(max_length=TITLE_MAX_LEN, description="12 字以内的小标题")
    body: NonEmptyStr = Field(max_length=BODY_MAX_LEN, description="一到两句话的说明")


class ReportAdvice(BaseModel):
    """对外契约里的单条建议：文案 + 动作。"""

    model_config = ConfigDict(extra="ignore")

    title: NonEmptyStr = Field(max_length=TITLE_MAX_LEN)
    body: NonEmptyStr = Field(max_length=BODY_MAX_LEN)
    #: 没有可用动作时为 None —— 前端只渲染文案，不给按钮。
    #: 编一个「点了没反应」的按钮比不给按钮更糟。
    action: ReportAction | None = None


class ReportDraft(BaseModel):
    """模型产出的一份复盘报告草稿。

    统计数字**不在这里**：它们由服务端算好当输入喂给模型（理由见
    `prompts/report_prompt.py` 的模块说明）。
    """

    model_config = ConfigDict(extra="ignore")

    mastered_points: list[NonEmptyStr] = Field(
        default_factory=list, max_length=POINTS_MAX, description="掌握较好的知识点标签"
    )
    weak_points: list[NonEmptyStr] = Field(
        default_factory=list, max_length=POINTS_MAX, description="需要巩固的知识点标签"
    )
    three_line_summary: list[NonEmptyStr] = Field(
        min_length=SUMMARY_LINES,
        max_length=SUMMARY_LINES,
        description=f"知识总结，恰好 {SUMMARY_LINES} 句",
    )
    advice: list[ReportAdviceDraft] = Field(
        min_length=ADVICE_COUNT,
        max_length=ADVICE_COUNT,
        description=f"复习建议，恰好 {ADVICE_COUNT} 条",
    )


class Report(BaseModel):
    """对外契约：`GET /tasks/{id}` 成功时 `data.report` 的结构。

    这就是原型 03 第 1–3 屏需要的全部数据 —— 前端不做任何二次计算
    （原型第 1 屏的「答对 4/5」「平均用时 8.4s」分别对应
    `correct_count`/`total_count`、`avg_seconds_per_question`）。

    ⚠️ 原型第 1 屏还有一句「本局超过社团里 72% 的冒险者」，**本方案撤掉了它**：
    「社团」在产品里没有任何数据实体，7 人池子上的 43% 是假精度，而且拿
    「你这一局」比「别人的历史最佳」在语义上并不成立。替换它的是 `progress`
    （与自己的历史比）。这是**有意偏离原型**，登记在
    `frontend/src/constants/copy.ts` 文件头与 `docs/MVP开发计划.md`，
    不要当成 bug「修」回去。
    """

    model_config = ConfigDict(extra="ignore")

    # ---- 标识 ----
    attempt_id: str
    quiz_id: str
    quiz_title: str
    finished_at: datetime = Field(description="本局结束时刻（UTC，前端按业务时区展示）")

    # ---- 统计数字：全部来自 attempts ----
    accuracy: int = Field(ge=0, le=100, description="0–100 整数")
    total_count: int = Field(ge=0)
    correct_count: int = Field(ge=0, description="完全答对；多选部分正确不计入")
    wrong_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    avg_seconds_per_question: float = Field(ge=0, description="保留两位小数")
    xp_gained: int = Field(ge=0)
    max_xp: int = Field(ge=0)
    coins_gained: int = Field(ge=0)
    #: 本局与该用户自己历史的比较结果（`progress_service`）。
    #:
    #: 必填：这一格是报告页第 1 屏的内容，「这次没算出来」不该是一种状态。
    progress: AttemptProgress

    # ---- 叙述内容：来自 reports（AI 生成，失败时为确定性模板） ----
    mastered_points: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    three_line_summary: list[str] = Field(
        min_length=SUMMARY_LINES, max_length=SUMMARY_LINES
    )
    advice: list[ReportAdvice] = Field(min_length=ADVICE_COUNT, max_length=ADVICE_COUNT)

    #: 是否是「AI 全部失败后由确定性模板兜底」生成的。
    #:
    #: 保留这个字段不是为了给用户看，而是为了让**测试与运维**能区分
    #: 「模型真的这么写的」与「走到兜底了」。没有它，兜底会变成一件
    #: 只有翻日志才知道的事，而兜底率高到一定程度就该有人去查模型了。
    degraded: bool = False

    @field_validator("avg_seconds_per_question")
    @classmethod
    def _require_two_decimals(cls, value: float) -> float:
        """必须已量化到两位小数。

        这个值写进 `attempts.avg_seconds_per_question` 是 `DECIMAL(6,2)`，
        读出来再经由 `float()` 转换。如果服务层漏了量化，这里能立刻发现 ——
        否则浮点尾数会让「报告页 = 结算页」的断言时好时坏，极难定位。
        """
        if round(value, 2) != value:
            raise ValueError("平均单题用时必须已量化到两位小数")
        return value

    @model_validator(mode="after")
    def _check_fact_consistency(self) -> "Report":
        """跨字段的事实一致性。见模块说明「两道事实一致性校验」。"""
        if self.accuracy == 100 and self.weak_points:
            raise ValueError("全部答对时不应出现薄弱知识点")
        if self.wrong_count == 0 and self.weak_points:
            raise ValueError("没有答错的题时不应出现薄弱知识点")
        if self.correct_count == 0 and self.mastered_points:
            raise ValueError("没有答对的题时不应出现掌握知识点")
        if self.correct_count + self.wrong_count + self.partial_count != self.total_count:
            raise ValueError("答对 / 答错 / 部分正确的数量之和必须等于题量")
        return self


class ReportGenerateRequest(BaseModel):
    """`POST /report/generate` 入参。

    **只收 `attempt_id`，不收题库与作答记录。**

    方案设计 §9.1 的原始设计是让客户端把 `questions` 与 `answer_records` 一起传上来。
    在还没有用户系统与落库的时候那样做是合理的；但 Phase B 之后，服务端已经
    持有这一局的**权威**作答（`attempts` + `answers`），再让客户端回传一份就等于
    把刚建立起来的权威性让回去 —— 客户端可以传一份「全对」的记录拿到一份漂亮的报告，
    而 `attempts` 上写的是另一回事。

    `reports.attempt_id` 是带外键的 `NOT NULL` 列（1:1 于 attempt），
    本来也必须由服务端知道是哪一局。所以这里收 id 而不是收内容，
    是这个 schema 逼出来的唯一自洽解。
    """

    model_config = ConfigDict(extra="ignore")

    attempt_id: IdStr = Field(description="挑战记录 id（数据库主键的字符串形式）")
    force: bool = Field(
        default=False,
        description="已存在报告时是否强制重新生成。默认复用已有报告（幂等）",
    )

    @field_validator("attempt_id")
    @classmethod
    def _check_attempt_id(cls, value: str) -> str:
        return require_numeric_id(value)


class ReportGenerateResponse(BaseModel):
    """`POST /report/generate` 返回内容（§7.5）。

    形状与 `POST /quiz/generate` 对齐：拿到 `task_id` 之后统一走
    `GET /tasks/{id}` 轮询 —— 前端只写一套轮询逻辑。
    """

    task_id: str
    status: str
    poll_interval_ms: int
    estimated_seconds: int
