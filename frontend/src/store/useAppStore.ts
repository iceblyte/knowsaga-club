/**
 * 应用级状态：当前输入、后端能力开关、冒险者档案快照。
 *
 * 只放真正跨页共享的东西。单页内的临时状态不进 store，避免 store 变成杂物间。
 */

import { create } from 'zustand'

import { MOCK_ADVENTURER } from '../constants/mock'

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

  /** 冒险者档案（MVP 为演示数据，接真实用户体系后替换） */
  adventurer: typeof MOCK_ADVENTURER
}

export const useAppStore = create<AppState>((set) => ({
  userInput: '',
  setUserInput: (text) => set({ userInput: text }),

  searchEnabled: false,
  setSearchEnabled: (enabled) => set({ searchEnabled: enabled }),

  backendReachable: true,
  setBackendReachable: (reachable) => set({ backendReachable: reachable }),

  adventurer: MOCK_ADVENTURER
}))
