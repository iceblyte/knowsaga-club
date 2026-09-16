/**
 * 出题相关的接口调用。
 *
 * 只放「怎么调后端」，不放「界面怎么反应」—— 进度条怎么画、几秒后出取消按钮
 * 属于页面的决定，写在这里会让这个文件变成半个页面。
 *
 * 接口清单（与 `backend/app/api/v1/routes/` 一一对应）：
 *
 * | 函数 | 接口 |
 * |---|---|
 * | `fetchHealth` | `GET /health` |
 * | `createQuizTask` | `POST /quiz/generate` |
 * | `fetchTask` | `GET /tasks/{id}` |
 * | `cancelTask` | `POST /tasks/{id}/cancel` |
 */

import {
  CLIENT_ERROR_CODE,
  FALLBACK_POLL_INTERVAL_MS,
  HEALTH_TIMEOUT_MS,
  POLL_DEADLINE_MS
} from '../constants/api'
import type {
  CancelResult,
  HealthInfo,
  QuizGeneratePayload,
  QuizSubmission,
  TaskRecord
} from '../types/api'
import { ApiError, request } from './request'

/** 探测后端可达性与能力开关（`search_enabled` / `key_configured`）。 */
export function fetchHealth(): Promise<HealthInfo> {
  return request<HealthInfo>({ path: '/health', timeoutMs: HEALTH_TIMEOUT_MS })
}

/** 创建出题任务。**只入队**，出题在后台推进，需轮询 `fetchTask`。 */
export function createQuizTask(payload: QuizGeneratePayload): Promise<QuizSubmission> {
  return request<QuizSubmission>({
    path: '/quiz/generate',
    method: 'POST',
    data: payload as unknown as Record<string, unknown>
  })
}

/** 查询任务状态。任务不存在或已过期时抛 `ApiError(4004)`。 */
export function fetchTask(taskId: string): Promise<TaskRecord> {
  return request<TaskRecord>({ path: `/tasks/${taskId}` })
}

/** 取消任务。任务已结束时抛 `ApiError(4090)`。 */
export function cancelTask(taskId: string): Promise<CancelResult> {
  return request<CancelResult>({ path: `/tasks/${taskId}/cancel`, method: 'POST' })
}

/** 任务是否已进入终态（成功 / 失败 / 已取消）。 */
export function isTerminal(task: TaskRecord): boolean {
  return task.status === 'succeeded' || task.status === 'failed' || task.status === 'cancelled'
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

export interface PollTaskOptions {
  taskId: string
  /** 每次拿到新状态时回调 —— 页面据此刷新进度条与三步状态卡 */
  onUpdate: (task: TaskRecord) => void
  /** 用后端建议的间隔；不传则用本地兜底值 */
  intervalMs?: number
  /** 总时长上限，默认 `POLL_DEADLINE_MS` */
  deadlineMs?: number
  /**
   * 每轮开始前询问「还要继续吗」。
   * 页面卸载或用户点了取消时返回 false，立即停止轮询 ——
   * 否则一个已经离开的页面会继续打请求直到超时。
   */
  shouldContinue?: () => boolean
}

/**
 * 轮询任务直到进入终态。
 *
 * **终态由 `status` 判定，不是由 HTTP 码判定**：出题失败时后端返回的是
 * HTTP 200 + `status: "failed"` + `error: {code, message}`，
 * 因为「任务失败了」对轮询端点而言是一次**成功**的状态查询。
 *
 * @throws {ApiError} 4004（任务不存在/已过期）、-3（超过 `deadlineMs` 仍在跑）、
 *                    以及 `fetchTask` 自身的网络错误。
 */
export async function pollTask({
  taskId,
  onUpdate,
  intervalMs = FALLBACK_POLL_INTERVAL_MS,
  deadlineMs = POLL_DEADLINE_MS,
  shouldContinue
}: PollTaskOptions): Promise<TaskRecord> {
  const startedAt = Date.now()

  // 先查一次再睡：任务在 `createQuizTask` 之后可能已经完成了，
  // 无条件先睡一轮会让这类「秒回」场景平白多等一个间隔。
  for (;;) {
    if (shouldContinue && !shouldContinue()) {
      throw new ApiError(CLIENT_ERROR_CODE.POLL_TIMEOUT, '已停止等待')
    }

    const task = await fetchTask(taskId)
    onUpdate(task)

    if (isTerminal(task)) {
      return task
    }

    if (Date.now() - startedAt >= deadlineMs) {
      throw new ApiError(CLIENT_ERROR_CODE.POLL_TIMEOUT, '')
    }

    await sleep(intervalMs)
  }
}
