/**
 * 内联样式工具。
 *
 * 这里踩过两个坑，都是**静默失效**：浏览器不报错，元素只是退回默认尺寸。
 *
 * ## 坑一：`style` 必须写成字符串
 *
 * Taro 的 H5 组件（`View` / `ScrollView` / …）是 Stencil 自定义元素。
 * React 把 `style` **对象**挂在自定义元素上时，属性不会落到元素的 `style` 属性上 ——
 * 实测 `getAttribute('style')` 为 `null`，`getComputedStyle` 也拿不到值。
 * 结果就是所有内联尺寸（进度条宽度、精灵大小、内容区高度）在 H5 上**静默失效**。
 *
 * 写成字符串时 React 会把它当普通属性写入，自定义元素即可正常解析。
 * 小程序端（WXML 的 `style` 属性）两种写法都支持，所以全站统一用字符串最省心。
 *
 * ## 坑二：长度单位不能写死 `rpx`
 *
 * **`rpx` 只是小程序/WXSS 的单位，浏览器不认识它。**
 * 一旦内联样式里出现 `width: 104rpx`，H5 会把整条声明当作无效值丢掉 ——
 * 元素退回默认尺寸（`<image>` 是 320×240），精灵被撑满整张卡片、
 * 圆形头像变成方块、`view` 里的文字被挤成逐字竖排。
 *
 * 所以长度一律走 `designLength()`：小程序给 `rpx`（原生、支持旋转重排），
 * H5 给 `vw`（设计宽 750 下 `1rpx = 0.13333vw`，与 rpx 等价且随视口自适应）。
 *
 * @example
 *   <View style={styleOf({ width: `${progress}%` })} />
 *   <Image style={squareStyle(104)} />
 */

import { isH5 } from './platform'

/** 设计稿宽度，与 `config/index.ts` 的 `designWidth` 保持一致 */
const DESIGN_WIDTH = 750

/**
 * 把「设计稿 px」（即 750 宽下的 rpx 数值）换算成当前平台合法的 CSS 长度。
 *
 * 小程序：`104rpx`
 * H5：`13.8667vw`（104 ÷ 750 × 100）
 */
export function designLength(designPx: number): string {
  if (!isH5()) return `${designPx}rpx`
  // 保留 4 位小数足够精确（1vw 在 390px 视口下约 3.9px），又不至于产生超长字符串
  return `${Number(((designPx * 100) / DESIGN_WIDTH).toFixed(4))}vw`
}

/** 对象式样式的字符串化；`undefined` / `''` / `null` 的字段会被跳过 */
export function styleOf(rules: Record<string, string | number>): string {
  return Object.entries(rules)
    .filter(([, value]) => value !== '' && value !== undefined && value !== null)
    .map(([key, value]) => `${key}: ${value}`)
    .join('; ')
}

/** 正方形尺寸的简写，供精灵 / 圆环 / 法阵这类等宽高元素使用 */
export function squareStyle(sizeInRpx: number): string {
  const length = designLength(sizeInRpx)
  return styleOf({ width: length, height: length })
}
