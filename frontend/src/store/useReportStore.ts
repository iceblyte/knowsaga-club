/**
 * 冒险日志的状态。
 *
 * ## 为什么单独一个 store，而不是塞进 `useQuizStore`
 *
 * 报告是**已经结束的那一局**的产物，生命周期比「进行中的一局」长：
 * 用户看完报告、又去打了新的一局（`useQuizStore.reset()` 会清空本局状态），
 * 此时点回「冒险日志」标签页仍应看到上次那份报告。
 * 放在 `useQuizStore` 里会被下一次 `start()` 顺手清掉，表现为
 * 「打了新一局，旧报告就没了」—— 用户会觉得数据丢了。
 *
 * ## 为什么只存「结果」，不存「过程」
 *
 * 轮询的中间态（`taskId` / `progress` / `steps`）只属于报告页自己，
 * 页面一卸载就没有意义了。存进全局只会制造「谁负责清它」的问题。
 * 这里只留两样东西：**我们要给哪一局出报告**，以及**已经拿到的报告**。
 *
 * ## `status` 为什么也要存
 *
 * 只存 `report` 的话无法区分「还没生成」与「生成失败了」，
 * 前者该自动发起生成、后者该停在失败态等用户点重试 ——
 * 分不清就会出现两种坏结果：失败后无限自动重试，或者永远不自动生成。
 *
 * MVP 不做持久化：小程序重启后这里回到初始态。
 *
 * ## 初始态不再等于空态（本轮修复第 7 条）
 *
 * 回到初始态时 `attemptId` 是空串，但报告页**不会**因此显示
 * 「日志本还是空的」—— 它自己会去拉最近 20 份日志，并默认选中最新的一份
 * （见 `pages/report`）。这一条 store 只负责「当前要复盘哪一局」，
 * 「一共写过多少份日志」是页面的事，不放在这里。
 */

import { create } from 'zustand'

import type { AttemptReport } from '../types/api'

/**
 * 报告页的四种形态。
 *
 * `offline` 与 `failed` **必须分开**：前者是「连不上服务器」，后者是
 * 「服务器说这次生成失败了」。两者的下一步动作不同 ——
 * 一个该检查网络重连，一个该重新生成报告。
 */
export type ReportStatus = 'idle' | 'generating' | 'ready' | 'failed' | 'offline'

interface ReportState {
  /** 要给哪一局出报告；空串表示还没有可复盘的挑战 */
  attemptId: string
  /** 已拿到的报告 */
  report: AttemptReport | null
  status: ReportStatus
  /** 失败 / 断网时展示给用户的原因 */
  message: string

  /** 指定要复盘的那一局。会清掉上一份报告，避免看到别人的数字 */
  begin: (attemptId: string) => void
  /** 进入「生成中」 */
  startGenerating: () => void
  /** 拿到报告 */
  succeed: (report: AttemptReport) => void
  /** 生成失败（服务器明确报错） */
  fail: (message: string) => void
  /** 连不上服务器 */
  goOffline: (message: string) => void
  /** 清空 */
  reset: () => void
}

export const useReportStore = create<ReportState>((set) => ({
  attemptId: '',
  report: null,
  status: 'idle',
  message: '',

  begin: (attemptId) =>
    // 换了目标那一局就必须丢掉上一份报告：留着会出现「标题是新卷轴、
    // 数字是旧一局」这种最难被发现的错配
    set({ attemptId, report: null, status: 'idle', message: '' }),

  startGenerating: () => set({ status: 'generating', message: '' }),

  succeed: (report) => set({ report, status: 'ready', message: '' }),

  fail: (message) => set({ status: 'failed', message }),

  goOffline: (message) => set({ status: 'offline', message }),

  reset: () => set({ attemptId: '', report: null, status: 'idle', message: '' })
}))
