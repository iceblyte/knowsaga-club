/**
 * 正确率环。
 *
 * 原型（01 第 6 屏）用一段内联 SVG 画：
 *     r=28 / stroke-width=8 / 轨道 #E6D6B4 / 进度 从 12 点方向顺时针
 *     / 内圈 r=23 填 9% 同级色 / 圆心 15px 800 字重显示百分比
 *
 * ## 为什么用 Canvas 而不是 SVG
 *
 * 微信小程序**不支持内联 `<svg>` 标签**（`<image>` 可以吃 SVG，但那是静态资源）。
 * 静态资源可以走 data URI，可这个环的弧长是运行期才知道的 ——
 * 真要塞进 data URI 就得每次拼接字符串，也就失去了「延后 0.3s 绘制 +
 * 0.8s 补间」的动效（原型明确要求这两点）。
 * Canvas 2D 是微信里画动态弧线最直接的手段。
 *
 * ## 降级
 *
 * Canvas 的初始化要经过一次 SelectorQuery 异步查询，拿不到 node 时会静默失败。
 * 所以轨道环与圆心数字都用普通元素画在 Canvas **下面/上面** ——
 * 即使 Canvas 完全没画出来，用户看到的也是一个「弧线没上色」的完整环，
 * 而不是一个空洞。
 */

import { Canvas, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef } from 'react'

import { squareStyle } from '../../utils/style'

import './index.scss'

/** 原型机身 332px → 真机 750rpx */
const RATIO = 2.259

/** 原型里的几何参数，全部以 64×64 的画布为基准 */
const BASE = 64
const RADIUS = 28
const STROKE = 8
const INNER_RADIUS = 23

/**
 * 环的颜色阈值。
 *
 * 原型只固定了「80% 用绿」这一种情况，另外两档是按设计系统里既有的
 * 语义色补的 —— 正确率 0% 时环还是绿的会读成「一切正常」，那是错的。
 * 三档取色全部来自 `styles/tokens.scss`：$ok / $gold / $seal。
 */
const COLOR_OK = '#2F7D4F'
const COLOR_MID = '#C8912A'
const COLOR_LOW = '#A63A2E'
const COLOR_TRACK = '#E6D6B4'

function colorOf(percent: number): string {
  if (percent >= 80) return COLOR_OK
  if (percent >= 60) return COLOR_MID
  return COLOR_LOW
}

/** 9% 不透明度的同色内圈（原型 `opacity=.09`） */
function withAlpha(hex: string, alpha: number): string {
  const value = Math.round(alpha * 255)
    .toString(16)
    .padStart(2, '0')
  return `${hex}${value}`
}

export interface AccuracyRingProps {
  /** 正确率百分比，0–100 */
  percent: number
  /** 直径，**写原型 px**（原型 64） */
  size?: number
  /** 环心文字，默认「N%」 */
  label?: string
  /**
   * 是否用大号环心文字。
   *
   * 原型两处用到的环心字号**随环径一起变大**，不是固定值：
   * 结算页是 64px 环配 15px 字，报告主视图是 88px 环配 21px 字。
   * 只放大环而不放大字，88px 的环心会读作「一个没填满的小数字」。
   */
  labelLarge?: boolean
}

