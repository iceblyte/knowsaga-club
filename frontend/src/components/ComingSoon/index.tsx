/**
 * 统一空态页。
 *
 * 两种使用场景：
 *
 * 1. **未开发的标签页**（卷轴工坊 / 公会社交 / 我的）。已确认的决策是
 *    「保留 5 个 tab，未开发的 3 个进入统一空态页」——保留 tab 是因为
 *    原型的信息架构本身就是 5 个，砍掉会让产品立刻显得缺胳膊少腿；
 *    而做成空态而不是隐藏，用户才知道「这里以后会有东西」。
 *
 * 2. **尚未实现的流程页**（副本召唤中 / 确认 / 挑战 / 结算 / 异常）。
 *    这些页在 Phase 2 / 3 会被真实实现替换掉，先占位是为了让
 *    `app.config.ts` 声明的路由全部可解析 —— 半成品路由会让 `build:weapp` 直接失败。
 *
 * 文案刻意**说清「以后会有什么」而不是「暂未开放」**：
 * 「暂未开放」只传达缺失，而「会支持上传文档与粘贴网址」传达的是意图。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import MagicStage from '../MagicStage'
import PhoneShell from '../PhoneShell'
import type { SpriteName } from '../../assets/sprites'
import { useTabPage } from '../../hooks/useTabPage'
import type { TabKey } from '../../store/useTabStore'

import './index.scss'

export interface ComingSoonProps {
  /** 导览栏标题 */
  navTitle: string
  /** 若是标签页，传入标识以同步底部标签栏的选中态 */
  tabKey?: TabKey
  /** 一句话主标题 */
  headline: string
  /** 补充说明：这一页**以后会有什么** */
  description: string
  /** 主视觉精灵，默认拾拾 */
  sprite?: SpriteName
  /** 是否显示「回到社团大厅」按钮 */
  showHomeButton?: boolean
}

export default function ComingSoon({
  navTitle,
  tabKey,
  headline,
  description,
  sprite = 'shishi',
  showHomeButton = true
}: ComingSoonProps) {
  // 标签页才需要上报选中态；流程页传 undefined，useTabPage 会跳过
  useTabPage(tabKey)

  return (
    <PhoneShell
      navTitle={navTitle}
      showBack={!tabKey}
      screenClassName='coming-soon'
      reserveTabBar={Boolean(tabKey)}
    >
      {/* 主视觉与文案作为一个整体在剩余空间里居中；按钮固定贴底 */}
      <View className='coming-soon__main'>
        <MagicStage size={150} spriteSize={64} sprite={sprite} spriteMotion='floaty' />
        <View className='coming-soon__text'>
          <Text className='h coming-soon__headline'>{headline}</Text>
          <Text className='sub coming-soon__desc'>{description}</Text>
        </View>
      </View>

      {showHomeButton && (
        <Button
          className='btn ghost coming-soon__btn'
          onClick={() => Taro.switchTab({ url: '/pages/hall/index' })}
        >
          回到社团大厅
        </Button>
      )}
    </PhoneShell>
  )
}
