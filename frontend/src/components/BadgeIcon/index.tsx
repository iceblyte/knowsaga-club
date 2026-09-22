/**
 * 勋章图案（原型 04·9 的圆底，本次改为矢量图案）。
 *
 * ## 为什么不再用单字
 *
 * 后端 `BadgeSpec.icon` 给的是一个汉字（「启」「连」「百」…），早期就把它
 * 直接摆在圆底里。那是设计系统 `.badge` 的占位做法 —— 18 枚摆在一起时，
 * 一屏汉字读起来像标签墙，没有「收集品」的质感。本次改成
 * **缎带 + 圆盘 + 徽记**的图案（见 `scripts/generate_badge_icons.py`）。
 *
 * ## 档位由谁决定
 *
 * 后端只给 `unlocked` 与 `tier`（`gold` / `rare`），**没有** `off` ——
 * 「未解锁用灰色」是前端的展示决定，所以这一层把它翻成三档
 * （`gold` / `rare` / `off`），见 `artTier`。
 *
 * ## 缺图案时退回单字，不留空
 *
 * 后端**新增**勋章时，前端这个图案表里不会有它 —— 直接渲染空图会得到一个
 * 白洞，比一个汉字更糟。所以找不到图案就退回原来的 `.badge` + 单字。
 */

import { Image, View } from '@tarojs/components'

import { BADGE_ART, type BadgeArtTier } from '../../assets/badges'
import { squareStyle } from '../../utils/style'

import './index.scss'

/** 换算系数：750 ÷ 332，与 `Avatar` / `Sprite` 的约定一致 */
const PX_RATIO = 2.259

/**
 * 由后端字段决定图案档位。
 *
 * 导出是给调用方（勋章墙）复用的：它自己也要按同一规则选图，
 * 两处各写一遍就会出现「格子是灰的、列表是金的」。
 */
export function artTier(unlocked: boolean, tier: string): BadgeArtTier {
  if (!unlocked) return 'off'
  return tier === 'rare' ? 'rare' : 'gold'
}

export interface BadgeIconProps {
  /** 勋章 key（后端 `BadgeItem.key`） */
  badgeKey: string
  /** 图案档位（用 `artTier()` 从后端字段翻出来） */
  tier: BadgeArtTier
  /** 尺寸，**直接写原型 px**（勋章墙是 62），内部换算 */
  size?: number
  /** 图案缺失时退回显示的单字（后端 `BadgeItem.icon`） */
  fallback?: string
  className?: string
}

export default function BadgeIcon({
  badgeKey,
  tier,
  size = 62,
  fallback = '',
  className = ''
}: BadgeIconProps) {
  const style = squareStyle(Math.round(size * PX_RATIO))
  const src = BADGE_ART[badgeKey]?.[tier]

  if (!src) {
    // 退回旧外观：`.badge` 的圆底 + 单字（`.off` / `.rare` 修饰符见 base.scss）
    const modifier = tier === 'off' ? ' off' : tier === 'rare' ? ' rare' : ''
    return (
      <View
        className={`badge badge-icon--fallback${modifier}${className ? ` ${className}` : ''}`}
        style={style}
      >
        {fallback}
      </View>
    )
  }

  return (
    <Image
      className={`badge-icon${className ? ` ${className}` : ''}`}
      style={style}
      src={src}
      mode='aspectFit'
      aria-label={fallback || badgeKey}
    />
  )
}