export default function AccuracyRing({
  percent,
  size = BASE,
  label,
  labelLarge = false
}: AccuracyRingProps) {
  const canvasId = useRef(`ring-${Math.random().toString(36).slice(2, 9)}`).current
  const clamped = Math.max(0, Math.min(100, percent))

  useEffect(() => {
    let disposed = false
    let stopAnimation: (() => void) | null = null

    /** 原型要求：环延后 0.3s 开始绘制，制造与数字递增的层次感 */
    const delay = setTimeout(() => {
      Taro.createSelectorQuery()
        .select(`#${canvasId}`)
        .fields({ node: true, size: true })
        .exec((res) => {
          if (disposed) return

          const item = res?.[0] as { node?: any; width?: number } | undefined
          const node = item?.node
          if (!node || !item?.width) return

          let dpr = 2
          try {
            dpr = Taro.getSystemInfoSync().pixelRatio || 2
          } catch {
            dpr = 2
          }

          const layoutSize = item.width
          const scale = layoutSize / BASE

          node.width = layoutSize * dpr
          node.height = layoutSize * dpr

          const ctx = node.getContext('2d')
          ctx.scale(dpr, dpr)
          ctx.clearRect(0, 0, layoutSize, layoutSize)

          const cx = (BASE / 2) * scale
          const cy = (BASE / 2) * scale
          const radius = RADIUS * scale
          const lineWidth = STROKE * scale
          const color = colorOf(clamped)

          // 轨道
          ctx.beginPath()
          ctx.arc(cx, cy, radius, 0, Math.PI * 2)
          ctx.strokeStyle = COLOR_TRACK
          ctx.lineWidth = lineWidth
          ctx.stroke()

          // 内圈淡色填充
          ctx.beginPath()
          ctx.arc(cx, cy, INNER_RADIUS * scale, 0, Math.PI * 2)
          ctx.fillStyle = withAlpha(color, 0.09)
          ctx.fill()

          ctx.lineCap = 'round'
          const start = -Math.PI / 2
          const total = (Math.PI * 2 * clamped) / 100

          const raf =
            typeof node.requestAnimationFrame === 'function'
              ? (cb: (t: number) => void) => node.requestAnimationFrame(cb)
              : (cb: (t: number) => void) => {
                  const id = setTimeout(() => cb(Date.now()), 16)
                  return id as unknown as number
                }
          const cancel = (id: number) => {
            if (typeof node.cancelAnimationFrame === 'function') {
              node.cancelAnimationFrame(id)
            } else {
              clearTimeout(id as unknown as ReturnType<typeof setTimeout>)
            }
          }

          const DURATION = 800
          let frameId = 0
          let beginAt = 0

          const draw = (now: number) => {
            if (disposed) return
            if (!beginAt) beginAt = now
            const progress = Math.min(1, (now - beginAt) / DURATION)
            // easeOutCubic：开头快、收尾稳，符合「填充」的物理直觉
            const eased = 1 - Math.pow(1 - progress, 3)

            ctx.clearRect(0, 0, layoutSize, layoutSize)

            ctx.beginPath()
            ctx.arc(cx, cy, radius, 0, Math.PI * 2)
            ctx.strokeStyle = COLOR_TRACK
            ctx.lineWidth = lineWidth
            ctx.lineCap = 'butt'
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(cx, cy, INNER_RADIUS * scale, 0, Math.PI * 2)
            ctx.fillStyle = withAlpha(color, 0.09)
            ctx.fill()

            if (total > 0 && eased > 0) {
              ctx.beginPath()
              ctx.arc(cx, cy, radius, start, start + total * eased)
              ctx.strokeStyle = color
              ctx.lineWidth = lineWidth
              ctx.lineCap = 'round'
              ctx.stroke()
            }

            if (progress < 1) {
              frameId = raf(draw)
            }
          }

          frameId = raf(draw)

          stopAnimation = () => {
            disposed = true
            cancel(frameId)
          }
        })
    }, 300)

    return () => {
      disposed = true
      clearTimeout(delay)
      stopAnimation?.()
    }
  }, [canvasId, clamped])

  const rpxSize = Math.round(size * RATIO)

  return (
    <View className={labelLarge ? 'ring ring--lg' : 'ring'} style={squareStyle(rpxSize)}>
      {/* 轨道环：Canvas 没画出来时的兜底，读起来仍是一个完整的环 */}
      <View className='ring__track' />
      <Canvas
        className='ring__canvas'
        id={canvasId}
        canvasId={canvasId}
        type='2d'
        style={squareStyle(rpxSize)}
      />
      {/* 圆心数字用普通元素而不是 Canvas 文字：字重与字体回退更可控，
          而且 Canvas 初始化失败时它仍然在 */}
      <Text className='ring__label'>{label ?? `${clamped}%`}</Text>
    </View>
  )
}
