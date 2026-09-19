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

// =============================================================================
// 冒险者档案（Phase D：看板 / 知识树 / 错题本 / 勋章墙 + 个人中心）
// =============================================================================
//
// ## 与原型不一致的地方，以及为什么
//
// 1. **环比一律不写「较上周」**。原型只有「近 7 天」一种口径，所以写「较上周」
//    是准确的；本实现支持 7/30 天切换，30 天区间的对比窗口是前 30 天，
//    再说「上周」就是假的。改成「较上一周期」。
//    例外是柱状图 —— 柱子**恒为最近 7 根**（与所选区间无关），
//    所以它的对比说法固定为「较前 7 天」。
// 2. **没有「连续 3 周上升」这句**。后端只提供本周期与上周期两个数，
//    说不出「3 周」；要说得先存 3 周的历史，那是另一件事。
// 3. **知识点为空时的话分开写**（`noMastered` / `noWeak`），不是一句通用的
//    「暂无数据」——见 REPORT_COPY 里的说明，同一道理。
// 4. **`环比缺失就说比不了`**（`deltaNoBaseline`）。上周期没有数据时，
//    后端给 `null`；把它当 0% 渲染成「与上周持平」是在编造事实。

/**
 * 数据看板（原型 04·3）。
 *
 * 三个数字的环比文案**分开写**，因为它们的比较基准不同：
 * 柱状图固定比前 7 天，正确率与用时比的是「上一个等长周期」。
 * 用同一句话概括会在 30 天口径下同一屏出现两种基准却写着同一个说法。
 */
export const DASHBOARD_COPY = {
  navTitle: '数据看板',

  range7: '近 7 天',
  range30: '近 30 天',

  barsTitle: '近 7 天答题量',
  /** 柱状图恒比前 7 天 —— 与所选区间无关 */
  barsDeltaUp: (percent: number) => `较前 7 天 +${percent}%`,
  barsDeltaDown: (percent: number) => `较前 7 天 −${Math.abs(percent)}%`,
  barsDeltaFlat: '较前 7 天持平',

  accuracyTitle: '正确率',
  durationTitle: '平均单局用时',

  /** 正确率 / 用时的对比基准是「上一个等长周期」，与柱状图不同 */
  periodDeltaUp: (points: number) => `较上一周期 +${points} 个百分点`,
  periodDeltaDown: (points: number) => `较上一周期 −${Math.abs(points)} 个百分点`,
  periodDeltaFlat: '与上一周期持平',
  periodFaster: (duration: string) => `较上一周期快 ${duration}`,
  periodSlower: (duration: string) => `较上一周期慢 ${duration}`,

  /**
   * 上周期没有数据时不编造对比。
   *
   * 这是看板上唯一一句话出现在「本期有数、上期没有」的情况 ——
   * 新用户的第二周几乎必然遇到，所以必须有个诚实的说法。
   */
  deltaNoBaseline: '上一周期还没有记录，暂时比不了',

  domainsTitle: '各知识领域掌握度',
  /** 领域统计是**全量口径**（不分区间），一条都没有时说明还没答过带知识点的题 */
  domainsEmpty: '还没有可以统计的领域',

  /**
   * 窗口内没有记录时的占位。
   *
   * 与 `deltaNoBaseline` 的区别：那句说的是「上一周期没数据，比不了」，
   * 这句说的是「本周期就没数据，没得看」。空窗口里正确率与平均用时都是 0，
   * 原样渲染成「正确率 0% · 用时 0 秒」读起来像考砸了，所以显示「—」。
   */
  rangeEmptyValue: '—',
  rangeEmpty: '这个区间还没有记录',

  emptyTitle: '还没有可以画成图的数据',
  emptyBody: '完成一次副本挑战，这里就会出现你的答题量、正确率与领域掌握度。',
  emptyCta: '去召唤一张卷轴'
} as const

/**
 * 知识树（原型 04·4）。
 *
 * 三态的措辞直接用原型给的「已点亮 / 进行中 / 未开始」——
 * 这三个词已经是产品语言，换成「已完成 / 学习中 / 未学习」会丢掉「点亮」
 * 这个与「卷轴 / 冒险」一致的世界观。
 */
export const KNOWLEDGE_TREE_COPY = {
  navTitle: '知识树',
  litCount: (count: number) => `已点亮 ${count} 个知识领域`,

  stateLit: '已点亮',
  stateGrowing: '进行中',
  stateNotStarted: '未开始',

  cta: '点亮新领域',

  /**
   * 一句都说不出时的替代文案。
   *
   * 后端的 `suggestion` 在「全部点亮」或「一个领域都没有」时是空串 ——
   * 它刻意不返回「继续加油」这种放之四海而皆准的话（那种话在界面上
   * 和占位符没有区别）。但版面上不能留空，所以这里给一句**描述状态**的话，
   * 而不是打气。
   */
  noSuggestion: '这棵树上的领域都已经点亮了，再开一张新卷轴就能长出新的枝丫。',

  emptyTitle: '知识树还是一张白纸',
  emptyBody: '第一次召唤卷轴之后，这里会长出属于你的知识领域。',
  emptyCta: '去召唤一张卷轴'
} as const

/**
 * 错题本 · 旧识重温（原型 04·7）。
 *
 * 引言的数字用的是**到期数**（`due_count`）而不是列表长度：原型那句
 * 「这 3 道题今天最适合重做」说的是「现在该做几道」，不是「错题本里有多少」。
 * 列表里同时列着未到期的题（它们只能看、不能做），所以两个数必须分开。
 */
