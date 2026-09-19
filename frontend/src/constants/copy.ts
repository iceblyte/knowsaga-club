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
  playAgain: '再来一局',
  /**
   * 交卷没能送到服务端时的说明。
   *
   * 报告是服务端基于 `attempts` 生成的，没有这一局就无从生成 ——
   * 此时**不能**放用户跳到日志页看一个空态（他会以为报告功能坏了）。
   * 留在结算页说明原因：本地数字仍然是对的，只是档案与报告这次没落上。
   */
  reportUnavailable: '这次成绩没能上传，冒险日志暂时无法生成'
} as const

/**
 * 冒险日志（原型 03 第 1 / 2 / 3 屏，以及失败 / 断网两态）。
 *
 * ## 关于「生成失败」的文案：为什么不用后端返回的原文
 *
 * 后端 `AI_GENERATION_FAILED`（5001）的默认文案是「出题失败，请重试」——
 * 这个码被出题链与报告链**共用**，而「出题」这个词出现在报告页上就是错的。
 * 原型的图注也明确要求：「失败文案给出具体原因与重试动作，
 * 不用『操作失败』这类无信息量的提示」。
 *
 * 因此这里按错误码给出**报告语境的**替换文案，未列出的码回退到后端原文。
 * 放在前端而不是改后端的默认文案：改默认值会同时改掉出题链的提示，
 * 而两个链需要的是不同的说法（一个说「重新生成题目」，一个说「重新生成报告」）。
 *
 * ## 关于「演示数据」
 *
 * 百分位与档位都是 `accuracy × 0.9` 的派生值，不是真实用户池统计出来的。
 * 结算页已经标注过「（演示数据）」，报告页沿用同一口径 —— 这是产品红线，
 * 不能在更详细的页面上反而把它隐掉。
 */
export const REPORT_COPY = {
  navTitle: '冒险日志',
  summaryNavTitle: '知识总结',
  suggestionsNavTitle: '下一步建议',

  // ---- 第 1 屏 · 主视图 ----
  xpLabel: 'XP',
  coinsLabel: '金币',
  statCorrect: '答对',
  statWrong: '答错',
  statAvgTime: '平均用时',
  percentilePrefix: '本局超过社团里',
  percentileSuffix: '的冒险者',
  /**
   * 百分位是 `accuracy × 0.9` 的派生值，不是真实用户池统计。
   * 结算页已经标注过，报告页把它放在更显眼的位置（一条进度条），
   * 更不能隐掉 —— 这是产品红线，不是免责声明。
   */
  percentileNote: '百分位为演示数据，不是真实统计',
  /**
   * 模板兜底时的说明。
   *
   * 必须写出来：模板报告读起来明显更「制式」，不说清会让用户
   * 以为 AI 就这个水平，进而对产品失去信心 —— 而实际上只是这一次没调到模型。
   */
  degradedNote: '这份报告由固定话术整理而成，上面的数字与你的作答完全一致',
  /** 底部按钮。MVP 不做 Canvas 海报，按开发计划 §3.7 改接微信原生转发 */
  share: '生成分享海报',
  backToHall: '返回社团大厅',
  /** 分享卡片的默认标题（用户没点转发时微信不会用到，但配置缺失会取页面标题） */
  shareTitle: '我在知拾冒险设闯过了一关',
  /** 小程序点「生成分享海报」后的引导：转发入口在微信右上角，页面里点不出来 */
  shareGuide: '点右上角「…」转发给好友',
  /** H5 没有原生转发能力 —— 明说，而不是给一个点了没反应的按钮 */
  shareH5Hint: '在微信里打开就能转发给好友',

  // ---- 第 2 屏 · 三句话总结 ----
  summaryLabel: '三句话知识总结',
  masteredLabel: '掌握较好的知识点',
  weakLabel: '需要再巩固的知识点',
  /**
   * 某一组知识点为空时的说明。
   *
   * 两句话必须分开写：全对的一局里「需要再巩固」本来就该是空的，
   * 此时说「还没有可以归纳的知识点」会读成「这一项没加载出来」。
   * 同样的道理，全错的一局里空的会是「掌握较好」那一组。
   */
  noMastered: '这次还没归纳出掌握得很稳的知识点',
  noWeak: '这次没有需要额外巩固的知识点',
  reviewWeak: '复习薄弱知识点',

  // ---- 第 3 屏 · 复习建议 ----
  backToReport: '回到冒险日志',
  /** 动作缺失时的兜底标题（理论上不会出现：后端保证三条文案） */
  adviceFallbackTitle: '继续下一张卷轴',

  // ---- 生成中 ----
  generatingTitle: '正在整理这次的冒险日志',
  generatingHint: '通常几秒就好，请稍候',

  // ---- 生成失败（原型 03 第 6 屏）----
  failedTitle: '报告生成失败',
  /** 兜底文案。正常情况下用下面按错误码映射的那张表 */
  failedBody: 'AI 服务暂时繁忙，你的答题记录已经保存，不会丢失。',
  regenerate: '重新生成报告',
  viewDetails: '先看看答题详情',

  // ---- 断网（原型 03 第 7 屏）----
  offlineNavTitle: '社团大厅',
  offlineTitle: '网络好像断开了',
  offlineBody: '已下载的冒险日志仍可查看，召唤副本需要联网。',
  reconnect: '重新连接',
  viewHistory: '查看历史日志',

  // ---- 空态：本地没有可复盘的一局 ----
  emptyTitle: '日志本还是空的',
  emptyBody: '完成一次副本挑战，这里就会出现你的正确率、答对题数与复习建议。',

  // ---- 尚未实现的能力（诚实提示，不静默失败）----
  historyUnavailable: '历史日志还没开放，敬请期待',
  reviewUnavailable: '错题复习还没开放，敬请期待',
  detailsUnavailable: '答题详情还没开放，可以回到大厅再挑战一次'
} as const

/**
 * 报告失败时按业务错误码替换的文案。
 *
 * 见文件头说明：这两个码的默认文案是「出题…」，出现在报告页上是错的。
 */
export const REPORT_ERROR_TEXT: Record<number, string> = {
  4004: '这次生成的报告已经过期，请重新生成',
  5000: '整理报告时出了点问题，你的答题记录已经保存',
  5001: 'AI 服务暂时繁忙，你的答题记录已经保存，不会丢失',
  5030: '整理报告花了太久，你的答题记录已经保存，请重试',
  5031: '当前使用的人有点多，请稍后再试'
}

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
