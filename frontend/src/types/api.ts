/**
 * 后端接口的返回体类型。
 *
 * 这些类型是**后端 Pydantic 模型的镜像**，而不是前端自定义的结构 ——
 * 与 `backend/app/models/quiz.py`、`backend/app/services/task_service.py`
 * 一一对应。后端改字段这里必须同步改，因此每个类型都标注了它的来源文件。
 *
 * 为什么不从后端生成：
 * MVP 阶段接口只有 4 个、模型不到 10 个，代码生成器的搭建与维护成本
 * 高于手写。接口数量上去之后再换成 openapi-typescript 之类的方案更划算。
 */

// -----------------------------------------------------------------------------
// 统一响应体（backend/app/core/response.py）
// -----------------------------------------------------------------------------
export interface ApiEnvelope<T> {
  /** 0 表示成功，非 0 为业务错误码（见 backend/app/core/exceptions.py） */
  code: number
  /** 人类可读提示，可直接展示给用户 */
  message: string
  /** 失败时为 null */
  data: T | null
}

// -----------------------------------------------------------------------------
// 题库（backend/app/models/quiz.py）
// -----------------------------------------------------------------------------
export type QuestionType = 'single' | 'multiple' | 'judge'
export type Difficulty = 'easy' | 'medium' | 'hard'
/**
 * 卷轴来源。
 *
 * `review` 是**复习关卡**（旧识重温）—— 它不是「资料」，而是一局由到期错题
 * 组成的卷轴。单独一个取值而不是复用 `text`：否则历史卷轴列表里那些复习局
 * 会显示成「来自一段文字」，那是编出来的来源。
 */
export type SourceType = 'text' | 'pdf' | 'web' | 'video' | 'review'

export interface QuizOption {
  /** 选项键；判断题固定为 T / F */
  key: string
  text: string
}

export interface QuizQuestion {
  /** 题库内唯一，如 q1 */
  id: string
  type: QuestionType
  stem: string
  options: QuizOption[]
  /** 正确答案的选项键列表 */
  answer: string[]
  explanation: string
  knowledge_point: string
  difficulty: Difficulty
  /**
   * 配图的**永久**地址（后端已把上游那张 24 小时有效的图转存到 COS）。
   *
   * `null` 是**常态之一**，不是异常：用户没勾配图、开关关着、生图失败、
   * 上游超预算 —— 任何一种都会让这道题没有图。所以渲染时
   * **没有图就什么都不画**（不占位、不出骨架屏）：一个永远填不上的占位框
   * 会让人以为「图马上就来」。
   *
   * ⚠️ 它**只能由后端写入**：模型自己吐的 `image_url` 会在
   * `draft_to_quiz` 里被强制清空（design D11），否则会冒出假图片链接。
   */
  image_url?: string | null
}

/** 题型构成。由后端从 questions 派生，前端**不做二次计算**。 */
export interface QuestionStats {
  single: number
  multiple: number
  judge: number
}

export interface Quiz {
  quiz_id: string
  title: string
  summary: string
  source_type: SourceType
  user_input: string
  question_stats: QuestionStats
  /** 知识点标签。同样由后端派生，直接驱动确认页的 chip */
  knowledge_points: string[]
  questions: QuizQuestion[]
}

// -----------------------------------------------------------------------------
// 任务与轮询（backend/app/services/task_service.py）
// -----------------------------------------------------------------------------
export type TaskType = 'quiz' | 'report'
export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type StepStatus = 'pending' | 'running' | 'done' | 'failed'

/** 进度条上的一步。**文案由后端给**，前端只渲染不拼装（见开发计划 §7.3）。 */
export interface TaskStep {
  key: string
  name: string
  status: StepStatus
  detail: string
}

export interface TaskError {
  /** 复用业务错误码，前端据此决定「重试」还是「提示检查配置」 */
  code: number
  message: string
}

/**
 * 轮询响应体。形状是**固定 10 个键**，不随任务类型变化 ——
 * 没有值的字段是 `null` 而不是缺键，所以前端不需要到处写 `?.`。
 */
export interface TaskRecord {
  task_id: string
  task_type: TaskType
  status: TaskStatus
  /** 0–100，单调递增 */
  progress: number
  steps: TaskStep[]
  /** quiz 任务成功后填充 */
  quiz: Quiz | null
  /** report 任务成功后填充。两种任务共用轮询端点，故这里一定有一个是 `null` */
  report: AttemptReport | null
  error: TaskError | null
  created_at: number
  updated_at: number
}

// -----------------------------------------------------------------------------
// 接口出入参
// -----------------------------------------------------------------------------
export interface QuizSubmission {
  task_id: string
  status: TaskStatus
  /** 后端建议的轮询间隔 */
  poll_interval_ms: number
  /** 展示用估算（「预计 12 秒」），不参与逻辑判断 */
  estimated_seconds: number
}

