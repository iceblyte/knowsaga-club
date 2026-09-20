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
  emptyBody: '完成一次副本挑战，这里就会出现你的正确率、答对题数与复习建议。'
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
 * ## 入口现在都通向真实的页面
 *
 * 历史卷轴（04·5 / 04·6）已随 Phase E 落地，那一行不再是「点击提示未开放」，
 * 而是与知识树、勋章墙一样直接跳转。设置页（07·5）也已落地 ——
 * 它的入口不在导览栏右侧（全站锁定右侧不放文字），而是与其余四行一起
 * 排在这一屏的入口列里，见 `rowSettings`。
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
  iconReview: '题',
  iconScroll: '账',
  iconBadge: '印',
  iconCard: '卡',

  rowKnowledgeTree: '知识树',
  rowKnowledgeTreeDesc: (count: number) => `已点亮 ${count} 个知识领域`,

  /**
   * 错题本（04·7 旧识重温）的入口行。
   *
   * 原型给 04·7 画的标签栏里高亮的是「我的」，说明它归属这一栏；
   * 但它和 04·8 复习提醒都不在 04·1 的入口行列表里 —— 于是这一屏
   * 在原型里其实**没有任何入口**，只在「今日有到期错题」时才从
   * 大厅 / 个人中心的页内提醒进得去。那意味着 `due_count` 为 0 的用户
   * 永远打不开它，而错题本恰恰是最该「随时想看就看」的一页：
   * 用户要确认自己的错题有没有排上、下次什么时候复习。
   *
   * 所以按 04·2 / 07·5 同样的做法，在这一列补一个看得见的入口。
   *
   * ⚠️ 这一行的副标题是**固定的**，不像上面三行那样带计数 ——
   * `GET /users/me` 的 `stats` 里没有错题数，而为了一个副标题
   * 去扩这个接口的契约（并且要重跑一遍后端闸门）不划算。
   * 字面上也不撒谎：它说的是机制，不是数量。理由同 `rowCard`。
   */
  rowReview: '错题本',
  rowReviewDesc: '答错的题会按遗忘曲线回来找你',

  rowScrolls: '历史卷轴',
  rowScrollsDesc: (count: number) => `共 ${count} 份冒险日志`,
  rowBadges: '勋章墙',
  rowBadgesDesc: (unlocked: number, total: number) => `已解锁 ${unlocked} / ${total} 枚`,
  rowView: '查看',

  /**
   * 公会卡（04·2）的入口行。
   *
   * 原型 04·1 只有三个入口行，第四个是 Phase E 新增的 —— 04·2 需要一个入口，
   * 而它既不该挤进导览栏（全站锁定右侧不放文字），也不该做成
   * 「点了没提示的可点卡片」（原型的身份卡没有任何可点的暗示，
   * 把整张卡做成隐式按钮是另一种形式的不可发现）。
   */
  rowCard: '公会卡',
  rowCardDesc: '把这段成长存成一张图',

  /**
   * 设置（07·5）的入口行。
   *
   * 原型把「设置」放在导览栏右侧，而全站锁定「导览栏右侧不放文字」
   * （方案 §7.6 明确把「设置」列在要去掉的名单里）—— 于是它在原型里
   * 唯一的位置没有了。设置页是 Phase E 的页面，需要一个**看得见**的入口，
   * 所以按其它四个入口行的做法加在这里。
   */
  iconSettings: '设',
  rowSettings: '设置',
  rowSettingsDesc: '提醒、缓存与账号'
} as const

/**
 * 页内复习提醒（方案 §8.5）。
 *
 * 本轮无订阅消息模板 ID，复习提醒降级为**页内提示**：进小程序时若今日有
 * 到期错题，在社团大厅与个人中心给一个入口。这个组件在三处共用，
 * 所以文案只写一份 —— 两处各写一份必然会出现两种说法。
 *
 * ## 说「约 2 分钟」而不是「2 分钟」
 *
 * 后端给的是**下限估算**（判断题按最低满分 20 计）。写成确定的「2 分钟」
 * 就成了承诺，而实际用时通常更长；一个「约」字把口径说清楚。
 */
export const REMINDER_PROMPT_COPY = {
  /** 原型 04·8 的标题缩短到一行，因为它要和一个按钮并排 */
  title: (dueCount: number) => `今天有 ${dueCount} 道旧识在等你`,
  /** 副行：把「重新开始的成本」说到最低（原型 04·8 的图注要求） */
  sub: (minutes: number) => `约 ${Math.max(1, minutes)} 分钟就能复习完`,
  action: '去复习'
} as const

