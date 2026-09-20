/**
 * 复习提醒（原型 04·8 与大厅 / 个人中心的页内提示入口）。
 *
 * | 函数 | 接口 |
 * |---|---|
 * | `fetchRemindersToday` | `GET /users/me/reminders/today` |
 * | `snoozeReminders` | `POST /users/me/reminders/snooze` |
 *
 * ## 为什么单独一个模块，而不是塞进 `archive.ts`
 *
 * `archive.ts` 里的东西都是「翻开档案看一眼」—— 只读、幂等、随时重试都安全。
 * 这里两个接口不一样：`snoozeReminders` 会**写服务端状态**（今天的提醒被关掉），
 * 调用方必须考虑「点下去之后到底成没成」，以及「失败时要不要回滚界面上的样子」。
 * 两类调用的判断逻辑不同，混在一个文件里迟早会有人拿只读页的思路去调写接口。
 *
 * ## 为什么不做本地「今天已忽略」缓存
 *
 * 是否忽略由服务端 `snoozed_today` 判定，本地不另存一份。多存一份的后果是
 * 换设备（或重装）之后两边不一致 —— 而这种不一致表现出来是
 * 「今天在大厅已经点过不复习了，换了手机又冒出来」，很难被当成 bug 提上来。
 */

import type { RemindersTodayResponse, SnoozeResponse } from '../types/api'
import { request } from './request'

/**
 * 今日到期的复习提醒（也就是 04·8 那一屏的全部数据）。
 *
 * 页面本身只读；`snoozed_today` 只影响**入口按钮**的样子（见该字段说明），
 * 不影响三宫格的数字 —— 忽略只是「今天不提醒你」，不是「把题取消掉」。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function fetchRemindersToday(): Promise<RemindersTodayResponse> {
  return request<RemindersTodayResponse>({
    path: '/users/me/reminders/today'
  })
}

/**
 * 「今天先不复习」。
 *
 * 只写 `remind_snooze_date`，**不动任何错题的排期**（后端口径）——
 * 所以调用方刷新时用 `fetchRemindersToday()` 而不是重新拉错题本；
 * 三宫格的数字不会因此变化，变的是入口的显隐。
 *
 * 这个接口是**幂等**的：当天重复调用只是把日期写成同一个值，不会报错。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function snoozeReminders(): Promise<SnoozeResponse> {
  return request<SnoozeResponse>({
    path: '/users/me/reminders/snooze',
    method: 'POST'
  })
}
