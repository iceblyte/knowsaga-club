/**
 * 冒险日志（复盘报告）相关的接口调用。
 *
 * 只有**一个**函数：`POST /report/generate`。
 *
 * 轮询**不在这里** —— 报告任务与出题任务共用 `GET /tasks/{id}`，
 * 所以直接复用 `services/quiz.ts` 的 `pollTask` 与 `fetchTask`。
 * 两套轮询写在一起，是因为「间隔多久问一次、多久算超时、用户点了取消怎么办」
 * 对两种任务完全一致；分成两份迟早会有一份被改歪。
 *
 * ## 为什么只回传 `attempt_id`
 *
 * 服务端已经持有这一局的**权威**作答（`attempts` + `answers`），
 * 让客户端把题库与作答记录再传一遍，等于把刚建立起来的权威性让回去：
 * 客户端可以传一份「全对」的记录换到一份漂亮的报告，而库里写的是另一回事。
 * 所以这里收 id 而不是收内容。
 *
 * 接口清单（与 `backend/app/api/v1/routes/report.py` 一一对应）：
 *
 * | 函数 | 接口 |
 * |---|---|
 * | `createReportTask` | `POST /report/generate` |
 */

import type { ReportGenerateRequest, ReportGenerateResponse } from '../types/api'
import { request } from './request'

/**
 * 创建报告生成任务。**只入队**，报告在后台生成，需轮询 `GET /tasks/{id}`。
 *
 * 已有可用报告时（且未传 `force`），后端返回的任务**建出来就是成功态** ——
 * 前端因此只有一条路径（建任务 → 轮询 → 读 `report`），而重复点「看报告」
 * 不会多花一次模型调用。
 *
 * @throws {ApiError} 4000（`attempt_id` 形状非法）、
 *                    4005（这一局不存在或不属于当前用户）、4010（登录态失效后重建仍失败）
 */
export function createReportTask(payload: ReportGenerateRequest): Promise<ReportGenerateResponse> {
  return request<ReportGenerateResponse>({
    path: '/report/generate',
    method: 'POST',
    data: payload as unknown as Record<string, unknown>
  })
}
