/**
 * 界面主题（**原型外**的一屏）。
 *
 * 原型只定义了「纸与印」一套外观，设置页里没有换主题这件事 —— 这一屏与另外
 * 四套主题的依据是既有设计实验室产物，不是原型（见 `constants/copy.ts` 的
 * `UI_THEME_COPY` 与 `openspec/changes/add-ui-theme-switch/design.md` 冲突点 2）。
 *
 * ## 切换为什么是「先改本地、再提交、失败翻回去」
 *
 * 与设置页那三个开关同一套纪律（`SETTINGS_COPY.switchFailed`）：换肤必须是
 * **零延迟**的，等一次网络往返再变色会让人以为没点上、于是再点一次；失败时
 * 翻回原主题并说一句「没切换成功，已回到原来的主题」—— 界面最终停在服务端
 * 认可的那一套上，用户不会带着一个假主题离开。
 *
 * ## 这里不做任何请求读取
 *
 * 当前主题来自 store（它已经同步读过本地镜像，且 `app.ts` 会对账服务端），
 * 所以本页**不需要** `useAsyncData` —— 少一次请求、也少一个「转圈」态。
 * 提交走的就是设置页同一个 `updateSettings`（`PATCH /users/me/settings`）。
 *
 * ## 色值一律来自生成物
 *
 * 小样要显示**每套主题**的颜色（含 `paper`），而 canvas / 小样这类地方拿不到
 * 「另一个主题」的 CSS 变量。所以色值取自 `uiThemeColorsOf(id)`，也就是
 * `constants/ui-theme-tokens.ts`（真源 = `shared/ui-themes.json` + `tokens.scss`）。
 * **不要**在这里手写十六进制 —— 那会立刻多出一份会漂的表。
 */

import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useCallback, useState } from 'react'

import PhoneShell from '../../../components/PhoneShell'
import { UI_THEME_COPY } from '../../../constants/copy'
import { UI_THEME_OPTIONS, uiThemeColorsOf, type UiThemeId } from '../../../constants/ui-theme'
import { updateSettings } from '../../../services/settings'
import { useAppStore } from '../../../store/useAppStore'
import { styleOf } from '../../../utils/style'

import './index.scss'

export default function UiThemePage() {
  const uiTheme = useAppStore((s) => s.uiTheme)
  /** 提交中：期间不接受第二次点击，避免发出两个相反的请求 */
  const [busy, setBusy] = useState(false)

  const pick = useCallback(
    (id: UiThemeId) => {
      if (busy || id === uiTheme) return
      const previous = uiTheme
      setBusy(true)

      // 先改本地 —— 界面当场换色（含窗口背景与镜像，见 store 的 setUiTheme）
      useAppStore.getState().setUiTheme(id)

      updateSettings({ ui_theme: id })
        .catch(() => {
          // 失败：翻回原来那一套，并说清「没生效」
          useAppStore.getState().setUiTheme(previous)
          Taro.showToast({ title: UI_THEME_COPY.applyFailed, icon: 'none' })
        })
        .finally(() => {
          setBusy(false)
        })
    },
    [busy, uiTheme]
  )

  return (
    <PhoneShell navTitle={UI_THEME_COPY.navTitle} screenClassName='theme-page'>
      <View className='theme-page__intro'>{UI_THEME_COPY.intro}</View>

      {UI_THEME_OPTIONS.map((option) => {
        const on = option.id === uiTheme
        const colors = uiThemeColorsOf(option.id)
        return (
          <View
            key={option.id}
            className={`card plain theme-opt${on ? ' theme-opt--on' : ''}`}
            onClick={() => pick(option.id)}
          >
            {/* 小样：纸色作框 + 主色 / 黄铜 / 错误色三条色带。
                色值来自生成物（见文件头），不是手写的十六进制。 */}
            <View
              className='theme-opt__swatch'
              style={styleOf({ 'background-color': colors.paper })}
            >
              <View className='theme-opt__band' style={styleOf({ 'background-color': colors.magic })} />
              <View className='theme-opt__band' style={styleOf({ 'background-color': colors.gold })} />
              <View className='theme-opt__band' style={styleOf({ 'background-color': colors.bad })} />
            </View>

            <View className='theme-opt__tx'>
              <View className='theme-opt__name'>{option.name}</View>
              <View className='theme-opt__mode'>
                {option.mode === 'dark' ? UI_THEME_COPY.modeDark : UI_THEME_COPY.modeLight}
              </View>
            </View>

            {/* 「不只依赖颜色」：选中的那一行除了主色描边，还有这颗胶囊 */}
            {on && <Text className='pill ok'>{UI_THEME_COPY.current}</Text>}
          </View>
        )
      })}

      {/* 覆盖边界：规格要求如实说明，不写「全部界面都会变」 */}
      <View className='theme-page__boundary'>{UI_THEME_COPY.boundaryNote}</View>
    </PhoneShell>
  )
}
