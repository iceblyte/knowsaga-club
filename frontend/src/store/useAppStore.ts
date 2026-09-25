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

import { QUIZ_DIFFICULTY, QUIZ_QUESTION_COUNT } from '../constants/api'
import type { Difficulty } from '../types/api'

/**
 * 本次召唤的出题参数。
 *
 * ⚠️ **它必须由「发起召唤的那个入口」显式写入**，不能只依赖默认值 ——
 * 曾经设过知识库的 `kbId` 会留在这里，下一次从大厅发起的召唤就会莫名其妙地
 * 带着上一个库取材。大厅的提交路径因此每次显式写回 `DEFAULT_QUIZ_OPTIONS`。
 *
 * 三个字段都是**请求级**的（出题接口的入参），与 `userInput` / `useSearch`
 * 同一层、同一生命周期：都是「这一次召唤」的一部分，没有跨局保留的意义。
 */
export interface QuizOptions {
  /** 题量。后端 `MIN_QUESTIONS=3` / `MAX_QUESTIONS=5` 是硬边界 */
  questionCount: number
  /** 难度偏好；`mixed` 让模型自己分配（与后端默认一致） */
  difficulty: Difficulty | 'mixed'
  /** 从哪个知识库取材。**空串表示不取材**（`kb_id` 字段整个不发给后端） */
  kbId: string
}

/** 大厅那条路（以及所有「不带知识库」的召唤）用的默认参数 —— 与接入知识库之前逐位一致。 */
export const DEFAULT_QUIZ_OPTIONS: QuizOptions = {
  questionCount: QUIZ_QUESTION_COUNT,
  difficulty: QUIZ_DIFFICULTY,
  kbId: ''
}

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

  /**
   * 后端是否开启了私有知识库。
   * 来自 `GET /api/v1/health` 的 `knowledge_base_enabled`；启动时探测一次。
   *
   * ⚠️ 与 `searchEnabled` 同一层：都是**后端能力**，不是用户意愿
   * （对比下面的 `useSearch`）。知识库那几处入口都按它显隐。
   *
   * 默认 `false`（与 `searchEnabled` 一致）：探测失败就当「没开」，
   * 于是不显示入口 —— 后端都没探通，点进去也只会拿到网络错误。
   */
  knowledgeBaseEnabled: boolean
  setKnowledgeBaseEnabled: (enabled: boolean) => void

  /**
   * 本次召唤的**意愿**：要不要让 AI 主动联网补充。
   *
   * ⚠️ 与 `searchEnabled` 是两件事，别合并：
   * - `searchEnabled` 是**后端能力**（有没有配 key），用户改不了，读一次就不变；
   * - `useSearch` 是**用户意愿**（这一局想不想联网），大厅那只 pill 点一下就翻转。
   * 两者都在时 pill 才是蓝色（「AI 将联网补充」），任一为假都退成中性文案。
   *
   * 内存态、**不持久化**：它与 `userInput` 同一层、同一生命周期 ——
   * 用户下次进小程序时应当重新表达一次意愿，而不是被上次的选择默默替他决定。
   */
  useSearch: boolean
  setUseSearch: (enabled: boolean) => void

  /** 出题参数（题量 / 难度 / 取材的知识库），由发起召唤的入口写入 */
  quizOptions: QuizOptions
  setQuizOptions: (options: QuizOptions) => void

  /** 后端可达性；为 false 时前端展示网络异常态 */
  backendReachable: boolean
  setBackendReachable: (reachable: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  userInput: '',
  setUserInput: (text) => set({ userInput: text }),

  searchEnabled: false,
  setSearchEnabled: (enabled) => set({ searchEnabled: enabled }),

  knowledgeBaseEnabled: false,
  setKnowledgeBaseEnabled: (enabled) => set({ knowledgeBaseEnabled: enabled }),

  useSearch: true,
  setUseSearch: (enabled) => set({ useSearch: enabled }),

  quizOptions: DEFAULT_QUIZ_OPTIONS,
  setQuizOptions: (options) => set({ quizOptions: options }),

  backendReachable: true,
  setBackendReachable: (reachable) => set({ backendReachable: reachable })
}))