export interface QuizGeneratePayload {
  user_input: string
  question_count?: number
  difficulty?: Difficulty | 'mixed'
  /**
   * 本次是否让 AI 主动联网补充（用户在大厅那只 pill 上的意愿）。
   *
   * 不带时后端按 **true** 处理；用户自己贴的链接**始终会被读**，
   * 不受这个字段影响（那是「你给我的资料」，不是「你去网上找找」）。
   */
  use_search?: boolean
  /**
   * 本次出题去哪个知识库取材。不带则与接入前完全一致。
   *
   * ⚠️ 它是**字符串**（后端 `kb_id: int | None` + 前端 id 一律当字符串传的约定）。
   * 归属校验在后端、且发生在建任务之前：别人的库与不存在的库返回**同一个 4005**，
   * 不会先给一个注定失败的 `task_id`。
   *
   * ⚠️ 知识库检索**不受 `use_search` 影响** —— 关掉联网也能「只用我自己的资料出题」。
   */
  kb_id?: string
  /**
   * 本次召唤要不要给题目生成配图。
   *
   * 不带时后端按 **false** 处理 ⇒ 所有既有调用方（含脚本）行为逐位不变。
   *
   * ⚠️ 它是**这一次召唤**的选项，不是账号级偏好（与 `use_search` 同一层，
   * 见 `useAppStore` 里 `QuizOptions` 的说明）。
   *
   * ⚠️ 后端在「开关关闭 / 缺 dashscope key / 缺 COS 凭据」三种情况下会拒掉
   * 传了 `true` 的请求（4001 + 友好文案）。正常路径下前端**根本走不到**那里：
   * 能力由 `/health` 的 `image_generation_enabled` 下发，为假时开关与 pill
   * 都不渲染（design D7）—— 宁可少一个入口，也不给一个点下去必然失败的按钮。
   */
  generate_images?: boolean
}

export interface HealthInfo {
  status: string
  version: string
  env: string
  model: string
  search_enabled: boolean
  /**
   * 私有知识库的总开关（由 `GET /health` 下发）。
   *
   * ⚠️ 它**不是**权限：`/kb/*` 路由无条件注册，关掉时接口照样能调。
   * 它管的是「要不要让用户看见这个功能」—— 工坊的两行入口、我的页那一行、
   * 大厅的「上传文档 / 粘贴网址」chip 都按它显隐（design D18）。
   */
  knowledge_base_enabled: boolean
  /**
   * 题目配图能力是否可用（由 `GET /health` 下发）。
   *
   * ⚠️ 这是**派生值**，不是 `.env` 里那个开关本身：只有「开关打开 **且**
   * dashscope key 非空 **且** COS 五项关键凭据齐全」时后端才下发 `true`。
   * 所以前端只看这一个字段，**不要**再自己去拼别的开关。
   *
   * 为 `false` 时，生成设置页那张「生成配图」卡与大厅的配图 pill
   * **整块不渲染**（与 `knowledgeBaseEnabled` 同一套做法，design D7）。
   */
  image_generation_enabled: boolean
  key_configured: boolean
}

export interface CancelResult {
  status: TaskStatus
}

// -----------------------------------------------------------------------------
// 用户（backend/app/models/user.py）
// -----------------------------------------------------------------------------
// `openid` / `session_key` / `token_version` 在后端模型里**根本不存在**
// （见该文件顶部说明），所以这里也不声明 —— 前端不可能拿到它们。
// `level*` 是后端按 `xp_total` 派生的，前端不重算：等级曲线属于服务端口径。
export interface UserPublic {
  id: number
  nickname: string
  avatar_key: string
  /** 自定义头像；**读取时优先于 `avatar_key`** */
  avatar_url: string | null
  xp_total: number
  coins: number
  streak_days: number
  longest_streak: number
  /** 派生字段：等级序号 */
  level: number
  /** 派生字段：等级文案，如「见习冒险者」 */
  level_title: string
  /** 下一级门槛（进度条分母） */
  next_level_xp: number
  /** 距下一级还差多少 */
  xp_to_next_level: number
  /** 0–100，直接当 CSS 宽度 */
  level_progress: number
  created_at: string
}

export interface LoginResponse {
  token: string
  /** 有效期（秒） */
  expires_in: number
  user: UserPublic
}

// -----------------------------------------------------------------------------
// 结算 / 挑战记录（backend/app/models/attempt.py）
// -----------------------------------------------------------------------------
export type AttemptOutcome = 'correct' | 'partial' | 'wrong'

