/**
 * 本地判题与结算。
 *
 * ## 为什么判题在前端
 *
 * 已确认的决策：**挑战副本是本地即时判题**（开发计划 Phase 2 · 2.8）。
 * 每答一题就发一次请求会让「答对后立刻变绿」这件事被网络延迟绑架 ——
 * 而正确答案本来就在题库里（`Quiz.question` 是随题库一起下发的），
 * 前端手里有全部判题所需信息。后端只在 Phase 3 接收**汇总后的结果**用于生成报告。
 *
 * ## 规则来源
 *
 * 全部照抄 `docs/MVP开发计划.md` §9，不在这里重新发明：
 * 单题满分 单选 40 / 多选 60 / 判断 20；答错一律 +0 不扣分；
 * `coins = floor(XP × 0.18)`；`percentile = clamp(round(accuracy × 0.9), 5, 95)`。
 *
 * 这些数字与原型逐处对齐过：5 题全对 = 200 XP；答对 4 题 = 180 XP；
 * 180 XP → 32 金币；正确率 80% → 超过 72% 的冒险者。
 * **改动任何一个数之前先回去看原型那三处是否还吻合。**
 */

import type { QuestionType, Quiz, QuizQuestion } from '../types/api'

/** 单题判定结果 */
export type QuestionOutcome = 'correct' | 'partial' | 'wrong'

/** 各题型满分经验值（§9.1） */
const MAX_XP: Record<QuestionType, number> = {
  single: 40,
  multiple: 60,
  judge: 20
}

/** 多选题部分正确的固定比例（§9.1，已确认口径为固定 50%，不按项数比例） */
const MULTIPLE_PARTIAL_RATIO = 0.5

export interface QuestionResult {
  questionId: string
  type: QuestionType
  /** 用户实际选中的选项键（已排序，便于比较与展示） */
  selected: string[]
  /** 正确答案 */
  answer: string[]
  outcome: QuestionOutcome
  earnedXp: number
  maxXp: number
}

/** 该题的满分经验值 */
export function maxXpOf(type: QuestionType): number {
  return MAX_XP[type]
}

/**
 * 判定一道题。
 *
 * 多选题的判定**必须按下面的顺序**，否则会出现「错选也给分」的漏洞：
 *
 * ```
 * 1. selected 含不属于 answer 的项  → 0 XP   （错选一票否决）
 * 2. selected == answer            → 60 XP  （完全正确）
 * 3. selected ⊂ answer 且非空       → 30 XP  （部分正确，固定 50%）
 * 4. 其余（selected 为空）          → 0 XP
 * ```
 *
 * 把第 1 步放在最前面是关键：如果先判「是不是 answer 的子集」，
 * 那么「从 4 个选项里选 1 个正确项」也会落进第 3 步拿到 30 分，
 * 而它实际上只是一次蒙对。
 *
 * @param selected 用户选中的选项键；单选/判断传长度为 1 的数组（或空数组）
 */
export function gradeQuestion(question: QuizQuestion, selected: string[]): QuestionResult {
  const maxXp = maxXpOf(question.type)
  const answer = [...question.answer]
  const picked = [...new Set(selected)]
  const pickedSet = new Set(picked)
  const answerSet = new Set(answer)

  let outcome: QuestionOutcome = 'wrong'
  let earnedXp = 0

  if (question.type === 'multiple') {
    const hasWrongPick = picked.some((key) => !answerSet.has(key))

    if (hasWrongPick) {
      outcome = 'wrong'
      earnedXp = 0
    } else if (picked.length === answer.length && answer.every((key) => pickedSet.has(key))) {
      outcome = 'correct'
      earnedXp = maxXp
    } else if (picked.length > 0) {
      // 走到这里蕴含 picked ⊂ answer 且非空（上面已排除含错选与全对）
      outcome = 'partial'
      earnedXp = Math.floor(maxXp * MULTIPLE_PARTIAL_RATIO)
    } else {
      outcome = 'wrong'
      earnedXp = 0
    }
  } else {
    // 单选 / 判断：只有「选中唯一正确项」才算对
    const isCorrect = picked.length === 1 && answerSet.has(picked[0])
    outcome = isCorrect ? 'correct' : 'wrong'
    earnedXp = isCorrect ? maxXp : 0
  }

  return {
    questionId: question.id,
    type: question.type,
    selected: picked.sort(),
    answer: [...answer].sort(),
    outcome,
    earnedXp,
    maxXp
  }
}

