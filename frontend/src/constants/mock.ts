/**
 * 演示数据。
 *
 * ⚠️ 已人工确认：MVP **不做真实用户体系**，也不做后端持久化。
 * 因此原型里那些跨局的身份数据（等级、累计经验、连续打卡天数）在本文件写死。
 *
 * 哪些是真实计算的、哪些是写死的：
 *
 * | 数据 | 来源 |
 * |---|---|
 * | 本局 XP / 金币 / 正确率 / 用时 | **真实计算**（后端 scoring_service） |
 * | 百分位 | 由正确率确定性派生（见 docs/MVP开发计划.md §9.4），标注为演示值 |
 * | 等级 / 累计 XP / 连续天数 / 公会名 | **本文件写死**（原型快照） |
 *
 * 后续接真实用户体系时，只需把本文件的值替换为接口返回值。
 */

/** 当前冒险者（原型 01 大厅里的身份卡） */
export const MOCK_ADVENTURER = {
  /** 等级文案 */
  levelLabel: 'Lv.3 见习冒险者',
  /** 当前周期已获得经验 */
  xpCurrent: 1280,
  /** 当前周期升级所需经验 */
  xpTotal: 2000,
  /** 连续打卡天数 */
  streakDays: 4
} as const

/** 等级进度条百分比：1280 / 2000 = 64%，与原型一致 */
export const MOCK_LEVEL_PERCENT = Math.round(
  (MOCK_ADVENTURER.xpCurrent / MOCK_ADVENTURER.xpTotal) * 100
)

/** 大厅空态：推荐知识点 chip（点击填入输入框） */
export const MOCK_SUGGESTIONS = ['AI 入门', 'RAG 是什么', '近代史纲要'] as const

/**
 * 大厅已输入态：追加资料类 chip。
 * 这三项属于 P1「卷轴工坊」的多源输入能力，本期未实现，点击给出明确提示。
 */
export const MOCK_ATTACH_CHIPS = ['追加背景资料', '上传文档', '粘贴网址'] as const

/** 输入框容量上限，与后端 `text_cleaner.MAX_INPUT_LEN` 保持一致 */
export const INPUT_MAX_LEN = 200

/** 触发按钮激活的最少字数，与后端 `text_cleaner.MIN_INPUT_LEN` 保持一致 */
export const INPUT_MIN_LEN = 8
