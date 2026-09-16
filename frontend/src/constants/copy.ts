/**
 * 全局文案。
 *
 * 集中管理的原因：原型里有大量精心打磨的文案（「拾万千知识，闯无尽关卡」
 * 「不会扣分」），它们是产品语气的一部分。分散在几十个组件里迟早会被改歪，
 * 集中一处便于校对与统一调整。
 *
 * ## 与原型不一致的两处，以及为什么
 *
 * 1. **`QUIZ_COPY.exitBody`**：原型说「当前进度会保存，下次可以从第 3 题继续挑战」。
 *    但 MVP 没有持久化，也没有「继续上次挑战」的入口 —— 这句话在本期无法兑现，
 *    照抄就是在骗用户。故改为如实说明「离开后需要从第 1 题重新开始」。
 * 2. **`SUMMON_COPY`** 里的等待说明：原型第 4 屏的状态卡文案全部由后端 `steps` 提供
 *    （名字与详情都是真实进度），前端**不复述实现细节**。凡是「这一步在做什么」
 *    这类描述内部机制的话，都不该出现在用户界面上。
 */

/** 三步生成过程的兜底文案。
 *
 * ⚠️ 正常情况下这些**根本用不到** —— 三步状态卡的名字与详情全部来自后端
 * `GET /tasks/{id}` 的 `steps`。这里只用于「首次轮询还没回来」的那一小段空窗，
 * 而且在拿到后端数据后立刻被覆盖。
 */
export const SUMMON_STEPS = {
  retrieveNoop: '理解你的输入',
  retrieveOnline: '联网检索知识',
  generate: '生成闯关题目',
  validate: '校验题目结构'
} as const

/** 副本召唤中（原型 01 第 4 屏） */
export const SUMMON_COPY = {
  navTitle: '召唤中',
  title: '正在生成知识副本',
  /** 生成完成、正在进入副本时的标题 */
  readyTitle: '知识副本已生成',
  /** 兜底入口：自动跳转没成功时才会被用户看到 */
  enter: '进入副本',
  cancelConfirmTitle: '要放弃这次召唤吗？',
  cancelConfirmBody: '已经生成的部分会一并丢弃。',
  cancelConfirmPrimary: '继续等待',
  cancelConfirmSecondary: '放弃本次召唤',
  failedTitle: '这次召唤没能完成',
  retry: '重新生成',
  /** 兜底的等待说明。不描述内部步骤，只说明「要多久、能做什么」 */
  waitingHint: '生成一本副本通常需要十几秒，请稍候',
  cancelled: '已放弃本次召唤'
} as const

/** 副本确认页（原型 01 第 5 屏） */
export const CONFIRM_COPY = {
  navTitle: '知识副本',
  regenerate: '重新生成',
  start: '开始挑战副本',
  noPenaltyHint: '答错也会给出完整讲解，不会扣分',
  knowledgeLabel: '本次覆盖的知识点',
  /** 题库丢失（小程序重启 / 内存被回收）时的说明与出口 */
  emptyTitle: '这份副本已经不在了',
  emptyHint: '副本只保留在当前运行期间，重新打开后需要再召唤一次',
  backHome: '返回社团大厅'
} as const

/** 挑战副本（原型 02） */
export const QUIZ_COPY = {
  navTitle: '挑战副本',
  /** 判断题提示 */
  lastQuestionHint: '这是本局最后一题，作答后生成冒险日志',
  /** 折叠态摘要 */
  collapseHint: '点击查看本题知识讲解',
  collapse: '收起',
  expand: '展开',
  submit: '确认作答',
  submitMultiple: (count: number) => `已选 ${count} 项 · 确认作答`,
  next: '下一题',
  last: '完成挑战',
  relatedLabel: '相关知识点',
  /** 退出确认 */
  exitTitle: '要离开这个副本吗？',
  exitBody: '离开后本局作答记录不会保留，需要从第 1 题重新开始。',
  exitPrimary: '继续挑战',
  exitSecondary: '退出副本'
} as const

/** 通关结算（原型 01 第 6 屏） */
export const SETTLE_COPY = {
  title: '副本通关',
  badge: '已通关',
  xpLabel: '经验值 XP',
  coinsLabel: '冒险金币',
  percentilePrefix: '超过社团里',
  percentileSuffix: '的冒险者',
  /** 百分位是确定性派生值，不是真实统计 —— 必须让用户知道 */
  percentileNote: '（演示数据）',
  viewReport: '查看冒险日志',
  playAgain: '再来一局'
} as const

/** 通用提示 */
export const COMMON_COPY = {
  /** P1 功能占位提示 */
  comingSoon: '该功能正在建造中，敬请期待',
  /** 生成失败 */
  generateFailed: '出题失败了，再来一次吧',
  retry: '重新生成',
  back: '返回',
  /** 输入不合规 */
  inputTooShort: '再多写几个字吧'
} as const
