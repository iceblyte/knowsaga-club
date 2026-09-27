#!/usr/bin/env node
/**
 * 从 `shared/ui-themes.json` 生成 `frontend/src/styles/_themes.scss`。
 *
 * ## 产出什么
 *
 * 四套**非默认**主题各一个类选择器，里面是全部 `--k-*` 自定义属性：
 *
 * ```scss
 * .ui-theme--lime {
 *   --k-board: #f5f5f5;   // $board
 *   …
 * }
 * ```
 *
 * 挂载点（PhoneShell 根 + 自定义 tabBar 根）加上 `ui-theme--<id>` 这个类，
 * `var(--k-x, 兜底字面量)` 就整棵树改色。
 *
 * ## 为什么没有 `.ui-theme--paper`
 *
 * 默认主题的色值真源是 `tokens.scss` 里 `var()` 的**兜底字面量**（design.md D5）。
 * 如果再生成一份 `.ui-theme--paper { --k-board: #f1e8d0; … }`，同一批数字就有
 * 了两处实现 —— 改 tokens.scss 忘了改生成物，默认主题就会悄悄错位。
 * 所以切换到默认主题的做法是**摘掉类**，让兜底值接管；本文件不含 paper 块。
 *
 * ## 用法
 *
 * ```
 * cd frontend && npm run gen:theme     # 写盘
 * cd frontend && node scripts/gen_theme_scss.mjs --check   # 只校验是否最新
 * ```
 *
 * `--check` 供 `npm run check:theme` 调用：生成物与真源不一致就退出码 1，
 * 防止「改了 JSON 忘了重生成」被提交进仓库。
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { REPO_ROOT, THEMES_JSON, TOKENS, deriveTheme, loadThemes } from './lib/ui-theme-recipe.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')
const OUT_FILE = path.join(FRONTEND, 'src', 'styles', '_themes.scss')

/** 自定义属性的名字前缀 —— `ink2` → `--k-ink-2` 这种映射在配方里已写好。 */
const HEADER = `// ⚠️ 生成物，请勿手改。
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

/** 渲染一个主题的 `--k-*` 块。值里若带 `//` 也只是字符串的一部分，不影响。 */
function renderTheme(theme) {
  const rows = deriveTheme(theme)
  const width = Math.max(...rows.map((r) => r.css.length))
  const body = rows
    .map((r) => `  ${`${r.css}:`.padEnd(width + 1)} ${r.value};${' '.repeat(2)}// $${r.scss}`)
    .join('\n')
  return `.ui-theme--${theme.id} {\n${body}\n}`
}

function render(themes) {
  const blocks = themes.map(renderTheme).join('\n\n')
  const list = themes.map((t) => `${t.id}（${t.name}·${t.mode}）`).join('、')
  return `${HEADER}// 共 ${themes.length} 套：${list}。每套 ${TOKENS.length} 个令牌。\n\n${blocks}\n`
}

const themes = loadThemes()
const output = render(themes)
const checkOnly = process.argv.includes('--check')
const current = fs.existsSync(OUT_FILE) ? fs.readFileSync(OUT_FILE, 'utf8') : null

if (checkOnly) {
  if (current === output) {
    console.log(`生成物最新：${path.relative(REPO_ROOT, OUT_FILE)}（${themes.length} 套主题）`)
    process.exit(0)
  }
  const why = current === null ? '文件不存在' : '内容与真源不一致'
  console.error(`生成物过期（${why}）：${path.relative(REPO_ROOT, OUT_FILE)}`)
  console.error('请运行 `cd frontend && npm run gen:theme` 重新生成，并把结果一起提交。')
  process.exit(1)
}

fs.writeFileSync(OUT_FILE, output)
console.log(`已写入 ${path.relative(REPO_ROOT, OUT_FILE)}`)
console.log(`  ${themes.length} 套主题 × ${TOKENS.length} 个令牌 = ${themes.length * TOKENS.length} 行自定义属性`)