/**
 * 一道题的作答。
 *
 * `question_id` 是**数据库主键的字符串形式**：出题落库时后端会把题库里的
 * `q1` 改写成 `"41"`（见 `quiz_repository` 的模块说明），前端拿到的本来就是这个值，
 * 所以直接回传即可，不需要任何映射。
 */
export interface AttemptAnswerRequest {
  question_id: string
  /** 选中的选项键；未作答传空数组或直接不传这道题 */
  selected: string[]
  time_spent_ms?: number
}

/**
 * `POST /attempts` 入参。
 *
 * **刻意没有任何分数字段** —— 分数由服务端重判（方案 §6.5）。
 * 客户端上报的只有「选了什么」和「什么时候开始/结束的」。
 *
 * `answers` 允许缺题：没出现的题按「未作答」计 0 分。
 */
export interface AttemptSubmitRequest {
  quiz_id: string
  /**
   * 一次性交卷令牌。**网络重试必须复用同一个值**，服务端据此幂等去重；
   * 换一个新的令牌就会被当成新的一局，档案里凭空多一次挑战。
   */
  client_token: string
  /** 开始时刻（客户端毫秒时间戳） */
  started_at: number
  /** 结束时刻（客户端毫秒时间戳） */
  finished_at: number
  answers: AttemptAnswerRequest[]
}

export interface AttemptAnswerResult {
  question_id: string
  /** 题序（1 起），结果按它排序 */
  seq: number
  type: string
  stem: string
  selected: string[]
  answer: string[]
  outcome: AttemptOutcome
  earned_xp: number
  max_xp: number
  explanation: string
  knowledge_point: string
}

/** 一局的汇总。**全部指标以服务端为准**，前端的本地计算只是即时反馈。 */
export interface AttemptSummary {
  /** 完全答对；多选的部分正确**不计入** */
  correct_count: number
  /** 含未作答 */
  wrong_count: number
  /** 多选题部分正确 */
  partial_count: number
  total_count: number
  /** 0–100 整数，分母是题量 */
  accuracy: number
  xp_gained: number
  max_xp: number
  coins_gained: number
  duration_ms: number
  avg_seconds_per_question: number
  /** 本局与该用户**自己**的历史记录的对比结果 */
  progress: AttemptProgress
}

/**
 * 一局的「自我比较」状态。**闭集**，前端按值查文案（`copy.ts::progressTextOf`），
 * 一条比较判断都不写。
 *
 * 取值的顺序有意义（判定的优先级），不按字母序：
 * `first` > `record` > `tie_best` > `better` / `same` / `worse`。
 * 完整规则见 `backend/app/services/progress_service.judge`。
 */
export type ProgressState = 'first' | 'record' | 'tie_best' | 'better' | 'same' | 'worse'

/**
 * 历史某一局的成绩点：答对几题 / 共几题。
 *
 * 刻意**只有这两个数** —— 这一格的全部文案都是「答对 4 / 5 题」这种绝对量
 * 说法，不带正确率。正确率（百分比）正是本次要撤掉的东西：一旦它进了这个
 * 契约，总有人会顺手拿它去比较，「比上一局高 3 个百分点」就会回来。
 */
export interface AttemptScorePoint {
  correct: number
  total: number
}

/**
 * 本局与**该用户自己的**历史记录的比较结果。
 *
 * ⚠️ 它替换掉的是 `percentile` / `percentile_pool`（2026-09-23）—— 那两格
 * 讲的是「本局超过社团里 43% 的冒险者」，而「社团」在产品里没有任何数据实体
 * （库里既没有 guild / club 表，也没有成员关系表），7 人池子上的 43% 是把
 * 42.86% 包装成的假精度，且拿「你这一局」比「别人的历史最佳」（还是别人
 * 另一份副本的最好成绩）在语义上并不成立。现在这一格只回答一个问题：
 * 比过去的自己怎么样。来龙去脉见
 * `openspec/changes/replace-percentile-with-self-comparison/`。
 *
 * ## 为什么是嵌套一层，而不是在 `summary` 里平铺
 *
 * 语义成组，且**差值由服务端给出**（`delta_vs_prev` / `delta_vs_best`）——
 * 前端连减法都不用做，只做「状态 → 文案」的查表。结算页与冒险日志页读同一份
 * 数据、走同一个函数，因此不可能出现两种说法（红线：两页必须逐位相同）。
 *
 * ## 为什么不落库（也就没有「这一格的数据在哪张表」）
 *
 * 状态是**读取时按「截至该局之前的记录」重算**的，不是 `attempts` 表的列。
 * 落库会变成假话：用户后来又刷新了纪录，旧那一局的报告仍旧宣称
 * 「这是你的最好成绩」。
 */