/**
 * 档案各页（个人中心 + 看板 / 知识树 / 历史卷轴 / 卷轴详情 / 错题本 / 勋章墙）
 * 共用的加载与失败提示。
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

/**
 * 历史卷轴（原型 04·5）。
 *
 * ## 一行里的时间说法来自后端
 *
 * `rowMeta` 只负责把后端给的 `finished_label`（「今天 14:20」）与正确率拼起来。
 * **不要在这里用 `formatDateRelative` 重算** —— 那个函数算的是「今天/昨天」，
 * 而后端的版本还带时刻，且两边都以业务时区为准；各算各的迟早会出现
 * 「列表写今天、详情写昨天」。
 *
 * ## 删除只说「不影响成绩」
 *
 * 原型图注要求「删除仅移除记录不影响统计」，而用户对「删除」最大的顾虑
 * 恰恰是「我的记录/成绩会不会一起没了」。所以确认弹窗必须把这句话说出来，
 * 而不是只问一句「确定删除吗」。
 */
export const SCROLLS_COPY = {
  navTitle: '历史卷轴',
  /** 筛选项的第一个，恒有且代表「不筛」 */
  filterAll: '全部',
  /** 行首方块里的字（原型是「卷」） */
  icon: '卷',
  /** 一行右侧的胶囊：原型「5 题」 */
  questionPill: (count: number) => `${count} 题`,
  /** 一行副标题：原型「今天 14:20 · 正确率 80%」 */
  rowMeta: (label: string, accuracy: number) => `${label} · 正确率 ${accuracy}%`,

  /**
   * 页脚：原型「已经到底了 · 共 12 份卷轴」。
   *
   * ⚠️ **只在真的取完时才显示**。服务端分页 20 条一页，还有下一页时说
   * 「已经到底了」就是在骗用户 —— 他以为只有 20 份，实际有 200 份。
   * 还有下一页时这个位置换成 `loadMore` 按钮。
   */
  footer: (total: number) => `已经到底了 · 共 ${total} 份卷轴`,

  // ---- 翻页（原型只画了一屏，没有翻页控件） ----
  /** 还有下一页时的入口 */
  loadMore: '查看更多卷轴',
  loadingMore: '正在取出更多…',

  // ---- 长按删除（原型的注解：长按可删除） ----
  deleteTitle: '删除这条记录？',
  deleteBody: '它会从历史卷轴里消失，但累计 XP、正确率与等级都不受影响。',
  /** 微信弹窗的按钮文案上限是 4 个字 */
  deleteConfirm: '删除',
  deleteCancel: '再想想',
  deleted: '已删除',
  deleteFailed: '删除没成功，稍后再试',

  // ---- 空态 ----
  /** 筛出来一条都没有：**不是**没有记录，所以不能说「完成一次挑战就有了」 */
  filterEmptyTitle: '这个领域还没有记录',
  filterEmptyBody: '换一个领域，或点上面的「全部」看所有卷轴。',
  emptyTitle: '还没有历史卷轴',
  emptyBody: '完成一次副本挑战，这里会留下你的冒险日志。',
  emptyCta: '去召唤一张卷轴'
} as const

/**
 * 卷轴详情（原型 04·6）。
 *
 * ## 逐题回看的是**当时**的答案
 *
 * `answerExact` / `answerDiff` 里的「我的答案」读的是服务端存下来的
 * 那一局的作答，不是当前状态 —— 所以用户重做几轮之后回看，看到的仍是
 * 当时选了什么。这正是历史记录的意义，不要「顺手」改成最新一局。
 */
