/**
 * 底部标签栏的选中态。
 *
 * 为什么要用全局 store 而不是组件内部 state：
 * 自定义 tabBar 的组件实例由小程序运行时管理，不同平台（微信 / h5）
 * 对「实例是否跨页复用」的行为不一致。把选中索引放在模块级 store 里，
 * 页面在 `useDidShow` 时写入、tabBar 读取，就能在所有平台上稳定工作，
 * 不依赖任何平台特有的组件实例语义。
 */

import { create } from 'zustand'

/** 标签顺序，必须与 app.config.ts 的 tabBar.list 一致 */
export const TAB_ORDER = ['hall', 'workshop', 'report', 'guild', 'mine'] as const

export type TabKey = (typeof TAB_ORDER)[number]

interface TabState {
  /** 当前选中的 tab 序号 */
  current: number
  /** 页面在 useDidShow 时调用 */
  setCurrent: (index: number) => void
  /** 按 tab 标识设置 */
  setCurrentByKey: (key: TabKey) => void
}

export const useTabStore = create<TabState>((set) => ({
  current: 0,
  setCurrent: (index) => set({ current: index }),
  setCurrentByKey: (key) => {
    const index = TAB_ORDER.indexOf(key)
    set({ current: index < 0 ? 0 : index })
  }
}))