export interface AttemptProgress {
  state: ProgressState
  /** 这是**该用户**的第几局（含本局） */
  attempt_count: number
  /** 本局 − **上一局** 的答对题数。首局恒为 `0` */
  delta_vs_prev: number
  /** 本局 − **此前最好** 的答对题数。只有 `record` 时为正数；首局恒为 `0` */
  delta_vs_best: number
  /** 此前最好的一局；首局为 `null` */
  best: AttemptScorePoint | null
  /** 紧邻的上一局；首局为 `null` */
  previous: AttemptScorePoint | null
}

export interface AttemptSubmitResponse {
  attempt_id: string
  /** 该卷轴的第几次尝试，首次 = 1 */
  attempt_no: number
  quiz_id: string
  quiz_title: string
  results: AttemptAnswerResult[]
  summary: AttemptSummary
  /** 结算后的最新用户快照（XP 已累加、等级已重算） */
  user: UserPublic
  /**
   * 本次新解锁的勋章**键**，顺序即注册表顺序。
   *
   * 只有键、没有名称与图标：名称映射在前端的 `BADGE_BY_KEY` 里（与勋章墙
   * 共用一份），结算页据此弹「新勋章」。重复提交时恒为 `[]` ——
   * 网络抖动重试一次不该再弹一遍同样的勋章。
   */
  new_badges: string[]
  /** 本次因答错而（重新）入队的错题数；重复提交时为 0 */
  wrong_queued_count: number
  /** 是否是一次重复提交（同一个 `client_token`）。页面据此跳过二次动画 */
  duplicate: boolean
}

/** `POST /attempts/{id}/retry`：重做同一卷轴所需的题库快照。 */
export interface AttemptRetryResponse {
  attempt_id: string
  /** 这一局是重做的第几次 */
  attempt_no: number
  quiz: Quiz
}

// -----------------------------------------------------------------------------
// 冒险日志 / 复盘报告（backend/app/models/report.py）
// -----------------------------------------------------------------------------
/**
 * 复习建议卡上的动作类型。闭集 —— 前端按值决定渲染成什么控件。
 *
 * - `retry_question` → 按钮「立即重做」，把 `question_id` 指向的题**排到卷轴第一位**
 * - `review_plan`    → **胶囊**（状态展示，不可点）「已加入复习计划」
 * - `new_scroll`     → 按钮「召唤新副本」
 *
 * `review_plan` 不是按钮，因为它表达的是「系统已经替你排好了」这个既成事实，
 * 做成可点按钮会让用户以为还要自己操作一次。
 *
 * ⚠️ `retry_question` 是「排到第一位」而不是「跳到第 N 题」：
 * 重做接口返回的是**整卷**，而答题页只能线性前进，跳题会让被跳过的题
 * 以「未作答」计 0 分。完整理由见
 * `pages/report/suggestions/index.tsx` 的「立即重做怎么落到那道题上」。
 */
export type ReportActionKind = 'retry_question' | 'review_plan' | 'new_scroll'

export interface ReportAction {
  kind: ReportActionKind
  /** 按钮 / 胶囊上的文字。**由后端给**，前端不自己拼 */
  label: string
  /** `retry_question` 时指向具体题目（要排到最前的那一道） */
  question_id: string | null
}

export interface ReportAdvice {
  title: string
  body: string
  /** 没有适用动作时为 `null` —— 此时只渲染文案，不给按钮 */
  action: ReportAction | null
}

/**
 * 一份复盘报告。`GET /tasks/{id}` 成功时 `data.report` 的结构。
 *
 * ## 两段数据的来源不同（这是本类型最需要注意的地方）
 *
 * | 字段 | 来源 |
 * |---|---|
 * | 正确率 / 答对答错数 / 用时 / XP / 金币 | `attempts` 表，与结算页**逐位相同** |
 * | 与本局之前的自己比（`progress`） | `progress_service`，读取时重算（**不落库**） |
 * | 掌握点 / 薄弱点 / 三句话总结 / 复习建议 | AI 生成（失败时为确定性模板兜底） |
 *
 * 所以前端**不做任何二次计算** —— 原型第 1 屏的「答对 4/5」「8.4s」
 * 分别直接读 `correct_count` / `total_count`、`avg_seconds_per_question`。
 *
 * ⚠️ 原型第 1 屏还有一句「本局超过社团里 72% 的冒险者」，**本方案撤掉了它**
 * （`percentile` / `percentile_pool` / `percentile_label` 三个字段一并删除）。
 * 替换它的是 `progress`。这是**有意偏离原型**，理由与登记位置见
 * `constants/copy.ts` 文件头，不要当成 bug「修」回去。
 */
export interface AttemptReport {
  attempt_id: string
  quiz_id: string
  quiz_title: string
  /** 本局结束时刻（UTC ISO 串，展示时按业务时区格式化） */
  finished_at: string

