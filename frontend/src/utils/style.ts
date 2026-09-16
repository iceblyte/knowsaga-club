/**
 * 内联样式工具。
 *
 * ## 为什么必须写成字符串
 *
 * Taro 的 H5 组件（`View` / `ScrollView` / …）是 Stencil 自定义元素。
 * React 把 `style` **对象**挂在自定义元素上时，属性不会落到元素的 `style` 属性上 ——
 * 实测 `getAttribute('style')` 为 `null`，`getComputedStyle` 也拿不到值。
 * 结果就是所有内联尺寸（进度条宽度、精灵大小、内容区高度）在 H5 上**静默失效**：
 * 没有报错，只是「宽度 45%」变成了 0。
 *
 * 写成字符串时 React 会把它当普通属性写入，自定义元素即可正常解析。
 * 小程序端（WXML 的 `style` 属性）两种写法都支持，所以全站统一用字符串最省心。
 *
 * @example
 *   <View style={styleOf({ width: `${progress}%` })} />
 */
export function styleOf(rules: Record<string, string | number>): string {
  return Object.entries(rules)
    .filter(([, value]) => value !== '' && value !== undefined && value !== null)
    .map(([key, value]) => `${key}: ${value}`)
    .join('; ')
}

/** 正方形尺寸的简写，供精灵 / 圆环 / 法阵这类等宽高元素使用 */
export function squareStyle(sizeInRpx: number): string {
  return styleOf({ width: `${sizeInRpx}rpx`, height: `${sizeInRpx}rpx` })
}
