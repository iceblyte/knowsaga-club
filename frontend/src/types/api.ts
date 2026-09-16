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
