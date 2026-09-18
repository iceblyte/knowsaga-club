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
export type SourceType = 'text' | 'pdf' | 'web' | 'video'

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
  /** report 任务成功后填充（Phase 3） */
  report: Record<string, unknown> | null
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
}

export interface HealthInfo {
  status: string
  version: string
  env: string
  model: string
  search_enabled: boolean
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
  /** 演示口径：clamp(round(accuracy × 0.9), 5, 95) */
  percentile: number
  duration_ms: number
  avg_seconds_per_question: number
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
  /** 本次新解锁的勋章键。Phase D 接入规则引擎前恒为空数组 */
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
