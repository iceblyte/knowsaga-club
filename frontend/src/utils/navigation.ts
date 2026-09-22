/**
 * 页面跳转的统一入口。
 *
 * ## 为什么需要它
 *
 * 小程序的路由 API **失败时不抛异常**，只在回调 / Promise 里拒绝。也就是说
 * 直接写 `Taro.redirectTo({ url })` 时，「跳转失败」是一个**完全静默**的分支：
 * 用户点了按钮，界面什么也没发生，也没有任何提示，控制台更是干净的。
 *
 * 出题流程里「召唤完成 → 进副本」正好落在这种关键路径上 —— 一旦跳转失败，
 * 用户会一直停在进度 100% 的等待页，看起来就像「AI 生成完就没反应了」，
 * 而这是最难排查的一类问题。所以这里统一接住失败：先换另一种方式重试，
 * 再失败就明确告诉用户。
 *
 * ## 为什么失败后切换 redirect / navigate
 *
 * 两种方式对用户是不可见的差别，但对「能不能过去」影响很大：
 * `redirectTo` 关闭当前页，`navigateTo` 保留当前页。某一方式因页面栈或
 * 页面状态失败时，另一种往往能过。这是最便宜的一次重试。
 *
 * ## ⚠️ 下钻一律传 `'navigate'`（这曾经是一类 bug）
 *
 * `mode` 的默认值是 `'redirect'`，因为它对**流程推进**（召唤完成 → 确认页 →
 * 挑战 → 结算）是对的：那些中间页不该再退回去。但**下钻**（大厅/个人中心 →
 * 某个详情页）绝不能走默认值 —— `redirectTo` 会把当前页从页面栈里换掉，
 * 于是详情页的返回键 `navigateBack` 找不到上一页，`PhoneShell` 的兜底
 * 就把用户**直接送回了社团大厅**。用户的描述是「返回键坏了」，
 * 而真相是页面栈里本来就没有上一页。
 *
 * 判据很简单：**用户看完还要退回原处 → `'navigate'`；这一页的使命已经结束、
 * 不该再回来 → `'redirect'`**。
 */

import Taro from '@tarojs/taro'

/** 跳转方式：`redirect` 关闭当前页（流程推进），`navigate` 保留当前页（下钻） */
export type NavMode = 'redirect' | 'navigate'

/**
 * 跳转到应用内页面，失败时自动重试并提示。
 *
 * 标签页（tabBar 页面）不能用这两个 API，必须走 `goTab`。
 */
export function goPage(url: string, mode: NavMode = 'redirect'): void {
  const primary = mode === 'redirect' ? Taro.redirectTo : Taro.navigateTo
  const fallback = mode === 'redirect' ? Taro.navigateTo : Taro.redirectTo

  primary({ url }).catch(() => {
    fallback({ url }).catch(() => {
      Taro.showToast({ title: '页面打开失败，请重试', icon: 'none' })
    })
  })
}

/** 切到标签页。标签页只能用 `switchTab`，失败时退回首页。 */
export function goTab(url: string): void {
  Taro.switchTab({ url }).catch(() => {
    Taro.redirectTo({ url: '/pages/hall/index' }).catch(() => {
      Taro.showToast({ title: '页面打开失败，请重试', icon: 'none' })
    })
  })
}
