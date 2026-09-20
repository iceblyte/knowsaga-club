/**
 * 冒险者档案（原型 04 各屏的数据）。
 *
 * | 函数 | 接口 | 原型屏 |
 * |---|---|---|
 * | `fetchProfile` | `GET /users/me` | 04·1 个人中心 |
 * | `fetchDashboard` | `GET /users/me/dashboard` | 04·3 数据看板 |
 * | `fetchKnowledgeTree` | `GET /users/me/knowledge-tree` | 04·4 知识树 |
 * | `fetchScrolls` | `GET /users/me/scrolls` | 04·5 历史卷轴 |
 * | `fetchScrollDetail` | `GET /users/me/scrolls/{id}` | 04·6 卷轴详情 |
 * | `fetchWrongQuestions` | `GET /users/me/wrong-questions` | 04·7 旧识重温 |
 * | `fetchBadges` | `GET /users/me/badges` | 04·9 勋章墙 |
 * | `deleteScroll` | `DELETE /users/me/scrolls/{id}` | 04·5 长按删除 |
 *
 * ## 为什么读取侧单独成一个模块
 *
 * 这些接口的失败后果都一样：**页面显示不出数据**，且都有「空态」可退
 * （没数据 ≠ 出错）。它们不会写坏服务端状态，因此重试是安全的。
 * 而 `services/attempt.ts` 那些写接口失败后要考虑「到底提交成功没有」。
 * 两类接口的调用方需要的判断完全不同，所以分开。
 *
 * ## 唯一的例外：`deleteScroll`
 *
 * 它是写接口，放在这里是因为 04·5 的删除入口与该页的数据同源 ——
 * 把「读这一页」和「删这一页的一条」分到两个文件，改这一屏时要在两处跳。
 * 它的失败处理与只读接口不同：**重复删除报 4005**，所以「幂等」由调用方
 * 忽略这个错误实现（见该函数的说明）。
 *
 * ## 查询参数为什么手拼
 *
 * `request()` 只收一个 `path`，没有独立的 `query` 字段。加一个字段就得在
 * 请求层多做一件「序列化查询串」的事 —— 而目前只有几个可选参数，手拼更直白。
 * 值都来自闭集（`'7d' | '30d'`、`boolean`、页码），唯一的自由文本是领域名，
 * 它来自服务端下发的 `domains`，用 `encodeURIComponent` 兜住即可。
 */

import type {
  BadgeListResponse,
  DashboardRange,
  DashboardResponse,
  KnowledgeTreeResponse,
  ProfileResponse,
  ScrollDeleteResponse,
  ScrollDetailResponse,
  ScrollListResponse,
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

/**
 * 历史卷轴列表（原型 04·5）。
 *
 * **一项 = 一次挑战**，不是一份卷轴（方案 §5.5）—— 同一份卷轴重做几次
 * 就有几条记录，`attempt_no` 标出是第几次。
 *
 * `domain` 传空串或省略即「全部」。它来自服务端下发的 `domains`，
 * 但仍是外部输入（网络报文），所以 `encodeURIComponent` 兜一层 ——
 * 领域名里出现 `&` 或 `#` 时，不转义会让查询串被截断，
 * 表现为「筛选后一条都没有」而不是报错。
 *
 * @param domain 领域筛选；`''` 表示不筛
 * @param page 从 1 开始
 * @param size 每页条数；超过 50 服务端会报 4000（不静默截断）
 * @throws {ApiError} 4000（`size` 超上限）、4010（登录态失效后重建仍失败）
 */
export function fetchScrolls(
  domain = '',
  page = 1,
  size = 20
): Promise<ScrollListResponse> {
  const query = [`page=${page}`, `size=${size}`]
  if (domain) query.push(`domain=${encodeURIComponent(domain)}`)

  return request<ScrollListResponse>({
    path: `/users/me/scrolls?${query.join('&')}`
  })
}

/**
 * 卷轴详情（原型 04·6）：这一局的汇总 + 逐题作答记录。
 *
 * 别人的记录与不存在的记录都回 **4005**（后端刻意不区分）——
 * 调用方不要试图从错误码推断「是不是没权限」，那正是它要藏起来的信息。
 *
 * @param attemptId 挑战记录 ID（**不是** `quiz_id`，见 `ScrollItem` 的说明）
 * @throws {ApiError} 4000（id 不是正整数）、4005（不存在或不属于当前用户）
 */
export function fetchScrollDetail(attemptId: string): Promise<ScrollDetailResponse> {
  return request<ScrollDetailResponse>({
    path: `/users/me/scrolls/${attemptId}`
  })
}

/**
 * 删除一条历史记录（04·5 的长按删除）。
 *
 * **软删除**：记录从列表与详情消失，但累计 XP / 正确率 / 等级一概不变
 * （需求 FR-B5）—— 所以调用方**只需要刷新列表**，不需要重新拉个人中心
 * 或看板。
 *
 * 重复删除返回 **4005**，也就是说这个接口**不是幂等的**。要让它表现得幂等，
 * 由调用方在错误码为 4005 时**当作成功处理**（记录本来就已经不在了，
 * 用户的目标已达成）；而不是让服务端谎报成功 —— 那会让「删错了」无法被发现。
 *
 * @throws {ApiError} 4005（不存在 / 不属于当前用户 / 已经删过）
 */
export function deleteScroll(attemptId: string): Promise<ScrollDeleteResponse> {
  return request<ScrollDeleteResponse>({
    path: `/users/me/scrolls/${attemptId}`,
    method: 'DELETE'
  })
}
