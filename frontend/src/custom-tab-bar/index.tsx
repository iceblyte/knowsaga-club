/**
 * 自定义标签栏（对应原型 `.tabbar`）。
 *
 * 为什么不用微信原生 tabBar：
 * 原型在选中项上有一条 26×2px 的顶部指示条，且图标是 1.9 描边宽的线性图标。
 * 原生 tabBar 只支持「图标 + 文字换色」，做不出指示条，也要求 PNG 位图。
 * 所以用自定义 tabBar（app.config.ts 中 `custom: true`）精确还原。
 *
 * 选中态来自 `useTabStore`，由各标签页在 `useDidShow` 时上报，
 * 详见 `src/store/useTabStore.ts` 里的说明。
 */

import { Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { TAB_ICONS, TAB_PATHS, TAB_TEXTS, type TabKey } from '../assets/icons/tab'
import { withUiTheme } from '../constants/ui-theme'
import { useAppStore } from '../store/useAppStore'
import { TAB_ORDER, useTabStore } from '../store/useTabStore'

import './index.scss'

export default function CustomTabBar() {
  const current = useTabStore((s) => s.current)

  /**
   * 主题挂载点之二。
   *
   * 自定义 tabBar 是**独立于页面**的组件（不套在 `PhoneShell` 里），所以它
   * 必须自己挂一次类 —— 否则切到暗色主题后，底部那条依旧是浅色的，而且
   * 因为 `.tabbar` 是 `position: fixed` 浮在页面之上，会在暗底上显得格外刺眼。
   *
   * ⚠️ 图标本身**不跟随主题**：`assets/icons/tab` 里的 PNG 烘焙了固定的
   * 未选中 / 选中两色。这是已登记的能力边界（design.md D8、规格里的
   * 「换肤覆盖不到的部分不得被宣称已覆盖」），文字与背景跟随、图标不跟随。
   */
  const uiTheme = useAppStore((s) => s.uiTheme)

  const handleTap = (key: TabKey, index: number) => {
    if (index === current) return
    // 先乐观更新，避免切换瞬间指示条闪回旧位置
    useTabStore.getState().setCurrent(index)
    Taro.switchTab({ url: `/${TAB_PATHS[key]}` })
  }

  return (
    <View className={withUiTheme('tabbar', uiTheme)}>
      {TAB_ORDER.map((key, index) => {
        const active = index === current
        return (
          <View
            key={key}
            className={`tabbar__item${active ? ' on' : ''}`}
            onClick={() => handleTap(key, index)}
          >
            <Image
              className='tabbar__icon'
              src={active ? TAB_ICONS[key].active : TAB_ICONS[key].normal}
              mode='aspectFit'
            />
            <Text className='tabbar__text'>{TAB_TEXTS[key]}</Text>
          </View>
        )
      })}
    </View>
  )
}
