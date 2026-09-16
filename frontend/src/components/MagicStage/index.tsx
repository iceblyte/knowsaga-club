/**
 * 法阵舞台：旋转的法阵 + 居中的精灵。
 *
 * 原型结构（`.stage` / `.stage-c`）：
 *     <div class="stage" style="width:176px;height:176px">
 *       <svg class="spin" viewBox="0 0 120 120">…</svg>   ← 绝对定位铺满，匀速旋转
 *       <div class="stage-c"><svg class="sprite floaty">…</svg></div>  ← 居中在上层
 *     </div>
 *
 * 转用在小程序里不生效，这里用 CSS `animation: spin` 实现 —— 转的是
 * `<image>` 元素本身（法阵是「中心对称」图形，整体旋转视觉等价于原型里转 svg）。
 *
 * 出现位置：启动页、副本召唤中、提交并生成报告中（原型 3 处）。
 */

import { Image, View } from '@tarojs/components'

import { DECORATIONS } from '../../assets/decorations'
import { squareStyle } from '../../utils/style'
import Sprite, { type SpriteMotion } from '../Sprite'
import type { SpriteName } from '../../assets/sprites'

import './index.scss'

export interface MagicStageProps {
  /** 法阵直径，**写原型 px**（如原型 176 就传 176） */
  size: number
  /** 精灵尺寸，写原型 px */
  spriteSize: number
  /** 精灵标识，默认拾拾 */
  sprite?: SpriteName
  /** 精灵动效，默认浮空 */
  spriteMotion?: SpriteMotion
  /** 反向旋转（原型 `.spin-r`，24s） */
  reverse?: boolean
  /** 关闭旋转（静态场景，如结算页） */
  still?: boolean
  className?: string
}

const RATIO = 2.259

export default function MagicStage({
  size,
  spriteSize,
  sprite = 'shishi',
  spriteMotion = 'floaty',
  reverse = false,
  still = false,
  className = ''
}: MagicStageProps) {
  const rpx = Math.round(size * RATIO)

  const spinCls = still ? '' : reverse ? 'spin-r' : 'spin'

  return (
    <View className={`magic-stage ${className}`} style={squareStyle(rpx)}>
      <Image className={`magic-stage__circle ${spinCls}`} src={DECORATIONS.magicCircle} mode='aspectFit' />
      <View className='magic-stage__core'>
        <Sprite name={sprite} size={spriteSize} motion={spriteMotion} />
      </View>
    </View>
  )
}
