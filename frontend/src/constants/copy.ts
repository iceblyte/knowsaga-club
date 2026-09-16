/**
 * 全局文案。
 *
 * 集中管理的原因：原型里有大量精心打磨的文案（「拾万千知识，闯无尽关卡」
 * 「不会扣分」「进度会保存」），它们是产品语气的一部分。分散在几十个组件里
 * 迟早会被改歪，集中一处便于校对与统一调整。
 */

/** 三步生成过程的文案（原型 01 第 4 屏）。 */
export const SUMMON_STEPS = {
  /** 未开启联网检索时，由后端 NoopSearchProvider 提供文案 */
  retrieveNoop: '理解你的输入',
  /** 开启联网检索后，由真实 Provider 提供文案（原型原文） */
  retrieveOnline: '联网检索知识',
  generate: '生成闯关题目',
  validate: '校验题目结构'
} as const

/** 挑战副本相关文案（原型 02，逐条照搬） */
export const QUIZ_COPY = {
  /** 判断题提示 */
  lastQuestionHint: '这是本局最后一题，作答后生成冒险日志',
  /** 折叠态摘要 */
  collapseHint: '点击查看本题知识讲解',
  /** 退出确认 */
  exitTitle: '要离开这个副本吗？',
  exitBody: '当前进度会保存，下次可以从第 %d 题继续挑战。',
  exitPrimary: '继续挑战',
  exitSecondary: '保存并退出',
  /** 提交中 */
  submittingTitle: '正在撰写冒险日志',
  submittingSub: '统计答题情况并生成复盘报告'
} as const

/** 通用提示 */
export const COMMON_COPY = {
  /** P1 功能占位提示 */
  comingSoon: '该功能正在建造中，敬请期待',
  /** 生成失败 */
  generateFailed: '出题失败了，再来一次吧',
  retry: '重新生成'
} as const
