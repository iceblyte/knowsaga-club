/**
 * 时间展示工具。
 *
 * ## 为什么不用 `toLocaleDateString('zh-CN', { timeZone })`
 *
 * 小程序的 JS 引擎（iOS 上是 JavaScriptCore，安卓上是 V8）对 `Intl` 的
 * 支持程度不一致，`timeZone` 选项在部分基础库版本上被忽略 —— 而「被忽略」
 * 的结果是**静默按设备时区渲染**，用户看到的日期就随手机设置变。
 * 报告页头部只有这一个日期，它错了没有任何告警。
 *
 * 业务时区是固定的 `Asia/Shanghai`（后端 `APP_TIMEZONE`，UTC+8，无夏令时），
 * 所以直接按 +8 小时偏移后读 UTC 字段，结果**在所有平台上完全一致**。
 *
 * ## 输入必须带时区偏移
 *
 * 后端出接口时会把库里的 naive UTC 标成 UTC 再序列化
 * （见 `backend/app/services/report_service.py` 的 `merge_draft`）。
 * 万一拿到的是不带偏移的串，`new Date()` 会按**本地时间**解析，
 * 这里会因此多算或少算 8 小时 —— 所以下面显式检查并给出兜底。
 */

/** 业务时区偏移（小时）。与后端 `APP_TIMEZONE=Asia/Shanghai` 一致 */
const BUSINESS_TZ_OFFSET_HOURS = 8

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'] as const

/** 把 ISO 串解析成时间戳；解析不出来返回 `NaN` */
function parse(iso: string): number {
  const raw = (iso || '').trim()
  if (!raw) return Number.NaN

  // 不带时区偏移（`2026-09-14T06:20:00` 或 `2026-09-14 06:20:00`）时，
  // 补上 `Z` 按 UTC 解释 —— 库里的时间一律是 UTC，不能交给浏览器按本地解释。
  const normalized = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw)
    ? raw
    : `${raw.replace(' ', 'T')}Z`

  const parsed = Date.parse(normalized)
  return Number.isNaN(parsed) ? Date.parse(raw) : parsed
}

/** 业务时区下的年月日 */
function businessParts(timestamp: number) {
  const shifted = new Date(timestamp + BUSINESS_TZ_OFFSET_HOURS * 3600 * 1000)
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    weekday: shifted.getUTCDay()
  }
}

const pad2 = (value: number) => String(value).padStart(2, '0')

/**
 * 「2026-09-14」。原型第 1 屏头部用的就是这种绝对日期。
 *
 * 解析失败时返回空串而不是 `Invalid Date` —— 让调用方自己决定隐藏这一段，
 * 而不是把 `Invalid Date` 渲染到界面上。
 */
export function formatDate(iso: string): string {
  const timestamp = parse(iso)
  if (Number.isNaN(timestamp)) return ''
  const { year, month, day } = businessParts(timestamp)
  return `${year}-${pad2(month)}-${pad2(day)}`
}

/** 「今天」/「昨天」/「9 月 14 日」/「2025 年 9 月 14 日」（列表场景用） */
export function formatDateRelative(iso: string, now: number = Date.now()): string {
  const timestamp = parse(iso)
  if (Number.isNaN(timestamp)) return ''

  const today = businessParts(now)
  const target = businessParts(timestamp)
  const dayGap = Math.round(
    (Date.UTC(target.year, target.month - 1, target.day) -
      Date.UTC(today.year, today.month - 1, today.day)) /
      86_400_000
  )

  if (dayGap === 0) return '今天'
  if (dayGap === -1) return '昨天'
  if (target.year === today.year) return `${target.month} 月 ${target.day} 日`
  return `${target.year} 年 ${target.month} 月 ${target.day} 日`
}

/** 「星期一」（列表场景用） */
export function formatWeekday(iso: string): string {
  const timestamp = parse(iso)
  if (Number.isNaN(timestamp)) return ''
  return `星期${WEEKDAYS[businessParts(timestamp).weekday]}`
}

/**
 * 毫秒 → 「3 分 12 秒」。
 *
 * 与原型头部的写法一致。不足一分钟时只给秒数（「42 秒」），
 * 不写成「0 分 42 秒」—— 后者读起来像机器日志。
 */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(Number(ms) || 0) / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = Math.floor(total % 60)
  if (minutes > 0) return `${minutes} 分 ${seconds} 秒`
  return `${seconds} 秒`
}

/** 平均用时：「8.4s」（原型第 1 屏的三分之一卡用的是这个写法） */
export function formatSeconds(seconds: number): string {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) return '0s'
  return `${value.toFixed(1)}s`
}
