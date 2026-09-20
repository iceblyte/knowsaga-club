/**
 * 应用级状态：当前输入、后端能力开关。
 *
 * 只放真正跨页共享的东西。单页内的临时状态不进 store，避免 store 变成杂物间。
 *
 * 用户的身份数据（昵称 / 头像 / 等级 / XP / 连续天数）**不在这里**：
 * 它由 `services/session.ts` 持有登录态快照、由 `GET /users/me` 提供权威值
 * （大厅与个人中心各自读）。store 里再来一份就要在每次写入时同步，
 * 而少同步一次的表现是「设置页改完昵称、大厅还是旧的」这类无法定位的不一致。
 */

import { create } from 'zustand'

interface AppState {
  /** 社团大厅里用户输入的主题（跨页共享：召唤页与确认页都要用） */
  userInput: string
  setUserInput: (text: string) => void

  /**
   * 后端是否开启了联网检索。
   * 来自 `GET /api/v1/health` 的 `search_enabled`；启动时探测一次。
   */
  searchEnabled: boolean
  setSearchEnabled: (enabled: boolean) => void

  /** 后端可达性；为 false 时前端展示网络异常态 */
  backendReachable: boolean
  setBackendReachable: (reachable: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  userInput: '',
  setUserInput: (text) => set({ userInput: text }),

  searchEnabled: false,
  setSearchEnabled: (enabled) => set({ searchEnabled: enabled }),

  backendReachable: true,
  setBackendReachable: (reachable) => set({ backendReachable: reachable })
}))
