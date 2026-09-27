#!/usr/bin/env node
/**
 * 从两个真源生成两份「同一批颜色」的产物：
 *
 * | 产物 | 用在哪 | 为什么需要 |
 * |---|---|---|
 * | `src/styles/_themes.scss` | WXSS / CSS | `var(--k-*)` 的取值表，运行时换色靠它 |
 * | `src/constants/ui-theme-tokens.ts` | JS（canvas / 原生 API） | 那些地方**读不到 CSS 变量** |
 *
 * 真源有两处（design.md D4 / D5）：
 *   · `shared/ui-themes.json`          —— 四套**新**主题的核心色
 *   · `src/styles/tokens.scss` 的兜底位 —— **默认**主题（paper）的全部色值
 *
 * ## 为什么需要那份 TS
 *
 * 正确率环是 Canvas 2D 画的（`components/AccuracyRing`），窗口背景要走
 * `Taro.setBackgroundColor` —— 两者都拿不到 `getComputedStyle`。如果为了这几个
 * 颜色再手抄一份表，就有了「CSS 一份、JS 一份」的同口径两处实现：改 JSON
 * 生成完 scss 就以为改完了，canvas 那份还停在旧值，而且**默认主题下完全看不出来**。
 * 所以这里把 JS 需要的那几个令牌也一并生成，让「改色」始终只有一条路径。
 *
 * ## 为什么没有 `.ui-theme--paper`
 *
 * 默认主题的色值真源是 `tokens.scss` 里 `var()` 的**兜底字面量**。如果再生成
 * 一份 `.ui-theme--paper { --k-board: #f1e8d0; … }`，同一批数字就有了两处实现 ——
 * 改 tokens.scss 忘了改生成物，默认主题就会悄悄错位。所以切换到默认主题的做法是
 * **摘掉类**，让兜底值接管；scss 产物里不含 paper 块（TS 产物里含，因为它没法靠
 * 「摘掉类」拿到值）。
 *
 * ## 用法
 *
 * ```
 * cd frontend && npm run gen:theme                       # 写盘（两个产物）
 * cd frontend && node scripts/gen_theme_scss.mjs --check # 只校验是否最新
 * ```
 *
 * `--check` 供 `npm run check:theme` 调用：任一产物与真源不一致就退出码 1，
 * 防止「改了 JSON / tokens.scss 忘了重生成」被提交进仓库。
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  REPO_ROOT,
  THEMES_JSON,
  TOKENS,
  TOKENS_SCSS,
  deriveTheme,
  loadThemes,
  readDefaultTokens
} from './lib/ui-theme-recipe.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')
const OUT_SCSS = path.join(FRONTEND, 'src', 'styles', '_themes.scss')
const OUT_TS = path.join(FRONTEND, 'src', 'constants', 'ui-theme-tokens.ts')

/** 默认主题的 id 与展示名。它的色值不在 JSON 里（D5），这条只是「标签」。 */
const DEFAULT_THEME = { id: 'paper', name: '纸与印', mode: 'light' }

/**
 * **JS 侧需要**的令牌（不是全部 69 个）。
 *
 * 只收真需要的那几个 —— 这份表是打进包里的字符串，多一个令牌就多一份
 * 要多处同步的东西，而 canvas / 原生 API 目前只用到这五个。
 * 将来多一处需要（例如公会卡导出图纳入主题，design.md D8 说那是另立变更），
 * 在这里加一行并跑 `gen:theme` 即可，不要去手改产物。
 */
const JS_TOKENS = [
  { scss: 'board', ts: 'board', note: '窗口背景（`Taro.setBackgroundColor`）—— 对应 `--k-board`' },
  { scss: 'paper', ts: 'paper', note: '设置页主题小样的纸面 —— 对应 `--k-paper`' },
  { scss: 'magic', ts: 'magic', note: '设置页主题小样的主色 —— 对应 `--k-magic`' },
  { scss: 'ok', ts: 'ok', note: '正确率环 ≥80% —— 对应 `--k-ok`' },
  { scss: 'gold', ts: 'gold', note: '正确率环 ≥60% —— 对应 `--k-gold`' },
  // ⚠️ 这里必须是 `bad` 而不是 `seal`。默认主题里两者同值（#a63a2e），所以换过来
  // 对默认主题逐位无变化；但青柠主题的 `seal` 是**品牌绿**（#70C000 被压深后）
  // —— 拿 seal 当「正确率低」那一档会画出一条**绿环**，读起来是「一切正常」。
  { scss: 'bad', ts: 'bad', note: '正确率环 <60% 与冒险日志进度条 —— 对应 `--k-bad`' },
  { scss: 'line-ring', ts: 'lineRing', note: '正确率环的轨道 —— 对应 `--k-line-ring`' }
]

// -----------------------------------------------------------------------------
// 产物一：_themes.scss
// -----------------------------------------------------------------------------

/** 渲染一个主题的 `--k-*` 块。值里若带 `//` 也只是字符串的一部分，不影响。 */
function renderThemeBlock(theme) {
  const rows = deriveTheme(theme)
  const width = Math.max(...rows.map((r) => r.css.length))
  const body = rows
    .map((r) => `  ${`${r.css}:`.padEnd(width + 1)} ${r.value};${' '.repeat(2)}// $${r.scss}`)
    .join('\n')
  return `.ui-theme--${theme.id} {\n${body}\n}`
}