export const SCROLL_DETAIL_COPY = {
  navTitle: '卷轴详情',
  /** 头部副标题：原型「今天 14:20 · 用时 3 分 12 秒」 */
  meta: (label: string, duration: string) => `${label} · 用时 ${duration}`,

  /** 题头：原型「第 1 题 · 单选」 */
  questionLabel: (seq: number, typeLabel: string) => `第 ${seq} 题 · ${typeLabel}`,

  outcomeCorrect: '答对',
  outcomePartial: '部分正确',
  outcomeWrong: '答错',

  /** 全对：原型「我的答案：C · 正确」 */
  answerExact: (mine: string) => `我的答案：${mine} · 正确`,
  /** 有出入：原型「我的答案：A、C · 正确答案 A、C、D」 */
  answerDiff: (mine: string, answer: string) => `我的答案：${mine} · 正确答案 ${answer}`,
  /** 多选题一个都没选就交卷 —— 「我的答案：」后面没有内容可写 */
  answerBlank: (answer: string) => `当时没有作答 · 正确答案 ${answer}`,

  /**
   * 讲解的展开（原型图注：「可展开任意一题重看讲解」）。
   *
   * 默认**收起**：这一屏的定位是「快速回看每一题当时答了什么」，
   * 5 道题的讲解全铺开会把作答记录挤散；要复盘时再逐题展开。
   * 与答题页相反 —— 那边刚作答完，讲解是必须立刻看到的反馈。
   */
  explainHint: '点击查看本题知识讲解',
  collapse: '收起讲解',

  /**
   * 这一局已经不在了（已被删除），或路由参数缺失。
   *
   * 与「加载失败」必须分开：重新加载一百次也不会变出来，
   * 所以要给的是出口（回列表），而不是「重试」。
   */
  goneTitle: '这份记录已经不在了',
  goneBody: '它可能已经被删除。累计 XP、正确率与等级都不受影响。',
  goneCta: '回到历史卷轴',

  retry: '重新挑战这一卷',
  retryStarting: '正在取回题目…',
  /** 重做要把题库快照取回来，取不到时给可操作的提示而不是静默无反应 */
  retryFailed: '没取回这套题，稍后再试'
} as const

/**
 * 冒险者头像键 → 「职业倾向」的名字（原型 04·2 底部左侧那句）。
 *
 * ## 为什么是一张显式表，而且在这里
 *
 * 原型的六个头像是**六种用户画像**（00-设计规范「冒险者头像」一节），
 * 而 04·2 的公会卡要把画像写成一句话。原型只钉死了其中一种
 * （学者 →「检索者」），另外五种按同一节的画像描述推导 —— 之所以推导而不是
 * 留五种空着，是因为「职业倾向 · 」后面跟着空白比跟着一个不够准的词更糟。
 *
 * 这条映射**同时是兜底链的一环**：认不出的头像键 → 学者 → 检索者，
 * 与 `Avatar` 组件的兜底（`FALLBACK_AVATAR = 'scholar'`）保持一致 ——
 * 两处若各兜各的，会出现「头像画的是学者、倾向写的是工匠」。
 *
 * ⚠️ 评审时如果确定了更好的五个名字，**只改这里**：公会卡、以及将来
 * 任何要展示职业倾向的地方都读它。
 */
export const CAREER_TENDENCY: Record<string, string> = {
  apprentice: '起步者', // 00-设计规范 · 新注册用户 Lv.1–2
  ranger: '探索者', // 00-设计规范 · 探索型学习者
  mage: '深耕者', // 00-设计规范 · 重度用户 Lv.4 以上
  knight: '挑战者', // 00-设计规范 · PK 与对战场景
  scholar: '检索者', // 00-设计规范 · 默认身份「检索者」（原型 04·2 原文）
  artisan: '建构者' // 00-设计规范 · 知识库创建者
}

/** 认不出的头像键退到这一位；与 `Avatar` 的 `FALLBACK_AVATAR` 同源 */
export const CAREER_FALLBACK_KEY = 'scholar'

/**
 * 冒险者卡片 · 公会卡（原型 04·2）。
 *
 * ## 卡面上的每个数字都来自 04·1 的同一个接口
 *
 * `GET /users/me` 已经把等级、三宫格、连续天数全部给了 04·1。公会卡不再
 * 单独请求一次同样的数据 —— 两张卡面必须逐字对上（用户会把它们并排截图），
 * 而从两个请求取数就意味着存在「列表页显示 12、卡片显示 11」的窗口期。
 *
 * ## 「加入第 N 天」为什么在前端算
 *
 * 它是 `created_at` 与**今天**的差，随日期自然变化。服务端不为此多开一个
 * 字段：那会让缓存与「今天」的定义绑在一起。算法见 `daysSinceJoin()`，
 * 按业务时区的自然日算，与「N 天前」口径一致。
 */