export interface QuizSummary {
  results: QuestionResult[]
  /** 完全答对的题数（多选题的部分正确**不计入**，与原型「正确率 4 / 5」的口径一致） */
  correctCount: number
  totalCount: number
  /** 正确率百分比，0–100 整数 */
  accuracy: number
  /** 本局获得经验值 */
  totalXp: number
  /** 本局满分经验值 */
  maxXp: number
  /** 冒险金币 */
  coins: number
  /** 演示用的百分位（§9.4） */
  percentile: number
}

/**
 * 汇总一局答题结果。
 *
 * 未作答的题按 0 分计 —— 这保证 `results.length === quiz.questions.length`，
 * 结算页的「正确率 4 / 5」分母永远是题量，不会因为中途退出而缩水。
 *
 * @param results 按题号索引的判定结果（来自 `useQuizStore`）
 * @param startedAt 开始时刻（ms）；不传则不计算用时（用时给 Phase 3 的报告用）
 * @param finishedAt 结束时刻（ms）
 */
export function summarizeQuiz(
  quiz: Quiz,
  results: Record<string, QuestionResult>,
  startedAt = 0,
  finishedAt = 0
): QuizSummary & { startedAt: number; finishedAt: number; durationSeconds: number } {
  const ordered: QuestionResult[] = quiz.questions.map(
    (question) =>
      results[question.id] ?? {
        questionId: question.id,
        type: question.type,
        selected: [],
        answer: [...question.answer].sort(),
        outcome: 'wrong' as QuestionOutcome,
        earnedXp: 0,
        maxXp: maxXpOf(question.type)
      }
  )

  const totalCount = ordered.length
  const correctCount = ordered.filter((item) => item.outcome === 'correct').length
  const totalXp = ordered.reduce((sum, item) => sum + item.earnedXp, 0)
  const maxXp = ordered.reduce((sum, item) => sum + item.maxXp, 0)

  const accuracy = totalCount === 0 ? 0 : Math.round((correctCount / totalCount) * 100)

  return {
    results: ordered,
    correctCount,
    totalCount,
    accuracy,
    totalXp,
    maxXp,
    coins: Math.floor(totalXp * 0.18),
    // 无真实用户池，用正确率做单调映射（§9.4）。界面必须标注这是演示值。
    percentile: Math.min(95, Math.max(5, Math.round(accuracy * 0.9))),
    startedAt,
    finishedAt,
    durationSeconds:
      startedAt > 0 && finishedAt > startedAt ? Math.round((finishedAt - startedAt) / 1000) : 0
  }
}

/** 题型的中文名，用于确认页的题型构成与答题页的题型胶囊 */
export const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  single: '单选题',
  multiple: '多选题',
  judge: '判断题'
}

/**
 * 确认页的题型构成文案，如「3 单选 · 1 多选 · 1 判断」。
 *
 * 与后端 `QuestionStats.summary_text()` 的措辞**故意不同**：后端给「3 单选」，
 * 确认页的 statlab 需要「单选题」这种完整称呼。只在有题量的题型上出卡片 ——
 * 「0 多选题」这种卡片除了占位没有任何信息量。
 */
export function questionStatEntries(stats: {
  single: number
  multiple: number
  judge: number
}): { type: QuestionType; count: number }[] {
  const entries: { type: QuestionType; count: number }[] = [
    { type: 'single', count: stats.single },
    { type: 'multiple', count: stats.multiple },
    { type: 'judge', count: stats.judge }
  ]
  return entries.filter((entry) => entry.count > 0)
}

/** 确认页「约 N 分钟」的估算。5 题 → 4 分钟，与原型一致。 */
export function estimateMinutes(questionCount: number): number {
  return Math.max(1, Math.round(questionCount * 0.8))
}
