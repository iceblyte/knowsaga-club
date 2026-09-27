// ⚠️ 生成物，请勿手改。
//
// 真源：shared/ui-themes.json（四套新主题的核心色）
//       frontend/src/styles/tokens.scss（默认主题 paper 的兜底字面量）
// 配方：frontend/scripts/lib/ui-theme-recipe.mjs
// 生成：frontend/scripts/gen_theme_scss.mjs
//
// 为什么同一批颜色还要再来一遍：CSS 侧靠 var(--k-*) 换色，而 canvas 与
// Taro.setBackgroundColor 这类地方**读不到 CSS 变量**，只能在 JS 里拿具体色值。
// 手抄一份就会漂 —— 改了 JSON 生成完 scss 就以为改完了，canvas 那份还停在旧值，
// 而且**默认主题下完全看不出来**。所以这里由同一个配方生成。
//
// 改色仍然是「改 JSON → `npm run gen:theme`」，然后跑 `npm run check:theme`。

/** 一套主题里 **JS 需要**的那几个颜色（不是全部 69 个令牌）。 */
export interface UiThemeColors {
  /** 窗口背景（`Taro.setBackgroundColor`）—— 对应 `--k-board` */
  readonly board: string
  /** 设置页主题小样的纸面 —— 对应 `--k-paper` */
  readonly paper: string
  /** 设置页主题小样的主色 —— 对应 `--k-magic` */
  readonly magic: string
  /** 正确率环 ≥80% —— 对应 `--k-ok` */
  readonly ok: string
  /** 正确率环 ≥60% —— 对应 `--k-gold` */
  readonly gold: string
  /** 正确率环 <60% 与冒险日志进度条 —— 对应 `--k-bad` */
  readonly bad: string
  /** 正确率环的轨道 —— 对应 `--k-line-ring` */
  readonly lineRing: string
}

/** 主题元信息。`id` 同时是 CSS 类名的后缀：`ui-theme--<id>`。 */
export const UI_THEME_META = {
  paper: { name: '纸与印', mode: 'light' },
  indigo: { name: '宣纸靛墨', mode: 'light' },
  vermilion: { name: '素白墨朱', mode: 'light' },
  midnight: { name: '夜航公会', mode: 'dark' },
  lime: { name: '青柠', mode: 'light' }
} as const

/** 五套主题的标识。**这个联合类型也从真源生成** —— 加主题只改 JSON + 本脚本的 DEFAULT_THEME。 */
export type UiThemeId = keyof typeof UI_THEME_META

/** 所有主题的 id，顺序 = 设置页里的展示顺序（paper 在最前）。 */
export const UI_THEME_IDS = ['paper', 'indigo', 'vermilion', 'midnight', 'lime'] as ReadonlyArray<UiThemeId>

export const UI_THEME_COLORS: Record<UiThemeId, UiThemeColors> = {
  paper: { board: '#f1e8d0', paper: '#fefcf6', magic: '#2f6bd8', ok: '#2f7d4f', gold: '#c8912a', bad: '#a63a2e', lineRing: '#e6d6b4' },
  indigo: { board: '#ebe8e2', paper: '#ffffff', magic: '#1e4b8f', ok: '#2c6a46', gold: '#b0821f', bad: '#a63a2e', lineRing: '#d6d2c9' },
  vermilion: { board: '#ededef', paper: '#ffffff', magic: '#18181b', ok: '#2a6b45', gold: '#a87a16', bad: '#b4322a', lineRing: '#d7d7da' },
  midnight: { board: '#0d0f14', paper: '#1d212b', magic: '#e0a455', ok: '#54c08a', gold: '#e0a455', bad: '#e56f5e', lineRing: '#3e4451' },
  lime: { board: '#f5f5f5', paper: '#ffffff', magic: '#70c000', ok: '#477900', gold: '#c27c09', bad: '#d80024', lineRing: '#d4d4d4' }
}
