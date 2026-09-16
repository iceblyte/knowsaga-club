/**
 * 页面骨架：状态栏占位 + 导览栏 + 可滚动内容区。
 *
 * 对应原型里每个机身都有的这三层结构：
 *     <div class="sbar">…</div>   ← 状态栏
 *     <div class="nav">…</div>    ← 导览栏（返回键 / 标题 / 右侧文案）
 *     <div class="screen">…</div> ← 内容区（overflow-y:auto）
 *
 * ## 与原型的两处必要差异（均为「样机 vs 真机」的差异，不是设计变更）
 *
 * 1. **不渲染 `.phone` 外框**。原型里的 `332×700` 机身是展示用的样机，
 *    真机上页面本身就是屏幕，画外框会多出一圈边框。
 *
 * 2. **状态栏不显示假时间**。原型 `.sbar` 里的「9:41」与电池图标是样机 chrome，
 *    真机上系统状态栏已经存在。这里改为按 `statusBarHeight` 撑出等高占位，
 *    避免内容被系统状态栏压住（`navigationStyle: 'custom'` 下页面是全屏的）。
 *
 * 因为导览栏需要**固定不动**、只有内容区滚动（原型里 `.nav` 与 `.screen` 是兄弟节点，
 * 只有 `.screen` 设了 `overflow-y:auto`），所以内容区用 `ScrollView` 而非页面级滚动。
 */

import { ScrollView, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import type { ReactNode } from 'react'

import './index.scss'

export interface PhoneShellProps {
  /** 导览栏标题，原型居中显示 */
  navTitle?: string
  /** 导览栏右侧文案，原型里是页码（如「1 / 5」）或「我的」 */
  navRight?: string
  /** 点击导览栏右侧文案的回调；不传则右侧不可点（纯展示） */
  onNavRightTap?: () => void
  /** 是否显示导览栏 */
  showNav?: boolean
  /** 是否显示返回键；默认显示（除标签页外都要返回） */
  showBack?: boolean
  /** 点击返回键的回调；不传则默认 `navigateBack` */
  onBack?: () => void
  /** 内容区是否可滚动 */
  scroll?: boolean
  /** 内容区附加类名（原型里用于 `.screen.center` 这类变体） */
  screenClassName?: string
  /** 为底部固定标签栏预留的高度（标签页传 true） */
  reserveTabBar?: boolean
  children?: ReactNode
}

/** 状态栏高度：`navigationStyle: custom` 下页面全屏，需自行让位 */
function useStatusBarHeight(): number {
  try {
    return Taro.getSystemInfoSync().statusBarHeight ?? 20
  } catch {
    return 20
  }
}

export default function PhoneShell({
  navTitle,
  navRight,
  onNavRightTap,
  showNav = true,
  showBack = true,
  onBack,
  scroll = true,
  screenClassName = '',
  reserveTabBar = false,
  children
}: PhoneShellProps) {
  const statusBarHeight = useStatusBarHeight()

  const handleBack = () => {
    if (onBack) {
      onBack()
      return
    }
    Taro.navigateBack({ delta: 1 }).catch(() => {
      // 无上一页时兜底回到大厅，避免返回键变成死按钮
      Taro.switchTab({ url: '/pages/hall/index' })
    })
  }

  const screenCls = [
    'screen',
    scroll ? '' : 'screen--static',
    reserveTabBar ? 'screen--reserve-tabbar' : '',
    screenClassName
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <View className='page'>
      {/* 状态栏占位：真实高度，避免与系统状态栏重叠 */}
      <View className='page__statusbar' style={{ height: `${statusBarHeight}px` }} />

      {showNav && (
        <View className='nav'>
          {showBack ? (
            <Text className='nvb' onClick={handleBack}>
              ‹
            </Text>
          ) : (
            <View className='nvb' />
          )}
          <Text className='t'>{navTitle}</Text>
          {navRight ? (
            <Text className='nvr' onClick={onNavRightTap}>
              {navRight}
            </Text>
          ) : (
            <View className='nvr' />
          )}
        </View>
      )}

      {scroll ? (
        <ScrollView className={screenCls} scrollY enhanced showScrollbar={false}>
          {children}
        </ScrollView>
      ) : (
        <View className={screenCls}>{children}</View>
      )}
    </View>
  )
}
