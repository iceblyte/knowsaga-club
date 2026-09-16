/**
 * 页面骨架：状态栏占位 + 导览栏 + 内容区。
 *
 * 对应原型里每个机身都有的这三层结构：
 *     <div class="sbar">…</div>   ← 状态栏
 *     <div class="nav">…</div>    ← 导览栏（返回键 / 标题）
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
 * ## 导览栏右侧不再有文字
 *
 * 原型在 `.nav` 右侧放页码（「1 / 5」）或动作（「我的」「重生成」）。这些属于
 * 开发者视角的冗余信息，产品已确认全部去掉。**右侧会保留一个等宽的空白占位**，
 * 因为标题是居中的 —— 去掉占位会让标题整体左偏。
 *
 * ## 内容区高度必须**显式给定**（重要）
 *
 * 滚动态下内容区是 `ScrollView`（真机为 `scroll-view`）。小程序里 `scroll-view`
 * 的高度需要是确定值，而「父级 flex + 自己 `flex:1; height:0`」这种写法在小程序
 * 渲染引擎里并不保证被解开 —— 一旦没解开，容器高度为 0：内容看不见、也滚不动，
 * 而页面又因为存在 scroll-view 被设了 `disableScroll`，用户就彻底卡在这一屏。
 * 大厅/召唤页之所以一直正常，是因为它们不滚动，走的是页面原生滚动。
 *
 * 所以这里直接按 `100vh - 状态栏 - 导览栏` 算出一个确定高度交给 `ScrollView`，
 * 不依赖 flex 的二次分配。导览栏高度按原型比例（48px @ 332px 机身宽）换算。
 */

import { ScrollView, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import type { ReactNode } from 'react'

import { styleOf } from '../../utils/style'

import './index.scss'

/** 导览栏在原型里的高度；机身宽见 prototype/00-设计规范.html */
const NAV_PROTO_PX = 48
const PROTOTYPE_WIDTH = 332

export interface PhoneShellProps {
  /** 导览栏标题，原型居中显示 */
  navTitle?: string
  /** 是否显示导览栏 */
  showNav?: boolean
  /** 是否显示返回键；默认显示（除标签页外都要返回） */
  showBack?: boolean
  /** 点击返回键的回调；不传则默认 `navigateBack` */
  onBack?: () => void
  /** 内容区是否用滚动容器承载（内容可能超出一屏时传 true） */
  scroll?: boolean
  /** 内容区附加类名（原型里用于 `.screen.center` 这类变体） */
  screenClassName?: string
  /** 为底部固定标签栏预留的高度（标签页传 true） */
  reserveTabBar?: boolean
  children?: ReactNode
}

interface ShellMetrics {
  /** 系统状态栏高度（px），用于撑出等高占位 */
  statusBarHeight: number
  /** 内容区高度（CSS 长度），`100vh` 减去状态栏与导览栏 */
  contentHeight: string
}

/** 兜底尺寸：取不到系统信息时按一台普通手机估算 */
const FALLBACK_STATUS_BAR = 20
const FALLBACK_WINDOW_WIDTH = 375

/**
 * 取一个有限数值。
 *
 * **不能只用 `??` 兜底** —— H5 端 Taro 给出的 `statusBarHeight` 实测是 `NaN`
 * 而不是 `undefined`，`??` 拦不住它，于是高度会算成 `calc(100vh - NaNpx)`。
 * 这是无效声明，浏览器直接丢弃，内容区又退回「撑满内容」的高度（实测 1441px），
 * 底部按钮再次跑到屏幕外 —— 表面看是「没生效」，实际是 NaN 穿透了兜底。
 */
function finiteOr(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function useShellMetrics(showNav: boolean): ShellMetrics {
  let statusBarHeight = FALLBACK_STATUS_BAR
  let windowWidth = FALLBACK_WINDOW_WIDTH

  try {
    const info = Taro.getSystemInfoSync()
    // H5 没有系统状态栏，取不到就按 0 处理；小程序端始终有真实值
    statusBarHeight = finiteOr(info.statusBarHeight, 0)
    windowWidth = finiteOr(info.windowWidth, FALLBACK_WINDOW_WIDTH)
  } catch {
    statusBarHeight = FALLBACK_STATUS_BAR
    windowWidth = FALLBACK_WINDOW_WIDTH
  }

  const navHeight = showNav
    ? Math.round((windowWidth * NAV_PROTO_PX) / PROTOTYPE_WIDTH)
    : 0

  return {
    statusBarHeight,
    contentHeight: `calc(100vh - ${statusBarHeight + navHeight}px)`
  }
}

export default function PhoneShell({
  navTitle,
  showNav = true,
  showBack = true,
  onBack,
  scroll = true,
  screenClassName = '',
  reserveTabBar = false,
  children
}: PhoneShellProps) {
  const { statusBarHeight, contentHeight } = useShellMetrics(showNav)

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
      <View className='page__statusbar' style={styleOf({ height: `${statusBarHeight}px` })} />

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
          {/* 右侧只保留占位：标题居中需要它，但不再放任何文字 */}
          <View className='nvr' />
        </View>
      )}

      {scroll ? (
        <ScrollView
          className={screenCls}
          style={styleOf({ height: contentHeight })}
          scrollY
          enableFlex
          enhanced
          showScrollbar={false}
        >
          {children}
        </ScrollView>
      ) : (
        <View className={screenCls}>{children}</View>
      )}
    </View>
  )
}