export const PROFILE_CARD_COPY = {
  navTitle: '冒险者卡片',
  /** 卡面顶部的归属行（原型原文） */
  cardLabel: '知拾冒险社 · 冒险者公会卡',

  /** 三宫格：原型是「副本 / 正确率 / 连续天数」（04·1 的三格是另一组词） */
  statAttempts: '副本',
  statAccuracy: '正确率',
  statStreak: '连续天数',

  /** 底部左侧（原型「职业倾向 · 检索者」） */
  career: (tendency: string) => `职业倾向 · ${tendency}`,
  /** 底部右侧（原型「加入第 38 天」）。注册当天即第 1 天 */
  joinDay: (days: number) => `加入第 ${days} 天`,

  save: '保存公会卡',
  saving: '正在绘制…',
  /** 卡片保存到相册是一串异步动作，成功必须说一声，否则用户不知道去哪找 */
  saveOk: '公会卡已存到相册',
  saveDenied: '需要相册权限才能保存，请在设置里打开',
  saveFailed: '保存没成功，稍后再试',

  share: '分享给好友',
  /** `useShareAppMessage` 的标题（用户直接从右上角转发时也用它） */
  shareTitle: '来看看我的冒险者公会卡',
  /** 转发入口只在微信右上角，页面里点不出来 —— 按钮负责指路，不假装自己会转发 */
  shareGuide: '点右上角「…」转发给好友',
  /** H5 没有原生转发能力：明说，而不是给一个点了没反应的按钮 */
  shareH5Hint: '在微信里打开就能转发给好友',

  /**
   * 卡面取不到数据时的出口。
   *
   * 与 04·1 一样是只读页，所以「重试」是安全且唯一有意义的动作 ——
   * 不要退回个人中心（那等于让用户自己找回这一屏）。
   */
  loadFailed: '公会卡暂时取不出来'
} as const

/**
 * 复习提醒（原型 04·8），也是大厅 / 个人中心「今日有到期错题」页内提示的文案源。
 *
 * ## 「为什么是今天」这一句是**拼**出来的
 *
 * 服务端只给两个事实（`days_ago` 与 `topic`），三种措辞在这里。
 * 之所以不把整句交给服务端：改一个词就要发一次后端版本，
 * 而这句文案还在大厅和个人中心的提示里复用。
 *
 * `days_ago` 已按业务时区的自然日算好，**不要**在这里拿时间戳相减 ——
 * 客户端时区不同的人会各算各的（见 `ReminderHint` 的说明）。
 *
 * ## 没有 `hint` 时说什么
 *
 * `hint` 为 `null` 有两种情况：没有到期错题（这一屏根本不出现），
 * 或到期了但取不到「等得最久的那一道」的题目信息。后者不能留一句
 * 「你在「」上失手」，所以退到 `hintFallback` 说机制、不说具体的人称。
 */

/** 中文数字，索引即数值；`一` 用不到（1 天走「昨天」那条分支），留着是为了下标可读 */
const CN_DIGITS = ['', '一', '两', '三', '四', '五', '六', '七', '八', '九', '十']

/**
 * 「N 天前」里的那截前缀（含「天」字）。
 *
 * 原型写的是「**三**天前」：小数值用中文数字更顺口，也不会让阿拉伯数字
 * 孤零零地卡在汉字中间。10 天以上退回阿拉伯数字 —— 「十二天前」开始
 * 就有读数成本了；此时补一个空格，否则 `12天前` 会挤成一团。
 */
function daysAgoPrefix(days: number): string {
  if (days >= 2 && days <= CN_DIGITS.length - 1) return `${CN_DIGITS[days]}天`
  return `${days} 天`
}

export const REMINDER_COPY = {
  navTitle: '复习提醒',

  /** 主标题：原型「你有 3 道旧识在等你」 */
  title: (dueCount: number) => `你有 ${dueCount} 道旧识在等你`,
  /** 今天刚错过的（`days_ago` 为 0）—— 说「今天」而不是「0 天前」 */
  hintToday: (topic: string) => `今天你在「${topic}」上失手，趁热重做记得最牢。`,
  hintYesterday: (topic: string) => `昨天你在「${topic}」上失手，现在重做记得最牢。`,
  hintDaysAgo: (days: number, topic: string) =>
    `${daysAgoPrefix(days)}前你在「${topic}」上失手，现在重做记得最牢。`,
  /** 拿不到知识点时的兜底：说机制，不说具体哪一道 */
  hintFallback: '按艾宾浩斯遗忘曲线，这些题今天最适合重做，此时回忆的成本最低、效果最好。',

  /** 三宫格：原型「2m 预计用时 / 3 待复习题 / +60 可得 XP」 */
  statMinutes: '预计用时',
  statDue: '待复习题',
  statXp: '可得 XP',
  /** 分钟写法沿用原型：`2m` 而不是「2 分钟」—— 三格等宽，长词会把格子撑歪 */
  minutes: (value: number) => `${Math.max(1, value)}m`,
  xp: (value: number) => `+${value}`,

  start: '开始重温',
  starting: '正在取回旧识…',
  /** 与 04·7 同一件事，所以共用同一句话的两个分支 */
  startEmpty: '现在没有到期的旧识',
  startFailed: '没能取回旧识，稍后再试',

  snooze: '今天先不复习',
  snoozing: '正在记下…',
  /** 忽略成功之后这句要说清「忽略的是什么」—— 题还在，只是今天不催 */
  snoozed: '好，今天不再提醒',
  snoozeFailed: '没记下来，稍后再试',
  /** 已经忽略过时按钮的样子：不是错误，是「今天已经跳过」 */
  snoozedNote: '今天已跳过提醒',

  /** `due_count` 为 0：不是错误，是「今天真的没有」 */
  emptyTitle: '今天没有到期的旧识',
  emptyBody: '错题会按遗忘曲线排队，到时间了会自动出现在这里。',
  emptyCta: '去召唤一张卷轴'
} as const