function renderScss(themes) {
  const header = `// ⚠️ 生成物，请勿手改。
//
// 真源：shared/ui-themes.json（只写核心色）
// 配方：frontend/scripts/lib/ui-theme-recipe.mjs（派生其余令牌）
// 生成：frontend/scripts/gen_theme_scss.mjs
//
// 改色 → 改 JSON → \`npm run gen:theme\`。改完跑 \`npm run check:theme\`
// 验「体检达标 + 生成物最新」。
//
// 默认主题（paper）刻意不在这里：它的色值是 tokens.scss 里 var() 的兜底字面量，
// 切回默认主题靠摘掉 \`ui-theme--<id>\` 这个类，而不是套另一个类。
`
  const blocks = themes.map(renderThemeBlock).join('\n\n')
  const list = themes.map((t) => `${t.id}（${t.name}·${t.mode}）`).join('、')
  return `${header}// 共 ${themes.length} 套：${list}。每套 ${TOKENS.length} 个令牌。\n\n${blocks}\n`
}

// -----------------------------------------------------------------------------
// 产物二：ui-theme-tokens.ts
// -----------------------------------------------------------------------------

/** 取一套主题在某令牌上的**字面量**：新主题走配方，默认主题走 tokens.scss。 */
function valueOf(theme, scss, defaults) {
  if (theme.id === DEFAULT_THEME.id) {
    const value = defaults.get(scss)
    if (value === undefined) {
      throw new Error(`tokens.scss 里找不到 $${scss}（JS 侧需要它，见 JS_TOKENS）`)
    }
    return value
  }
  const row = deriveTheme(theme).find((r) => r.scss === scss)
  if (!row) throw new Error(`主题 ${theme.id} 缺少令牌 $${scss}`)
  return row.value
}

function renderTs(themes) {
  const defaults = readDefaultTokens()
  const all = [DEFAULT_THEME, ...themes]

  const metaRows = all
    .map((t) => `  ${t.id}: { name: '${t.name}', mode: '${t.mode}' }`)
    .join(',\n')

  const colorRows = all
    .map((t) => {
      const entries = JS_TOKENS.map((tok) => `${tok.ts}: '${valueOf(t, tok.scss, defaults)}'`)
      return `  ${t.id}: { ${entries.join(', ')} }`
    })
    .join(',\n')

  const interfaceRows = JS_TOKENS.map((tok) => `  /** ${tok.note} */\n  readonly ${tok.ts}: string`)
    .join('\n')

  return `// ⚠️ 生成物，请勿手改。
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
// 改色仍然是「改 JSON → \`npm run gen:theme\`」，然后跑 \`npm run check:theme\`。

/** 一套主题里 **JS 需要**的那几个颜色（不是全部 69 个令牌）。 */
export interface UiThemeColors {
${interfaceRows}
}

/** 主题元信息。\`id\` 同时是 CSS 类名的后缀：\`ui-theme--<id>\`。 */
export const UI_THEME_META = {
${metaRows}
} as const

/** 五套主题的标识。**这个联合类型也从真源生成** —— 加主题只改 JSON + 本脚本的 DEFAULT_THEME。 */
export type UiThemeId = keyof typeof UI_THEME_META

/** 所有主题的 id，顺序 = 设置页里的展示顺序（paper 在最前）。 */
export const UI_THEME_IDS = [${all.map((t) => `'${t.id}'`).join(', ')}] as ReadonlyArray<UiThemeId>

export const UI_THEME_COLORS: Record<UiThemeId, UiThemeColors> = {
${colorRows}
}
`
}

// -----------------------------------------------------------------------------
// 跑
// -----------------------------------------------------------------------------

const themes = loadThemes()
const outputs = [
  { file: OUT_SCSS, content: renderScss(themes), what: 'WXSS 令牌表' },
  { file: OUT_TS, content: renderTs(themes), what: 'JS 取色表' }
]
const checkOnly = process.argv.includes('--check')

if (checkOnly) {
  const stale = outputs.filter(({ file, content }) => {
    const current = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null
    return current !== content
  })
  if (stale.length === 0) {
    console.log(`生成物最新（${outputs.length} 份）：${themes.length} 套主题 × ${TOKENS.length} 个令牌`)
    process.exit(0)
  }
  for (const { file, what } of stale) {
    const exists = fs.existsSync(file)
    console.error(`生成物过期（${exists ? '内容与真源不一致' : '文件不存在'}）：${path.relative(REPO_ROOT, file)}（${what}）`)
  }
  console.error('请运行 `cd frontend && npm run gen:theme` 重新生成，并把结果一起提交。')
  process.exit(1)
}

for (const { file, content, what } of outputs) {
  fs.writeFileSync(file, content)
  console.log(`已写入 ${path.relative(REPO_ROOT, file)}（${what}）`)
}
console.log(`  ${themes.length} 套新主题 × ${TOKENS.length} 个令牌 = ${themes.length * TOKENS.length} 行自定义属性`)
console.log(`  JS 取色表：${themes.length + 1} 套（含默认主题）× ${JS_TOKENS.length} 个令牌 = ${(themes.length + 1) * JS_TOKENS.length} 条`)
console.log(`  真源：${path.relative(REPO_ROOT, THEMES_JSON)} + ${path.relative(REPO_ROOT, TOKENS_SCSS)}`)
