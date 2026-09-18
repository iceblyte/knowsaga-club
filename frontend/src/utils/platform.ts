/**
 * 运行平台判定。
 *
 * 抽成独立模块是因为**它被两个不相干的地方需要**：内联样式（`utils/style.ts`
 * 要决定用 `rpx` 还是 `vw`）和登录通道（`services/auth.ts` 要决定走
 * `wx.login` 还是调试设备通道）。两份各写一遍必然会出现「一边修了、另一边没修」。
 */

import Taro from '@tarojs/taro'

/** 缓存：`Taro.getEnv()` 每个渲染周期都会被问，没必要重复算 */
let cachedIsH5: boolean | null = null

/**
 * 是否运行在 H5（浏览器）里。
 *
 * 取不到环境信息时**按小程序处理**：`rpx` 与 `wx.login` 都是小程序原生能力，
 * 猜错的代价比「把浏览器当小程序」小。
 */
export function isH5(): boolean {
  if (cachedIsH5 === null) {
    try {
      cachedIsH5 = Taro.getEnv() === Taro.ENV_TYPE.WEB
    } catch {
      cachedIsH5 = false
    }
  }
  return cachedIsH5
}