/**
 * 把服务端给的两个事实拼成「为什么是今天」那句话。
 *
 * 参数类型内联写死而**不 import `ReminderHint`**：`copy.ts` 是全站的叶子模块
 * （没有任何 import），保持这一点意味着任何地方引用文案都不会被拖进
 * 类型模块的依赖链。这里的形状与 `ReminderHint` 一致，
 * 字段名对不上时 `tsc` 会在调用处直接报错。
 *
 * `days_ago` 的 0 / 1 有专门的说法：「0 天前」「1 天前」不是中文。
 */
export function reminderHint(hint: { days_ago: number; topic: string } | null): string {
  if (!hint) return REMINDER_COPY.hintFallback
  const { days_ago: days, topic } = hint
  if (days <= 0) return REMINDER_COPY.hintToday(topic)
  if (days === 1) return REMINDER_COPY.hintYesterday(topic)
  return REMINDER_COPY.hintDaysAgo(days, topic)
}

/**
 * 应用级的固定信息（07·5 的「关于」、07·8 的页脚、反馈模板共用）。
 *
 * `version` 取自构建期注入的 `APP_VERSION`（`config/index.ts` 里由
 * `package.json` 的 `version` 生成）。需求 FR-D4 写的是「版本号取自**真实**版本」
 * —— 原型里的「1.0.0」是设计稿上的占位数字，硬写进源码就一定会和真实版本漂开。
 */
export const APP_COPY = {
  name: '知拾冒险社',
  version: APP_VERSION,
  slogan: '拾万千知识，闯无尽关卡',
  /** 页脚：「知拾冒险社 v0.1.0 · 拾万千知识，闯无尽关卡」 */
  footer: () => `${APP_COPY.name} v${APP_VERSION} · ${APP_COPY.slogan}`
} as const

/**
 * 六个预置头像（方案 §7.4）。
 *
 * 顺序即选择器里的排列顺序，默认「学者」在第二位 —— 与后端
 * `utils.crypto.AVATAR_KEYS` 是同一组键（那里是白名单，这里是展示顺序）。
 * 用**数组**而不是 `Record`：`Object.keys` 的顺序在两端和不同引擎里
 * 不保证稳定，而这一排小图必须每次都长得一样。
 */
export const AVATAR_PRESETS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'apprentice', label: '学徒' },
  { key: 'scholar', label: '学者' },
  { key: 'knight', label: '骑士' },
  { key: 'mage', label: '法师' },
  { key: 'ranger', label: '游侠' },
  { key: 'artisan', label: '工匠' }
]

/**
 * 设置（原型 07·5）。**9 行** —— 原型 8 行，最上面一行「头像与昵称」
 * 是方案 §7.4 要求新增的（原型没有这一屏），其余 8 行与原型逐字对应。
 *
 * ## 「当前占用」显示的是**真实**占用
 *
 * 原型写「12.6 MB」，那是设计稿的占位数字。需求 FR-D4 明确要求
 * 「『清理缓存』显示真实占用并可清理」，所以这里的数据来自
 * `utils/cache.ts`（按字节真算，见那里的说明）。
 *
 * ## 开关状态「不只依赖颜色」
 *
 * 原型图注：「所有开关状态用颜色加位置双重表达，不只依赖颜色」。
 * 所以每行右侧既有 `pill ok`（绿）／`pill`（灰）的**颜色**，
 * 也有「已开 / 已关」的**文字**。
 */