  // ---- 统计数字：全部来自 attempts ----
  accuracy: number
  total_count: number
  /** 完全答对；多选部分正确不计入 */
  correct_count: number
  wrong_count: number
  partial_count: number
  duration_ms: number
  avg_seconds_per_question: number
  xp_gained: number
  max_xp: number
  coins_gained: number
  /** 本局与该用户自己历史的比较结果（见 `AttemptProgress`） */
  progress: AttemptProgress

  // ---- 叙述内容 ----
  mastered_points: string[]
  weak_points: string[]
  /** 恰好 3 句 */
  three_line_summary: string[]
  /** 恰好 3 条 */
  advice: ReportAdvice[]

  /**
   * 是否由「确定性模板」兜底生成。
   *
   * 正常情况下用不到，但**必须渲染出来**：模板报告与 AI 报告读起来差别明显，
   * 不告知会让用户以为 AI 就这个水平。见报告页的说明。
   */
  degraded: boolean
}

/** `POST /report/generate` 入参。**只回传 `attempt_id`**，不传作答内容。 */
export interface ReportGenerateRequest {
  attempt_id: string
  /** 已有报告时是否强制重新生成。默认复用（幂等） */
  force?: boolean
}

/** `POST /report/generate` 返回内容。形状与 `QuizSubmission` 对齐。 */
export interface ReportGenerateResponse {
  task_id: string
  status: TaskStatus
  poll_interval_ms: number
  estimated_seconds: number
}


// -----------------------------------------------------------------------------
// 冒险者档案（backend/app/models/archive.py）
// -----------------------------------------------------------------------------
// 四屏：04·3 数据看板 / 04·4 知识树 / 04·7 旧识重温 / 04·9 勋章墙。
//
// 这里**没有**任何「较上周 +18%」这类句子 —— 后端给的是数字
// （`week_delta_percent` / `accuracy_delta` / `duration_delta_ms`），
// 句子在前端拼。数字是事实，措辞是界面。

/**
 * 看板的统计区间。原型导览栏右侧的「近 30 天」去掉（全站右侧不放文字），
 * 改由页面上的切换控件承担。
 */
export type DashboardRange = '7d' | '30d'

export interface DashboardBar {
  /** 星期几的单字（一…日） */
  label: string
  /** 业务时区日期（`YYYY-MM-DD`），便于排查「这根柱子是哪天」 */
  date: string
  /** 这一天的**答题数**（不是挑战局数） */
  count: number
}

export interface DomainMastery {
  name: string
  /** 0–100 */
  mastery: number
  total_count: number
  correct_count: number
}

/**
 * `GET /users/me/dashboard?range=7d|30d`。
 *
 * ## 柱状图恒为 7 根，与 `range` 无关
 *
 * 原型图注写明「柱状图只展示最近 7 天，避免移动端柱子过密不可读」，
 * 所以 `range` 只影响正确率 / 平均用时这两项，柱子固定最近 7 天。
 */
export interface DashboardResponse {
  range: DashboardRange
  /** 这个用户**曾经**挑战过。为 false 时出「还没有开始冒险」空态 */
  has_data: boolean
  /**
   * **所选区间内**有没有作答记录。
   *
   * 与 `has_data` 是两件事：老用户切到「近 30 天」时 `has_data` 为 true、
   * 这一项可能为 false。空窗口里 `accuracy` 与 `avg_duration_ms` 都是 0，
   * 原样渲染成「正确率 0% · 用时 0 秒」读起来像考砸了，实际只是这段时间没来 ——
   * 所以界面靠这个标志把两个数字显示成「—」。
   */
  range_has_data: boolean

  /** 恰好 7 项，按日期升序，最后一项是今天 */
  bars: DashboardBar[]
  /** 7 天答题合计 */
  week_answers: number
  /** 与上一个 7 天相比的变化百分比；上周期无数据时为 `null`（不编造对比） */
  week_delta_percent: number | null

  /** 区间内平均正确率（0–100，按题量加权） */
  accuracy: number
  /** 与上一个等长周期相比的**百分点**变化；上周期无数据时为 `null` */
  accuracy_delta: number | null

  /** 区间内平均单局用时 */
  avg_duration_ms: number
  /** 与上一周期相比的变化（毫秒，**正数 = 变慢**）；上周期无数据时为 `null` */
  duration_delta_ms: number | null

  /** 各知识领域掌握度（只含答过题的领域），按掌握度降序 */
  domains: DomainMastery[]
}

/** 知识领域三态。`not_started` 是「没碰过」，不是「0% 掌握」。 */
export type KnowledgeState = 'lit' | 'growing' | 'not_started'

export interface KnowledgeNode {
  name: string
  mastery: number
  total_count: number
  correct_count: number
  state: KnowledgeState
}

