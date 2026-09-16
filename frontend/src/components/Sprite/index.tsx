/**
 * 精灵角色渲染器。
 *
 * 精灵来自 `src/assets/sprites/index.ts`（由 `scripts/extract_sprites.py`
 * 从原型内联 SVG 抽取后转成 base64 data URI）。
 * 页面内容区用 data URI 没问题 —— 矢量清晰、体积极小，
 * 只有**标签栏**例外（官方文档明确 base64 图片在 TabBar 中不展示），
 * 所以标签栏图标走的是 PNG 文件，见 `src/assets/icons/` 与 `custom-tab-bar/`。
 */

import { Image } from '@tarojs/components'

import { SPRITE_LABELS, SPRITES, type SpriteName } from '../../assets/sprites'
import { squareStyle } from '../../utils/style'

import './index.scss'

/** 原型里精灵可用的动效（全站只有这 6 个 keyframe） */
export type SpriteMotion = 'none' | 'floaty' | 'floaty-slow' | 'floaty-fast' | 'twinkle' | 'drift'

export interface SpriteProps {
  /** 精灵标识 */
  name: SpriteName
  /** 尺寸，**直接写原型 px**（如原型 80×80 就传 80），内部按 2.259 换算 */
  size: number
  /** 动效；默认不动（原型纪律：静态场景一律不动） */
  motion?: SpriteMotion
  className?: string
  onClick?: () => void
}

const MOTION_CLASS: Record<SpriteMotion, string> = {
  none: '',
  floaty: 'floaty',
  'floaty-slow': 'floaty slow',
  'floaty-fast': 'floaty fast',
  twinkle: 'twinkle',
  drift: 'drift'
}

export default function Sprite({
  name,
  size,
  motion = 'none',
  className = '',
  onClick
}: SpriteProps) {
  // 原型机身 332px → 真机 750rpx，换算系数 750 ÷ 332
  const rpxSize = Math.round(size * 2.259)

  const cls = ['sprite', MOTION_CLASS[motion], className].filter(Boolean).join(' ')

  return (
    <Image
      className={cls}
      style={squareStyle(rpxSize)}
      src={SPRITES[name]}
      mode='aspectFit'
      aria-label={SPRITE_LABELS[name]}
      onClick={onClick}
    />
  )
}