export const SETTINGS_COPY = {
  navTitle: '设置',
  /** 跳转类行的右侧胶囊（与 04·1 的入口行同一个词） */
  rowView: '查看',

  // ---- 行 1：头像与昵称（方案 §7.4 新增）----
  iconProfile: '像',
  rowProfile: '头像与昵称',
  rowProfileDesc: '换一个头像或昵称',

  // ---- 原型 8 行 ----
  iconReminder: '铃',
  rowReminder: '学习提醒',
  rowReminderOn: (time: string) => `每天 ${time} 提醒我复习`,
  /** 关掉之后不能再说「每天 20:00 提醒我」—— 那是在陈述一件不会发生的事 */
  rowReminderOff: '提醒已关闭',

  iconSound: '音',
  rowSound: '音效与振动',
  rowSoundDesc: '答对答错的即时反馈',

  iconTraffic: '存',
  rowTraffic: '流量下自动加载配图',
  rowTrafficDesc: '关闭可节省流量',

  iconEye: '护',
  rowEye: '护眼模式',
  rowEyeDesc: '降低羊皮纸底亮度',

  iconCache: '清',
  rowCache: '清理缓存',
  cacheUsage: (size: string) => `当前占用 ${size}`,
  cacheAction: '清理',
  /** 说清删了几项。「清理完成」在删了 0 项时也是这句，用户会以为漏了什么 */
  cacheCleared: (count: number) => (count > 0 ? `已清理 ${count} 项` : '没有需要清理的内容'),
  cacheClearFailed: '没清理成功，稍后再试',

  iconAccount: '账',
  rowAccount: '账号与安全',
  /** 绑定状态由本端走的登录通道决定（`services/auth`）；服务端不暴露 openid */
  accountBound: '微信已绑定',
  accountUnbound: '微信未绑定',

  iconHelp: '问',
  rowHelp: '帮助与反馈',
  rowHelpDesc: '常见问题与意见反馈',

  iconAbout: '版',
  rowAbout: '关于知拾冒险社',
  appVersion: (version: string) => `版本 ${version}`,

  // ---- 开关与弹层 ----
  switchOn: '已开',
  switchOff: '已关',
  /** 开关是「先改本地、再提交」：失败要把它翻回去，并说清没保存 */
  switchFailed: '没保存成功，请重试',

  accountTitle: '账号与安全',
  accountNicknameLabel: '昵称',
  accountIdLabel: '账号编号',
  accountBindingLabel: '微信绑定',
  /** 弹层里两个按钮，第二个不要出现 —— 这里只有「知道了」 */
  dismiss: '知道了',

  loadFailed: '设置暂时取不出来'
} as const

/**
 * 学习提醒设置（原型 07·6）。
 *
 * ## 时间与星期为什么是**固定 chips** 而不是时间选择器
 *
 * 原型给的就是 4 个固定时段 + 7 个星期 chip（原型图注：「提醒时间默认 20:00，
 * 覆盖下班后的学习高峰」）。四个时段是产品选的「学习高峰」，
 * 让用户自己挑一个任意时刻并不会比这四选一更好用，还要多一层原生选择器。
 * 后端的 `reminder_time` 是自由 `HH:MM`，将来放开不受这一层限制。
 */
export const SETTINGS_REMINDER_COPY = {
  navTitle: '学习提醒',

  sectionTitle: '每日学习提醒',
  /** 原型图注：「默认开启但必须可关闭」 */
  enabled: '已开启',
  disabled: '已关闭',
  /** 原型原文 */
  intro: '每天在你设定的时间提醒你来社团大厅，避免连续记录中断。',

  timeLabel: '提醒时间',
  /** 原型给的 4 个时段 */
  timeOptions: ['08:00', '12:30', '20:00', '22:00'] as ReadonlyArray<string>,

  daysLabel: '提醒日',
  /** 顺序即 1–7（周一 → 周日），与后端 `reminder_days` 的取值一致 */
  dayLabels: ['一', '二', '三', '四', '五', '六', '日'] as ReadonlyArray<string>,
  /** 后端不接受空集合，所以不给用户走到那一步的机会（见页面说明） */
  daysMinOne: '至少保留一天',

  extraLabel: '额外提醒',
  extraStreak: '连续记录即将中断时提醒',
  extraReview: '旧识重温到期时提醒',
  /** 原型这一屏的两个开关写的是「开 / 关」（与 07·5 的「已开 / 已关」不同） */
  extraOn: '开',
  extraOff: '关',

  save: '保存设置',
  saving: '正在保存…',
  saved: '设置已保存',
  saveFailed: '没保存成功，稍后再试',
  /**
   * 一个字段都没改就点「保存设置」。
   *
   * 与 07·5 的开关不同，这一屏有一颗显式的保存按钮 —— 用户点了它就该得到一个回应。
   * 什么反应都没有，或者更糟：报一句「设置已保存」，等于告诉他刚刚发生了一次
   * 实际不存在的写入。与 07·4 的 `unchanged` 是同一件事，两页各写一份。
   */
  unchanged: '还没有改动',
  loadFailed: '提醒设置暂时取不出来'
} as const