export const REVIEW_COPY = {
  navTitle: '旧识重温',
  sectionTitle: '待复习错题',
  /** 行首 28px 方块里的字（原型是「题」） */
  icon: '题',
  duePill: (count: number) => `${count} 题到期`,

  intro: (dueCount: number) =>
    `按艾宾浩斯遗忘曲线，这 ${dueCount} 道题今天最适合重做，此时回忆的成本最低、效果最好。`,
  /** 一道都没到期时，上面那句话就是假的 —— 换成如实说明 */
  introNoDue: '现在没有到期该重做的题。复习间隔会逐次拉长，到期后这里会提醒你。',

  wrongTimes: (count: number) => `答错 ${count} 次`,
  /** 到期态与未到期态的右侧控件文案（原型一致） */
  actionRedo: '重做',
  actionPending: '待复习',

  start: '开始旧识重温关卡',
  starting: '正在挑出该复习的题…',
  /** 组卷失败：题库只在服务端，取不回来时给可操作的提示而不是静默无反应 */
  startFailed: '组卷没成功，稍后再试',
  /**
   * 服务端说「没有到期的错题」（错误码 4005）。
   *
   * 与 `introNoDue` 说的是同一件事、但出现在**点击之后**：列表是进页面那一刻的
   * 快照，用户可能在别处已经复习过一轮。所以这句要给出「不是出错，是没什么可做」，
   * 而不是和 `startFailed` 共用一句话 —— 后者会让用户反复重试一个永远不会成功的事。
   */
  startEmpty: '现在没有到期该重做的题，过几天再来吧',

  emptyTitle: '错题本还是空的',
  emptyBody: '答错的题会自动收进来，并在最合适的时机提醒你重做。',
  emptyCta: '去召唤一张卷轴'
} as const

/**
 * 勋章墙（原型 04·9）。
 *
 * 未解锁的勋章**必须带名称与条件**：原型的图注要求「保留轮廓与名称，
 * 让用户知道还有什么可追求」，全灰的圆点等于什么都没说。
 */
export const BADGES_COPY = {
  navTitle: '勋章墙',
  unlockedLabel: '已解锁',
  progress: (unlocked: number, total: number) => `${unlocked} / ${total} 枚`,
  unlockedAt: (date: string) => `${date} 解锁`,
  /** 未解锁时不显示解锁时间，改显示「还没有拿到」这类空位说明 */
  lockedAt: '还没有点亮',

  /** 默认只列已解锁的；有未解锁的才出现这个按钮（它执行「展开全部」） */
  viewAll: '查看全部成就',
  collapse: '只看已解锁',
  /** 全部解锁后按钮消失，这句替代它告诉用户已经集齐 */
  allUnlocked: '全部勋章都已点亮，了不起'
} as const

/**
 * 个人中心（原型 04·1）。
 *
 * 原型的导览栏右侧写「设置」，按方案 §7.6 的全局口径**一律去掉**
 * （同批去掉的还有「近 30 天」「6 / 18」「重做」「分享」「保存」）。
 * 所以这里没有 `settings` 这个键 —— 留着一个没有任何使用点的键，
 * 只会让人以为界面上某处应该有它。
 *
 * 「历史卷轴」这一行**保留在版面上但明确提示尚未开放** —— 原型是三行入口，
 * 抽掉一行会让这一屏看起来像没做完；而点了没反应比明说更糟。
 * 历史卷轴与卷轴详情（04·5 / 04·6）属 Phase E，见
 * `docs/用户系统方案设计文档.md §7.3`。
 */
export const PROFILE_COPY = {
  navTitle: '我的档案',

  /** 等级进度：原型「距离 Lv.4 还差 720 XP」 */
  levelRemaining: (level: number, xp: number) => `距离 Lv.${level} 还差 ${xp} XP`,
  /** 满级后不再说「还差」—— 曲线封顶，永远到不了 Lv.100 */
  levelMaxed: '已经到最高等级',
  /** 进度条右侧的两个数：原型「1280 / 2000」。分子是**累计** XP，分母是下一级门槛 */
  xpFraction: (xp: number, nextThreshold: number) => `${xp} / ${nextThreshold}`,

  statAttempts: '闯关副本',
  statXp: '累计 XP',
  statAccuracy: '平均正确率',

  iconTree: '树',
  iconScroll: '账',
  iconBadge: '印',

  rowKnowledgeTree: '知识树',
  rowKnowledgeTreeDesc: (count: number) => `已点亮 ${count} 个知识领域`,
  rowScrolls: '历史卷轴',
  rowScrollsDesc: (count: number) => `共 ${count} 份冒险日志`,
  rowBadges: '勋章墙',
  rowBadgesDesc: (unlocked: number, total: number) => `已解锁 ${unlocked} / ${total} 枚`,
  rowView: '查看'
} as const

/**
 * 档案五页（个人中心 + 看板 / 知识树 / 错题本 / 勋章墙）共用的加载与失败提示。
 *
 * 失败后果完全一致（页面显示不出数据、重试安全），所以文案共用一份；
 * 各自写一份迟早会出现几种略有出入的说法。
 *
 * ⚠️ `retry` 必须取自这里，**不要用 `COMMON_COPY.retry`** —— 后者是
 * 「重新生成」（报告 / 出题那类会产出内容的动作），用在只读页面上会变成
 * 一句说不通的话：档案页没有东西可以「重新生成」，它只能重新读取。
 */
export const ARCHIVE_COMMON = {
  loading: '正在翻开档案…',
  loadFailed: '档案暂时翻不开，请稍后再试',
  retry: '重新加载'
} as const
