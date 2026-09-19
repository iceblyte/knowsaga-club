/**
 * 复习关卡的接口调用。
 *
 * 只有一个函数：`POST /review/start`。
 *
 * ## 为什么不用传参
 *
 * 「该复习哪些题」完全由服务端按错题队列的到期时刻决定 ——
 * 客户端连 `user_id` 都不用传（从令牌取）。这不是接口设计得懒，
 * 而是**到期判定是服务端的事实**：客户端时钟可能不准、可能被改，
 * 让它来决定「哪些算到期」等于把复习计划交给用户设备。
 *
 * 返回的 `quiz` 就是一份普通题库，直接喂给既有的「确认 → 答题 → 交卷」链路。
 * 复习**没有**第二条交卷路径 —— 有两条的话，两边的评分口径迟早会漂。
 *
 * 接口清单（与 `backend/app/api/v1/routes/review.py` 一一对应）：
 *
 * | 函数 | 接口 |
 * |---|---|
 * | `startReview` | `POST /review/start` |
 */

import type { ReviewStartResponse } from '../types/api'
import { request } from './request'

/**
 * 用到期错题组一局复习关卡。
 *
 * 每次调用都**新造一份卷轴**（`source_type: 'review'`），而不是复用上一次的 ——
 * 因为答题记录是按卷轴归属的，复用会让两局混在同一条记录里。
 *
 * 副本题通过 `origin_question_id` 指回原错题：复习答对推进的是**原错题**的
 * 阶段、并最终把它移出队列。这件事由后端负责，前端只需照常交卷。
 *
 * @throws {ApiError} 4005（现在没有到期的错题 —— 「全都还没到期」与
 *                          「队列为空」在用户看到的现象上是一样的：
 *                          现在没什么可复习的）、4010（登录态失效后重建仍失败）
 */
export function startReview(): Promise<ReviewStartResponse> {
  return request<ReviewStartResponse>({
    path: '/review/start',
    method: 'POST'
  })
}