/**
 * 帮助与反馈（原型 07·8）。
 *
 * ## FAQ 的答案为什么换掉了两条
 *
 * 原型是设计稿：第 2 条写「每天 3 次，会员不限次数」，而**这个项目里既没有
 * 每日次数限制，也没有会员体系**（会员那四屏在需求文档里被标为不做）。
 * 于是点开「查看」等于读了一条与事实相反的产品承诺 —— 这比少一条 FAQ 糟得多。
 * 需求 FR-D6 只要求「3 条 FAQ」，没有规定写哪三条，所以这里把问题留着、
 * 答案换成真的：目前不限次数。第 1、3 条与原型一致。
 *
 * ## 「查看」展开的是**详细说明**，不是把短答案再写一遍
 *
 * 行里的 `d` 是一句话结论，展开给的是「所以我该怎么做」。
 * 两者写成一模一样的话，那个「查看」就没有存在的意义。
 */
export const SETTINGS_HELP_COPY = {
  navTitle: '帮助与反馈',

  faqTitle: '常见问题',
  faqAction: '查看',
  /** 展开之后同一颗胶囊的文字 —— 已经展开了还写「查看」，就成了一个骗人的按钮 */
  faqActionOpen: '收起',
  faq: [
    {
      icon: '问',
      question: '为什么生成的题目不太准？',
      short: '补充背景资料可以显著提升质量',
      detail:
        '出题只依据你贴进来的那段资料。资料写得粗（只有标题、没有解释），题目就只能停在字面。把原文的完整段落一起贴进来，或者一次只喂一个主题，命中率会明显提高。'
    },
    {
      icon: '问',
      question: '免费版每天能生成几次？',
      short: '目前没有次数限制',
      detail:
        '随时可以召唤新卷轴。已经做过的卷轴还能重做 —— 重做用的是当时存下来的题目，不需要重新出题，也不消耗任何东西。'
    },
    {
      icon: '问',
      question: '上传的文档安全吗？',
      short: '按用户隔离，不会用于训练',
      detail:
        '卷轴按账号隔离，别的用户看不到你的资料。资料只用来给你出题，我们不会把它用于训练。'
    }
  ],

  reportTitle: '举报题目问题',
  reportDesc: '题干有误、答案错误或内容不适',
  /** 模板里留了空行给用户填 —— 只给一串固定文字，等于让他自己组织一遍 */
  reportTemplate: (account: string) =>
    `【题目问题反馈】\n卷轴：\n题号：\n问题：\n账号：${account}`,
  reportCopied: '反馈模板已复制，粘贴给开发者即可',
  reportFailed: '没复制成功，请手动截图反馈',

  contactTitle: '联系开发者',
  contactDesc: '复制账号信息，方便定位问题',
  contactAction: '发信',
  contactTemplate: (nickname: string, id: number, version: string) =>
    `【知拾冒险社】\n昵称：${nickname}\n账号编号：${id}\n版本：v${version}`,
  contactCopied: '账号信息已复制',

  copyFailed: '没复制成功，请手动记录'
} as const

/**
 * 头像与昵称（原型外，方案 §7.4）。
 *
 * ## 昵称为什么不在前端校验长度
 *
 * 后端 `normalize_nickname` 判定合规并抛 4001（方案 §4.6）。前端再写一套
 * 长度 / 字符规则，总有一天会与后端不一致 —— 那时用户看到的是
 * 「明明填得下却存不进去」。所以这里只做一件事：空的（或没变的）不发请求。
 */
