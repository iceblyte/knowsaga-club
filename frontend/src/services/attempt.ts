/**
 * 挑战记录相关的接口调用（交卷结算 / 重做）。
 *
 * 与 `services/quiz.ts` 的分工：那边是「卷轴怎么来」（异步出题 + 轮询），
 * 这边是「一局打完之后怎么算」。两者的错误处理策略完全不同，混在一起
 * 会让「轮询超时该怎么办」和「交卷失败该怎么补」这两件事互相干扰。
 *
 * 接口清单（与 `backend/app/api/v1/routes/attempts.py` 一一对应）：
 *
 * | 函数 | 接口 |
 * |---|---|
 * | `submitAttempt` | `POST /attempts` |
 * | `retryAttempt` | `POST /attempts/{id}/retry` |
 */

import type { AttemptRetryResponse, AttemptSubmitRequest, AttemptSubmitResponse } from '../types/api'
import { request } from './request'

/**
 * 交卷结算。**服务端会重新判题**，请求体里没有任何分数字段。
 *
 * 这个接口是**幂等**的：同一个 `client_token` 重复提交只会落一条挑战记录，
 * 并原样回放第一次的结果（`duplicate: true`）。所以调用方在失败后
 * 可以直接重试，不需要自己记录「到底提交成功没有」。
 *
 * @throws {ApiError} 4000（参数不合理 / 题号不属于该卷轴）、
 *                    4005（卷轴不存在或不属于当前用户）、4010（登录态失效后重建仍失败）
 */
export function submitAttempt(payload: AttemptSubmitRequest): Promise<AttemptSubmitResponse> {
  return request<AttemptSubmitResponse>({
    path: '/attempts',
    method: 'POST',
    data: payload as unknown as Record<string, unknown>
  })
}

/**
 * 取回某一局所用卷轴的题库快照，供「重做」使用。
 *
 * 返回的 `quiz` 可以直接喂给 `useQuizStore.start()` —— 题目 id 与首次一致，
 * 所以重做之后的交卷走的是同一条路径。
 *
 * @throws {ApiError} 4005（这一局不存在或不属于当前用户）
 */
export function retryAttempt(attemptId: string): Promise<AttemptRetryResponse> {
  return request<AttemptRetryResponse>({
    path: `/attempts/${attemptId}/retry`,
    method: 'POST'
  })
}