/**
 * `GET /users/me/knowledge-tree`。
 *
 * `nodes` 含**还没碰过**的领域（掌握度 0）—— 知识树的意义正是
 * 「还有什么没点亮」，只列已答过的话这一屏就永远没有新东西。
 */
export interface KnowledgeTreeResponse {
  nodes: KnowledgeNode[]
  lit_count: number
  growing_count: number
  not_started_count: number
  /** 一句按事实生成的建议；没有可说的时为空串 */
  suggestion: string
  /** `suggestion` 提到的领域名，前端据此高亮那个节点；无建议时为 `null` */
  next_target: string | null
}

export interface WrongQuestionItem {
  question_id: string
  stem: string
  knowledge_point: string
  /** 这道题来自哪份卷轴 —— 用户需要这个上下文才知道「错在哪儿」 */
  quiz_title: string
  wrong_count: number
  /** 复习阶段 0–5，对应间隔 1/2/4/7/15/30 天 */
  stage: number
  /** 现在是否已到期 */
  due: boolean
  /** 下次到期时刻（UTC ISO 串） */
  next_review_at: string
  /** 面向用户的到期说法（「已经到期」「今天」「明天」「3 天后」）。**后端按业务时区算好** */
  next_review_label: string
}

/**
 * `GET /users/me/wrong-questions?due=1`。
 *
 * `due_count` 与 `total_count` **恒按整个队列统计**，与 `due` 参数无关 ——
 * 原型 04·7 的胶囊写「3 题到期」而列表里同时列着未到期的题。
 */
export interface WrongQuestionsResponse {
  due_count: number
  /** 队列总题数（不含已攻克的） */
  total_count: number
  items: WrongQuestionItem[]
}

export interface BadgeItem {
  key: string
  name: string
  /** 解锁条件的一句话说明，显示在未解锁的那几枚下面 */
  desc: string
  /** 圆底上的单字 */
  icon: string
  tier: 'gold' | 'rare'
  unlocked: boolean
  /** UTC ISO 串；未解锁时为 `null` */
  unlocked_at: string | null
}

/**
 * `GET /users/me/badges`。
 *
 * `items` 恒为全部 18 枚、顺序即注册表顺序（前端不重排）——
 * 未解锁的也带名称与条件，原型明确要求「保留轮廓与名称，让用户知道还有什么可追求」。
 */
export interface BadgeListResponse {
  unlocked_count: number
  total: number
  items: BadgeItem[]
}

// -----------------------------------------------------------------------------
// 历史卷轴（backend/app/models/archive.py → ScrollListResponse / ScrollDetailResponse）
// -----------------------------------------------------------------------------
/**
 * 历史卷轴列表里的一条。
 *
 * **一条 = 一次挑战（`attempts` 的一行），不是一份卷轴**（方案 §5.5）。
 * 同一份卷轴重做三次就有三条记录，`attempt_no` 标出这是第几次 ——
 * 原型 04·5 每条写「正确率 80% · 5 题」而详情页带「重做」按钮，
 * 两者合起来只有「一局」这个粒度说得通。
 */
export interface ScrollItem {
  /** 列表项的主键。详情 / 重做 / 删除都用它，**不是** `quiz_id` */
  attempt_id: string
  quiz_id: string
  title: string
  /** UTC ISO 串（带 `+00:00`） */
  finished_at: string
  /**
   * 面向用户的时间说法（「今天 14:20」「昨天 21:05」「9 月 11 日」）。
   * **由后端按业务时区派生** —— 客户端时区与业务时区不一致时，
   * 前端自己算会得到不同的「今天」。
   */
  finished_label: string
  /** 0–100 */
  accuracy: number
  correct_count: number
  total_count: number
  duration_ms: number
  /** 这一局是该卷轴的第几次挑战 */
  attempt_no: number
}

/**
 * `GET /users/me/scrolls?domain=&page=&size=`。
 *
 * `total` 是**当前筛选下**的全部条数（不是 `items.length`）——
 * 04·5 页脚的「已经到底了 · 共 N 份卷轴」要用它，翻页时不会越翻越少。
 */
export interface ScrollListResponse {
  total: number
  page: number
  size: number
  has_more: boolean
  /**
   * 可用的领域筛选项（不含「全部」）。
   *
   * **恒为全量、不随当前筛选变化** —— 否则切到一个空结果之后
   * chips 一起消失，就再也切不回去了。
   */
  domains: string[]
  items: ScrollItem[]
}

/**
 * 详情页里的一道题（含用户**当时**的作答）。
 *
 * 题干 / 选项 / 答案 / 讲解都来自 `questions` —— 那张表本身就是快照，
 * 所以历史卷轴能无限期回看，不受后续重新出题影响。
 */