export const SETTINGS_PROFILE_COPY = {
  navTitle: '头像与昵称',

  avatarLabel: '头像',
  /** 自选图片只能上传，不能贴链接（后端不接受客户端给的地址） */
  avatarHint: '可以使用微信头像，或从相册选一张',
  /** 两端能做的事不一样，所以按钮文字也不一样（见 `components/AvatarPicker`） */
  avatarPickWeapp: '使用微信头像',
  avatarPickH5: '从相册选一张',
  avatarUploading: '正在上传…',
  avatarFailed: '头像没换上，稍后再试',
  avatarTooLarge: '图片太大了，请选 2 MB 以内的',
  avatarPickFailed: '没能打开相册，请检查权限',

  presetLabel: '预置头像',

  nicknameLabel: '昵称',
  nicknamePlaceholder: '给自己起个名字',
  /** `<input type="nickname">` 的微信填写提示位；不填就用默认名 */
  nicknameHint: '点一下可以使用微信昵称',

  save: '保存',
  saving: '正在保存…',
  saved: '已保存',
  saveFailed: '没保存成功，稍后再试',
  /** 一个字符都没改就点保存：说清楚，而不是静默什么都不做 */
  unchanged: '还没有改动',
  /**
   * 清空昵称之后点保存。
   *
   * 这一条**不是**把后端的校验规则搬一份到前端：它只拦「一个字符都没有」
   * 这种连请求都不必发的输入（后端 `normalize_nickname` 判 4001）。
   * 长度与字符集仍然只由后端定，前端不表态 —— 两套规则迟早会不一致。
   */
  nicknameRequired: '昵称不能为空',
  loadFailed: '资料暂时取不出来',

  /**
   * 隐私协议（方案 §7.4 的时序要求）。
   *
   * 未同意时微信会把 `<input type="nickname">` **降级成普通输入框**，
   * 界面上看不出任何区别 —— 所以要先让用户读一眼、点一次同意。
   */
  privacyTitle: '需要先同意隐私保护指引',
  privacyBody:
    '「头像与昵称」用到了微信的头像昵称能力。同意之后才能填微信昵称，或直接使用微信头像。',
  privacyRead: '查看指引',
  privacyAgree: '同意并使用',
  privacyLater: '暂不使用'
} as const

/**
 * 社团大厅的冒险者档案（原型 01 第 2 / 3 屏底部那张卡）。
 *
 * ## 它原来是写死的演示数据
 *
 * 原型是 `Lv.3 见习冒险者` / `1280 / 2000 XP` / `连续 4 天` / 进度 64%，
 * MVP 期照抄进 `constants/mock.ts`（当时的定位见 `docs/MVP开发计划.md` §9.5）。
 * 现在换成 `GET /users/me` 的真实值 —— 演示数据留在屏幕上的后果是
 * 「一个 0 XP 的新用户打开大厅，看见自己已经练了 1280 点经验」。
 *
 * ## 数字一律由服务端算
 *
 * 等级、头衔、下一级门槛、进度百分比**全部取自接口**（服务端见
 * `backend/app/services/level_service.py`）。前端不按 `xp_total` 再推一遍：
 * 那样某天后端调了曲线，就会出现「大厅写 Lv.3、个人中心写 Lv.4」。
 * 尤其是进度条分母这个口径 —— 它是**累计 XP / 下一级门槛**，
 * 不是「本级区间内的完成度」，自己算必然算错（`level_service` 开头有完整推导）。
 *
 * ## 读不到时宁可空态，不显示数字
 *
 * 需求 FR-D1 定的是「接口异常时不显示错误数字」。所以请求还没回来、
 * 或者失败了，这张卡只出现占位符与一句说明 —— 它**不回落到**任何默认值。
 * `0 / 400 XP` 这种「看起来像真的」的数字比一个破折号糟得多：
 * 新用户分不清那是自己确实没经验，还是这一屏根本没读到。
 *
 * ## 为什么单独一个常量，而不是并进 `PROFILE_COPY`
 *
 * 这一屏是原型 01（核心闭环的入口），`PROFILE_COPY` 是原型 04·1（个人中心）。
 * 两处都显示等级与 XP，但**版式不同**（这里一行写「Lv.3 见习冒险者」、
 * 那里是两颗胶囊；这里的分数带 `XP` 后缀、那里不带）。
 * 合在一起就要为「谁在调」加分支，不如各写一份。
 *
 * 大厅其余文案（欢迎语、输入占位、推荐 chip）在本文件出现之前就写在页面里了，
 * 这里只放这次新接的真实数据需要的格式化 —— 不顺手把旧文案搬过来，
 * 那会让「换成真实数据」的 diff 里混进一堆无关的行。
 */
export const HALL_PROFILE_COPY = {
  /** 等级与累计 XP 读不到时的占位（加载中 / 读失败都用它） */
  unknown: '—',
  /** 等级与头衔。原型「Lv.3 见习冒险者」 */
  level: (level: number, title: string) => `Lv.${level} ${title}`,
  /** 进度条上方那行。原型「1280 / 2000 XP」—— 分子是累计 XP，分母是下一级门槛 */
  xpFraction: (xp: number, nextThreshold: number) => `${xp} / ${nextThreshold} XP`,
  /** 满级后分母取自身（`level_service` 的封顶处理），再写成分数就成了「8000 / 8000」这种废话 */
  xpTotal: (xp: number) => `${xp} XP`,
  /** 连续打卡。原型「连续 4 天」 */
  streak: (days: number) => `连续 ${days} 天`
} as const

