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
import { TAB_ORDER, useTabStore } from '../store/useTabStore'

import './index.scss'

export default function CustomTabBar() {
  const current = useTabStore((s) => s.current)

  const handleTap = (key: TabKey, index: number) => {
    if (index === current) return
    // 先乐观更新，避免切换瞬间指示条闪回旧位置
    useTabStore.getState().setCurrent(index)
    Taro.switchTab({ url: `/${TAB_PATHS[key]}` })
  }

  return (
    <View className='tabbar'>
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
