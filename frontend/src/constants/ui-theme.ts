/**
 * 界面主题的**词表与取值入口**。
 *
 * ## 本文件里没有色值，也没有主题 id 的字面量
 *
 * 主题 id 的联合类型、展示名、以及 JS 用得上的色值全部来自生成物
 * `./ui-theme-tokens.ts`（真源 = `shared/ui-themes.json` + `styles/tokens.scss`，
 * 由 `npm run gen:theme` 生成）。所以**加一套主题不需要改这里** ——
 * 改 JSON 再重生成，这个文件里的类型与列表自动跟上。
 *
 * 手写第二份 id 列表的坏处很具体：类型上多一个 id、实际没有对应的 CSS 类，
 * 于是用户选中它之后界面**颜色完全不变**（`ui-theme--xxx` 这个类没有任何规则），
 * 而编译器、构建、单测全都是绿的。
 *
 * ## 为什么 canvas 的颜色要从这里取
 *
 * CSS 侧的换色靠 `var(--k-*)`，但 canvas 2D、`Taro.setBackgroundColor`
 * 这类地方读不到 CSS 变量，只能拿具体色值。见 `ui-theme-tokens.ts` 的说明。
 */

import {
  UI_THEME_COLORS,
  UI_THEME_IDS,
  UI_THEME_META,
  type UiThemeColors,
  type UiThemeId
} from './ui-theme-tokens'

export { UI_THEME_COLORS, UI_THEME_IDS, UI_THEME_META }
export type { UiThemeColors, UiThemeId }

/**
 * 用户从未选择过时的主题（规格：「未做过选择时必须是 paper」）。
 *
 * 与后端 `user_settings.ui_theme` 的 `DEFAULT 'paper'` 是同一个值；
 * 前端这份是「拿不到服务端值时」的兜底，权威值仍在服务端。
 */
export const DEFAULT_UI_THEME: UiThemeId = 'paper'

/** 一套主题的元信息 + id，供设置页列表渲染（顺序 = `UI_THEME_IDS` 的顺序）。 */
export interface UiThemeOption {
  id: UiThemeId
  name: string
  mode: 'light' | 'dark'
}

export const UI_THEME_OPTIONS: ReadonlyArray<UiThemeOption> = UI_THEME_IDS.map((id) => ({
  id,
  name: UI_THEME_META[id].name,
  mode: UI_THEME_META[id].mode
}))

/**
 * 主题对应的 CSS 类名。
 *
 * **默认主题返回空串** —— 切回默认主题的做法是「摘掉类」，让 `tokens.scss` 里
 * `var(--k-*, 兜底字面量)` 的兜底值接管，而不是套一个 `.ui-theme--paper`
 * （design.md D5：那样同一批色值就有两处定义）。
 */
export function uiThemeClass(id: UiThemeId): string {
  return id === DEFAULT_UI_THEME ? '' : `ui-theme--${id}`
}

/** 拼「基础类名 + 主题类名」，跳过空串。 */
export function withUiTheme(base: string, id: UiThemeId): string {
  const theme = uiThemeClass(id)
  return theme ? `${base} ${theme}` : base
}

/**
 * 是不是一个合法的主题标识。
 *
 * 服务端有白名单校验（design.md D7），这里是**本机的第二道闸**：
 * 镜像里可能存着上一版留下的、或被人手改过的值，直接拿去拼类名会得到一个
 * 谁都不认识的类（表现为「换了主题没反应」），甚至拼出奇怪的 className。
 */
export function isUiThemeId(value: unknown): value is UiThemeId {
  return typeof value === 'string' && (UI_THEME_IDS as ReadonlyArray<string>).includes(value)
}

/** 不认识的值一律回落到默认主题。 */
export function normalizeUiTheme(value: unknown): UiThemeId {
  return isUiThemeId(value) ? value : DEFAULT_UI_THEME
}

/** 主题展示名；拿不到时回默认主题的名字。 */
export function uiThemeNameOf(id: UiThemeId): string {
  return UI_THEME_META[id]?.name ?? UI_THEME_META[DEFAULT_UI_THEME].name
}

/** JS 侧取色（canvas / 窗口背景）。**不要**在别处手写这些色值。 */
export function uiThemeColorsOf(id: UiThemeId): UiThemeColors {
  return UI_THEME_COLORS[id]
}
