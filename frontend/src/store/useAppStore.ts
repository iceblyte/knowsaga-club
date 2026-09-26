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
 * 四个字段都是**请求级**的（出题接口的入参），与 `userInput` 同一层、
 * 同一生命周期：都是「这一次召唤」的一部分，没有跨局保留的意义。
 */
export interface QuizOptions {
  /** 题量。后端 `MIN_QUESTIONS=3` / `MAX_QUESTIONS=5` 是硬边界 */
  questionCount: number
  /** 难度偏好；`mixed` 让模型自己分配（与后端默认一致） */
  difficulty: Difficulty | 'mixed'
  /** 从哪个知识库取材。**空串表示不取材**（`kb_id` 字段整个不发给后端） */
  kbId: string
  /**
   * 本次要不要给题目生成配图（后端 `generate_images`）。
   *
   * ⚠️ 它是**意愿**，而 `imageGenerationEnabled` 是**能力** —— 两者是两件事，
   * 别合并（与 `useSearch` / `searchEnabled` 同一组关系）：
   * 能力由后端 `/health` 给，用户改不了；意愿归用户，大厅那只 pill 与
   * 生成设置页那张卡各点一下就能翻。
   *
   * 放进 `QuizOptions` 而不是像 `useSearch` 那样单独一格，是因为它**只在
   * 发起召唤的那两个入口**上被设置（大厅 / 生成设置页），没有第三个能改它的
   * 地方；而 `useSearch` 那只 pill 在大厅是常驻的。放这里也顺带拿到了
   * 「大厅提交时显式写回默认参数」这道防串味闸门。
   */
  generateImages: boolean
}

/** 大厅那条路（以及所有「不带知识库」的召唤）用的默认参数 —— 与接入配图之前逐位一致。 */
export const DEFAULT_QUIZ_OPTIONS: QuizOptions = {
  questionCount: QUIZ_QUESTION_COUNT,
  difficulty: QUIZ_DIFFICULTY,
  kbId: '',
  /** 默认**不生成配图**：与后端 `generate_images` 的默认值一致（design D1） */
  generateImages: false
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
   * 后端是否具备「给题目生成配图」的能力。
   * 来自 `GET /api/v1/health` 的 `image_generation_enabled`；启动时探测一次。
   *
   * ⚠️ 后端下发的是**派生值**（开关 && dashscope key && COS 凭据齐全），
   * 所以这里读到 `true` 就等于「现在真的点得动」。
   *
   * 默认 `false`：探测失败就当「没这个能力」，于是生成设置页那张卡与大厅的
   * 配图 pill 都不出现 —— 后端都没探通，给一个必然失败的入口只会制造一次
   * 无谓的点击（与 `searchEnabled` / `knowledgeBaseEnabled` 同一条纪律）。
   *
   * 与 `QuizOptions.generateImages`（**意愿**）是两件事：
   * 这一格决定「开关显不显示」，那一格决定「这次要不要配图」。
   */
  imageGenerationEnabled: boolean
  setImageGenerationEnabled: (enabled: boolean) => void

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

  imageGenerationEnabled: false,
  setImageGenerationEnabled: (enabled) => set({ imageGenerationEnabled: enabled }),

  useSearch: true,
  setUseSearch: (enabled) => set({ useSearch: enabled }),

  quizOptions: DEFAULT_QUIZ_OPTIONS,
  setQuizOptions: (options) => set({ quizOptions: options }),

  backendReachable: true,
  setBackendReachable: (reachable) => set({ backendReachable: reachable })
}))