export interface ScrollQuestionItem {
  seq: number
  type: QuestionType
  stem: string
  options: QuizOption[]
  /** 正确答案（答错时要显示它） */
  answer: string[]
  /** 用户当时选中的键 */
  selected: string[]
  outcome: AttemptOutcome
  explanation: string
  earned_xp: number
  max_xp: number
  /**
   * 当年这一局的配图。与题干同一性质 —— 它在 `questions` 表里是快照，
   * 所以回看时看到的就是**当时那张图**，不受后续重新出题影响。
   * 没有配图时为 `null`，此时不渲染、不占位。
   */
  image_url?: string | null
}

/** `GET /users/me/scrolls/{attempt_id}`。 */
export interface ScrollDetailResponse {
  attempt_id: string
  quiz_id: string
  title: string
  /** 复习关卡是 `review` —— 详情页可据它换一个来源说法 */
  source_type: SourceType
  finished_at: string
  finished_label: string
  duration_ms: number
  accuracy: number
  correct_count: number
  partial_count: number
  wrong_count: number
  total_count: number
  xp_gained: number
  max_xp: number
  attempt_no: number
  questions: ScrollQuestionItem[]
}

/**
 * `DELETE /users/me/scrolls/{attempt_id}`。
 *
 * **软删除**：记录从列表与详情消失，但累计 XP / 正确率 / 等级一概不变
 * （需求 FR-B5）。重复删除报 4005 —— 幂等由客户端忽略该错误实现。
 */
export interface ScrollDeleteResponse {
  attempt_id: string
  deleted: boolean
}

// -----------------------------------------------------------------------------
// 复习关卡（backend/app/models/archive.py → ReviewStartResponse）
// -----------------------------------------------------------------------------
/**
 * `POST /review/start`：用到期错题组一局。
 *
 * 返回的就是**普通题库**，直接喂给既有的「确认 → 答题 → 交卷」链路 ——
 * 复习不需要第二条交卷路径。
 *
 * 副本题通过 `origin_question_id` 指回原错题，所以复习答对推进的是
 * **原错题的阶段**（这件事由后端负责，前端无感）。
 */
export interface ReviewStartResponse {
  quiz: Quiz
  /** 本局用到的到期错题数（= `quiz.questions.length`） */
  question_count: number
}

// -----------------------------------------------------------------------------
// 个人中心（backend/app/models/user.py）
// -----------------------------------------------------------------------------
export interface ProfileStats {
  /** 闯关副本 */
  attempt_count: number
  /** 平均正确率（0–100 整数） */
  avg_accuracy: number
  /** 知识树：已点亮领域数 */
  lit_kp_count: number
  /** 历史卷轴：条目数（= 挑战次数） */
  scroll_count: number
  /** 勋章墙：已解锁数 */
  badge_unlocked: number
  /** 勋章墙：总数（原型「6 / 18」的分母） */
  badge_total: number
}

/** `GET /users/me`：个人中心首屏的全部数据（一个接口而不是四个）。 */
export interface ProfileResponse {
  user: UserPublic
  stats: ProfileStats
}

/**
 * 「为什么是今天」的两个事实（原型 04·8 的第二句文案）。
 *
 * 服务端只给**事实**，不给整句 —— 「今天 / 昨天 / N 天前」三种说法属于
 * 面向用户的措辞，统一放在 `copy.ts`。`days_ago` 已按业务时区的**自然日**
 * 之差算好（0 = 今天，1 = 昨天），前端**不要**自己拿时间戳相减：
 * 客户端时区不同的人会各算各的，出现「服务端说昨天、界面写今天」。
 */
export interface ReminderHint {
  days_ago: number
  /** 在哪个知识点上失手；题干没给知识点时退化为卷轴标题 */
  topic: string
}

/** `GET /users/me/reminders/today`（原型 04·8 的三宫格）。 */
export interface RemindersTodayResponse {
  due_count: number
  estimated_minutes: number
  available_xp: number
  snoozed_today: boolean
  /** 没有到期错题时为 `null`，此时不要硬凑一句理由 */
  hint: ReminderHint | null
}

/** `POST /users/me/reminders/snooze` 的返回。 */
export interface SnoozeResponse {
  snoozed_today: boolean
}

/**
 * `GET /users/me/settings`（原型 07·5 / 07·6 的数据面）。
 *
 * `reminder_time` 是 `"HH:MM"` 字符串而不是时间戳：拿到就显示、改了就直接提交，
 * 中间不需要任何时区换算。它代表**用户的本地时间**（业务时区），不是一个时间点。
 */
export interface UserSettingsPublic {
  reminder_enabled: boolean
  /** `"HH:MM"`，24 小时制 */
  reminder_time: string
  /** 星期集合，1 = 周一 … 7 = 周日；服务端保证非空、不重复、已排序 */
  reminder_days: number[]
  remind_streak_break: boolean
  remind_review_due: boolean
  sound_enabled: boolean
  auto_load_images: boolean
  eye_care: boolean
}

