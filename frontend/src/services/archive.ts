/**
 * 冒险者档案（Phase D 的四屏数据）。
 *
 * 四个函数对应四个**只读聚合**接口，都挂在 `/users/me` 下：
 *
 * | 函数 | 接口 | 原型屏 |
 * |---|---|---|
 * | `fetchDashboard` | `GET /users/me/dashboard` | 04·3 数据看板 |
 * | `fetchKnowledgeTree` | `GET /users/me/knowledge-tree` | 04·4 知识树 |
 * | `fetchWrongQuestions` | `GET /users/me/wrong-questions` | 04·7 旧识重温 |
 * | `fetchBadges` | `GET /users/me/badges` | 04·9 勋章墙 |
 *
 * ## 为什么读取侧单独成一个模块
 *
 * 这四个接口的失败后果都一样：**页面显示不出数据**，且都有「空态」可退
 * （没数据 ≠ 出错）。它们不会写坏服务端状态，因此重试是安全的。
 * 而 `services/attempt.ts` 那些写接口失败后要考虑「到底提交成功没有」。
 * 两类接口的调用方需要的判断完全不同，所以分开。
 *
 * ## 查询参数为什么手拼
 *
 * `request()` 只收一个 `path`，没有独立的 `query` 字段。加一个字段就得在
 * 请求层多做一件「序列化查询串」的事 —— 而目前只有两个可选参数，手拼更直白。
 * 值都来自闭集（`'7d' | '30d'`、`boolean`），不需要转义。
 */

import type {
  BadgeListResponse,
  DashboardRange,
  DashboardResponse,
  KnowledgeTreeResponse,
  ProfileResponse,
  WrongQuestionsResponse
} from '../types/api'
import { request } from './request'

/**
 * 个人中心（原型 04·1）。
 *
 * 身份 + 进度 + 三宫格 + 四个入口的计数**一次取回**，不拆成四个请求 ——
 * 这些数字在同一个屏幕上，拆开只会让首屏出现「身份已到、计数还没到」
 * 的中间态（头像与昵称旁边空着一块，然后数字突然跳出来）。
 *
 * 注意它同时也是「本地没有令牌时」最直接的探活手段：这个接口需要鉴权，
 * 能拿到数据就说明登录态是好的。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function fetchProfile(): Promise<ProfileResponse> {
  return request<ProfileResponse>({
    path: '/users/me'
  })
}

/**
 * 数据看板。
 *
 * `range` 只影响「正确率 / 平均用时」及其环比 —— **柱子恒为最近 7 根**，
 * 与 `range` 无关（原型图注：再密就不可读了）。传 `30d` 不会让柱子变多。
 *
 * @throws {ApiError} 4000（`range` 不在闭集内）、4010（登录态失效后重建仍失败）
 */
export function fetchDashboard(range: DashboardRange = '7d'): Promise<DashboardResponse> {
  return request<DashboardResponse>({
    path: `/users/me/dashboard?range=${range}`
  })
}

/**
 * 知识树。
 *
 * 返回的 `nodes` **包含还没碰过的领域**（掌握度 0、`state: 'not_started'`），
 * 所以这个接口在任何时刻都有内容可展示 —— 新用户看到的是「一片待点亮」，
 * 不是空页面。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function fetchKnowledgeTree(): Promise<KnowledgeTreeResponse> {
  return request<KnowledgeTreeResponse>({
    path: '/users/me/knowledge-tree'
  })
}

/**
 * 错题本。
 *
 * `dueOnly = true` 只列表里过滤，**胶囊上的计数不受影响** ——
 * `due_count` 与 `total_count` 恒按整个队列统计（原型 04·7 的胶囊写
 * 「3 题到期」而下面同时列着未到期的题）。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function fetchWrongQuestions(dueOnly = false): Promise<WrongQuestionsResponse> {
  return request<WrongQuestionsResponse>({
    path: `/users/me/wrong-questions${dueOnly ? '?due=1' : ''}`
  })
}

/**
 * 勋章墙。
 *
 * `items` 恒为全部 18 枚、顺序即注册表顺序 —— 前端**不要重排**。
 * 未解锁的也带名称与条件：原型明确要求保留轮廓与名称，
 * 让用户知道还有什么可追求。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function fetchBadges(): Promise<BadgeListResponse> {
  return request<BadgeListResponse>({
    path: '/users/me/badges'
  })
}
