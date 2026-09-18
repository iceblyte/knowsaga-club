/**
 * 本局答题会话。
 *
 * ## 为什么放在全局 store 而不是答题页的 state
 *
 * 结算页需要「所有题的判定结果」才能算总分，而它是**另一个页面**；
 * 把结果留在答题页的组件里，页面一卸载就没了。所以这份状态必须活过页面。
 *
 * ## 但它是「一局」的状态，不是「用户」的状态
 *
 * 和 `useAppStore` 的分工：`useAppStore` 放跨局的（输入的主题、后端能力开关、
 * 冒险者档案），这里放**只在一局内有效**的东西。任何需要跨局保留的数据
 * 都不该进这个 store —— MVP 不做持久化，放进来只会制造「重启就丢」的错觉。
 *
 * ## 退出即作废
 *
 * `reset()` 会清空全部会话状态。答题页的退出确认弹层文案（见 constants/copy.ts）
 * 明确告诉用户「离开后本局作答记录不会保留」，所以退出时**必须真的调 reset()**，
 * 否则文案就是在骗人。原型那句「进度会保存，下次可以继续」在本期无法兑现
 * （没有持久化、也没有「继续上次挑战」的入口），故文案已改为诚实版本。
 */

import { create } from 'zustand'

import type { AttemptSubmitResponse, Quiz } from '../types/api'
import { uuidV4 } from '../utils/id'
import type { QuestionResult } from '../utils/scoring'

interface QuizState {
  /**
   * 已生成、等待用户确认的题库（「副本确认页」要展示它）。
   *
   * 为什么单独放一个字段而不是直接 `start()`：
   * 「生成完成」和「用户决定开始挑战」是两个不同的时刻。
   * 如果出题一完成就起算会话，那么用户在确认页犹豫的两分钟
   * 会被算进 Phase 3 报告的「用时」里 —— 那个数字是给用户看自己答题速度的，
   * 不该包含阅读题目的时间。
   */
  pendingQuiz: Quiz | null
  /** 当前进行中的题库；null 表示没有进行中的一局 */
  quiz: Quiz | null
  /** 当前题号，0 起 */
  currentIndex: number
  /** 已判定结果，按题号索引（`quiz.questions[].id`） */
  results: Record<string, QuestionResult>
  /** 开始时刻（ms），用于 Phase 3 报告的用时统计 */
  startedAt: number
  /** 结束时刻（ms），0 表示尚未结束 */
  finishedAt: number
  /**
   * 本局的交卷令牌（一个 v4 UUID）。
   *
   * **一局一个，在 `start()` 时生成**，而不是在结算页生成 ——
   * 结算页可能被重挂载（用户返回再进来），在那里生成会换出一个新令牌，
   * 服务端就会把它当成**新的一局**，档案里凭空多一次挑战记录。
   * 放在「开局」这个唯一时刻，重试与重挂载自动复用同一个值。
   */
  clientToken: string
  /**
   * 服务端的结算结果（权威口径）。
   *
   * 结算页拿到之后写进来，供：
   *  1. 页面重挂载时直接用，不再打一次请求；
   *  2. 冒险日志（Phase C）与「再来一局」复用 `attempt_id`。
   */
  attempt: AttemptSubmitResponse | null

  /** 记录一份刚生成好的题库，等待确认 */
  setPendingQuiz: (quiz: Quiz | null) => void
  /** 开启新的一局。会清空上一局的全部痕迹 */
  start: (quiz: Quiz) => void
  /** 记录一题的判定结果 */
  recordResult: (result: QuestionResult) => void
  /** 跳到指定题号 */
  setCurrentIndex: (index: number) => void
  /** 标记本局结束 */
  finish: () => void
  /** 记录服务端的结算结果 */
  setAttempt: (attempt: AttemptSubmitResponse | null) => void
  /** 清空会话 */
  reset: () => void
}

export const useQuizStore = create<QuizState>((set) => ({
  pendingQuiz: null,
  quiz: null,
  currentIndex: 0,
  results: {},
  startedAt: 0,
  finishedAt: 0,
  clientToken: '',
  attempt: null,

  setPendingQuiz: (quiz) => set({ pendingQuiz: quiz }),

  start: (quiz) =>
    set({
      quiz,
      currentIndex: 0,
      results: {},
      startedAt: Date.now(),
      finishedAt: 0,
      // 新的一局 = 新的令牌。上一局的令牌绝不能带过来，
      // 否则第二次交卷会被服务端当成「重试」而回放上一局的结果。
      clientToken: uuidV4(),
      attempt: null
    }),

  recordResult: (result) =>
    set((state) => ({ results: { ...state.results, [result.questionId]: result } })),

  setCurrentIndex: (index) => set({ currentIndex: index }),

  finish: () => set({ finishedAt: Date.now() }),

  setAttempt: (attempt) => set({ attempt }),

  reset: () =>
    set({
      pendingQuiz: null,
      quiz: null,
      currentIndex: 0,
      results: {},
      startedAt: 0,
      finishedAt: 0,
      clientToken: '',
      attempt: null
    })
}))