/**
 * `PATCH /users/me/settings` 的入参：**全部可选**，只传要改的那个。
 *
 * 用 `Partial` 而不是把每个字段都写成 `?`，是为了「设置页改了什么就提交什么」
 * 这件事在类型上就成立：只要 `UserSettingsPublic` 加了字段，这里自动跟上，
 * 不会出现「服务端支持了、前端忘了加」的空洞。
 */
export type UserSettingsUpdateRequest = Partial<UserSettingsPublic>

// -----------------------------------------------------------------------------
// 私有知识库（backend/app/models/kb.py）
// -----------------------------------------------------------------------------
/**
 * 文档的解析状态。**四态是闭集，只有 `ready` 参与检索。**
 *
 * 文案不由后端下发（与档案页的 `state` 同一条约定）：静态界面用语归
 * `constants/copy.ts`，这里只给状态值。`error_message` 是例外 ——
 * 它是随数据变化的叙述，由后端给且保证是可展示的一句话。
 */
export type KbDocStatus = 'pending' | 'parsing' | 'ready' | 'failed'

/** 知识库接受的文档扩展名（小写、不带点）。与后端准入清单一致。 */
export type KbDocExt = 'pdf' | 'docx' | 'md' | 'txt'

/** 一份文档在界面上的全部信息。 */
export interface KbDocumentItem {
  /** 字符串形式的主键（与卷轴 / 题目 id 的约定一致，可直接当 key 用） */
  id: string
  kb_id: string
  /** 客户端给的**原始**文件名（`机器学习导论.pdf`），不是服务端的落盘名 */
  filename: string
  /** 小写扩展名**不带点**（`pdf` / `docx` / `md` / `txt`） */
  ext: string
  size_bytes: number
  status: KbDocStatus
  /** 入库片段数；仅 `ready` 时非零 */
  chunk_count: number
  /** 页数（PDF 才有）；不适用时为 0 —— 界面据此决定要不要显示「共 N 页」 */
  page_count: number
  /** 失败原因的一句话；非失败态为空串 */
  error_message: string
  created_at: string
  /** 解析结束（成功或失败）的时刻；解析中为 `null` */
  parsed_at: string | null
}

/** 一个知识库在列表 / 详情页头部的样子。 */
export interface KbBaseItem {
  id: string
  name: string
  description: string
  /** 全部文档数（含解析中与失败的） */
  document_count: number
  /**
   * 已就绪文档数。**「能不能出题」看它** —— 为 0 时按钮要置灰
   * （原型 05·5 的批注「未就绪的库不允许出题」，后端不拦，见 design D17）。
   */
  ready_count: number
  created_at: string
  updated_at: string
}

/** `GET /kb`。恒返回全部库（不分页）：一个用户手上的资料库是「个位数」。 */
export interface KbListResponse {
  total: number
  items: KbBaseItem[]
}

/** `GET /kb/{kb_id}`：库本身 + 它的全部文档（也不分页）。 */
export interface KbBaseDetailResponse {
  base: KbBaseItem
  documents: KbDocumentItem[]
}

/** `POST /kb` 的入参。库名 2–40 字，同用户下唯一（重名报 4001）。 */
export interface KbCreatePayload {
  name: string
  description?: string
}

/**
 * `PATCH /kb/{kb_id}` 的入参：改名 / 改描述，**至少给一个**。
 *
 * 两个都不给会被后端判 4000 —— 「什么都没改」与「改成功」在客户端看起来
 * 一模一样，而用户明明改过东西。所以类型上就要求至少一个：
 * 用联合而不是两个可选字段，让漏传在编译期就暴露。
 */
export type KbUpdatePayload =
  | { name: string; description?: string }
  | { name?: string; description: string }

/**
 * 上传 / 重新解析的返回。
 *
 * 带上 `poll_interval_ms` 而不是让前端写死：轮询节奏由后端配置决定
 * （原型 05·3 写 8 秒，本期 2 秒）。
 *
 * ⚠️ `document.status` 是**调用前的快照**，不一定是终态（上传时通常是
 * `pending`、重试时是 `parsing`）。终态一律靠轮询 `GET /kb/{kb_id}` 拿到 ——
 * 不要为「响应里恰好是 ready」写分支，那条分支在真实环境里走不到。
 */
export interface KbDocumentEnvelope {
  document: KbDocumentItem
  poll_interval_ms: number
}

/** `DELETE /kb/{kb_id}`。 */
export interface KbDeleteResponse {
  kb_id: string
}

/** `DELETE /kb/documents/{doc_id}`。 */
export interface KbDocumentDeleteResponse {
  doc_id: string
  kb_id: string
}
