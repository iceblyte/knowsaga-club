#!/usr/bin/env node
/**
 * 五套 UI 主题的 WCAG 体检。
 *
 * ## 它回答什么问题
 *
 * `add-ui-theme-switch` 的规格里有一条：**每套主题的文字必须保持可读**。
 * 这条不能靠「看着还行」——设计实验室的第三轮就吃过亏：语义色算到
 * 4.50 就收工，8bit 量化之后翻到不达标。所以这里把**判定发生在合成后的
 * 不透明色上**，并且要求留出余量（正文 4.5 + 0.12）。
 *
 * ## 默认主题也要进来
 *
 * `paper` 的色值不在这套配色里（见 design.md D5），它是 `tokens.scss` 里的
 * 字面量。但体检必须把它一起算：一是要证明「新主题的取值没有比现状更差」，
 * 二是默认主题里**本来就有几处低于 AA**（三级墨 3.34:1、`$gold-d` 4.40:1、
 * 金底按钮上的字 3.96:1），把它们显式登记出来，比假装不存在要好 ——
 * 规格里写的是「新主题必须达标」，不是「五套全部达标」。
 *
 * ## 用法
 *
 * ```
 * cd frontend && npm run check:theme      # 体检 + 生成物一致性
 * cd frontend && node scripts/audit_theme_contrast.mjs --table   # 附完整派生表
 * ```
 *
 * 退出码：0 = 新主题全部达标；1 = 有新增不达标项（会逐条列出）。
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  REPO_ROOT,
  TOKENS,
  composite,
  contrast,
  deriveTheme,
  loadThemes,
  parseColor
} from './lib/ui-theme-recipe.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')

/** 正文门槛 + 余量；余量防「刚好压线」在量化后翻红。 */
const TEXT_TARGET = 4.5
const TEXT_MARGIN = 0.12
/** 大字与「非文本」门槛（交互控件的边界、状态色）。 */
const UI_TARGET = 3.0
const UI_MARGIN = 0.1

/**
 * 默认主题（`paper`）的色值 —— 逐字取自 `frontend/src/styles/tokens.scss`。
 *
 * ⚠️ 这里是**手抄**的，也就意味着它可能与 tokens.scss 漂移。所以下面有一条
 * `assertDefaultMatchesSource()` 直接去读 tokens.scss 核对，抄错了会当场失败。
 */
const PAPER_TOKENS = {
  board: '#f1e8d0',
  paper: '#fefcf6',
  paper2: '#f5edd8',
  paper3: '#eadfc4',
  'paper-plain': '#fffdf6',
  line: '#c9b48d',
  ink: '#2a2018',
  ink2: '#6b5a45',
  ink3: '#9a8870',
  seal: '#a63a2e',
  magic: '#2f6bd8',
  // 默认主题里 `$magic-ink` 就是 `$magic`（中间调，填充与文字都能当），
  // 所以这里与上面同值 —— 拆出这个令牌是为了浅色品牌（青柠）。
  'magic-ink': '#2f6bd8',
  'magic-d': '#1f4694',
  gold: '#c8912a',
  'gold-d': '#9c6e15',
  ok: '#2f7d4f',
  bad: '#a63a2e',
  rare: '#6d4bc4',
  'on-magic': '#fff9ea',
  // 默认主题里 `$on-ok` / `$on-bad` 也是 `$on-magic`（深绿/深红块上都读得清）。
  'on-ok': '#fff9ea',
  'on-bad': '#fff9ea',
  'on-gold': '#3d2a05',
  'btn-ok-edge': '#1f5a38',
  'btn-dis-edge': '#d3c29f',
  // 下面五个在 tokens.scss 里是**别名**（`$btn-magic-edge: $magic-d`），
  // 不是字面量 —— 这里写它们解析后的值（别名关系由 SCSS 自己维护）。
  'btn-magic-edge': '#1f4694',
  'btn-gold-edge': '#9c6e15',
  'opt-sel-border': '#2f6bd8',
  'opt-ok-border': '#2f7d4f',
  'opt-bad-border': '#a63a2e',
  'paper-blue': '#e7effb',
  'paper-ok': '#e6f2e9',
  'paper-bad': '#f8e9e6',
  'paper-gold': '#f8efd6',
  'paper-rare': '#ede8fa',
  'opt-selected': '#dce9fb',
  'opt-correct': '#dff0e4',
  'opt-wrong': '#f7e3df',
  'chip-sel-border': '#7fa9d8',
  'stroke-knob': 'rgba(150,120,72,0.3)',
  'stroke-knob-strong': 'rgba(150,120,72,0.34)',
  'stroke-edge': 'rgba(120,92,48,0.36)',
  'stroke-line-dash': 'rgba(150,120,72,0.45)',
  'stroke-ghost': 'rgba(150,120,72,0.38)',
  mask: 'rgba(42,32,24,0.44)',
  'hi-inset': 'rgba(255,255,255,0.7)',
  'edge-magic-32': 'rgba(47,107,216,0.32)',
  'edge-magic-34': 'rgba(47,107,216,0.34)',
  'edge-magic-42': 'rgba(47,107,216,0.42)',
  'edge-ok-34': 'rgba(47,125,79,0.34)',
  'edge-bad-34': 'rgba(166,58,46,0.34)',
  'edge-gold-36': 'rgba(200,145,42,0.36)',
  'edge-gold-42': 'rgba(200,145,42,0.42)',
  'edge-gold-50': 'rgba(200,145,42,0.5)',
  'edge-rare-32': 'rgba(109,75,196,0.32)',
  'edge-rare-36': 'rgba(109,75,196,0.36)',
  'edge-rare-44': 'rgba(109,75,196,0.44)',
  'stroke-32': 'rgba(150,120,72,0.32)',
  'stroke-dash-44': 'rgba(150,120,72,0.44)',
  'stroke-dash-52': 'rgba(150,120,72,0.52)',
  'shadow-slip': 'rgba(120,92,48,0.2)',
  'shadow-sheet': 'rgba(120,92,48,0.18)',
  rod: '#e8d2a0',
  'rod-edge': '#c4a874',
  'grad-hi': 'rgba(255,255,255,0.55)',
  'grad-lo': 'rgba(120,88,38,0.1)',
  'line-ring': '#e6d6b4',
  'bar-past': '#b9d5f2',
  'glow-gold': 'rgba(200,145,42,0.12)',
  'grain': null // 数据 URI，不参与颜色体检
}

/**
 * 体检项。
 *
 * `target` 为 `TEXT`（4.5，正文/小字）或 `UI`（3.0，大字、非文本边界与状态色）。
 * `since` 标出这个组合在默认主题里本来就低于门槛 —— 新增主题不允许出现这
 * 一类；默认主题上的这些项只登记、不判红。
 */
const CHECKS = [
  // ---- 正文与标题 ----
  { label: '正文墨 on 纸面', fg: 'ink', bg: 'paper', target: 'TEXT' },
  { label: '正文墨 on 板色', fg: 'ink', bg: 'board', target: 'TEXT' },
  { label: '正文墨 on 次级纸面', fg: 'ink', bg: 'paper2', target: 'TEXT' },
  { label: '次级墨 on 纸面', fg: 'ink2', bg: 'paper', target: 'TEXT' },
  { label: '次级墨 on 次级纸面', fg: 'ink2', bg: 'paper2', target: 'TEXT' },
  { label: '三级墨（11px 辅助） on 纸面', fg: 'ink3', bg: 'paper', target: 'TEXT' },
  { label: '三级墨（11px 辅助） on 板色', fg: 'ink3', bg: 'board', target: 'TEXT' },

  // ---- 语义色当文字 ----
  // `.c-blue` 在 base.scss 里用 `$magic-ink`（当文字的那一份主色），不是
  // 当填充用的 `$magic` —— 浅色品牌这两者必须分开，见 ui-theme-recipe.mjs 文件头。
  { label: '.c-blue 主色文字 on 纸面', fg: 'magic-ink', bg: 'paper', target: 'TEXT' },
  { label: '.c-ok 正确色文字 on 纸面', fg: 'ok', bg: 'paper', target: 'TEXT' },
  { label: '.c-bad 错误色文字 on 纸面', fg: 'bad', bg: 'paper', target: 'TEXT' },
  { label: '.c-gold 黄铜深文字 on 纸面', fg: 'gold-d', bg: 'paper', target: 'TEXT' },
  { label: '.c-rare 稀有文字 on 纸面', fg: 'rare', bg: 'paper', target: 'TEXT' },
  { label: '.stamp 印章色 on 纸面', fg: 'seal', bg: 'paper', target: 'TEXT' },

  // ---- 反白（实心控件上的字）----
  { label: '.btn 主按钮文字 on 主色', fg: 'on-magic', bg: 'magic', target: 'TEXT' },
  { label: '.btn.gold 文字 on 黄铜', fg: 'on-gold', bg: 'gold', target: 'TEXT' },
  { label: '.chip.on 文字 on 已选底', fg: 'magic-d', bg: 'opt-selected', target: 'TEXT' },
  { label: '.pill.solid 文字 on 主色', fg: 'on-magic', bg: 'magic', target: 'TEXT' },

  // ---- 淡底胶囊：淡底 + 同色深字 ----
  { label: '.pill.blue 文字 on 主色淡底', fg: 'magic-d', bg: 'paper-blue', target: 'TEXT' },
  { label: '.pill.ok 文字 on 正确色淡底', fg: 'ok', bg: 'paper-ok', target: 'TEXT' },
  { label: '.pill.bad 文字 on 错误色淡底', fg: 'bad', bg: 'paper-bad', target: 'TEXT' },
  { label: '.pill.gold 文字 on 黄铜淡底', fg: 'gold-d', bg: 'paper-gold', target: 'TEXT' },
  { label: '.pill.rare 文字 on 稀有淡底', fg: 'rare', bg: 'paper-rare', target: 'TEXT' },

  // ---- 答题选项 ----
  { label: '选项四态文字 on 选项底', fg: 'ink', bg: 'opt-selected', target: 'TEXT' },
  { label: '选项正确态文字 on 正确底', fg: 'ink', bg: 'opt-correct', target: 'TEXT' },
  { label: '选项错误态文字 on 错误底', fg: 'ink', bg: 'opt-wrong', target: 'TEXT' },
  { label: '答对题号字 on 正确色', fg: 'on-ok', bg: 'ok', target: 'TEXT' },
  { label: '答错题号字 on 错误色', fg: 'on-bad', bg: 'bad', target: 'TEXT' },

  // ---- 非文本：状态描边与交互边界（3:1）----
  { label: '主色描边 on 已选底', fg: 'opt-sel-border', bg: 'opt-selected', target: 'UI' },
  { label: '正确色描边 on 正确底', fg: 'opt-ok-border', bg: 'opt-correct', target: 'UI' },
  { label: '错误色描边 on 错误底', fg: 'opt-bad-border', bg: 'opt-wrong', target: 'UI' },
  { label: '已选 chip 描边 on 已选底', fg: 'chip-sel-border', bg: 'opt-selected', target: 'UI' },
  { label: '次级按钮/表单边界 on 纸面', fg: 'stroke-ghost', bg: 'paper', target: 'UI' },
  { label: '禁用按钮文字 on 禁用底（豁免项）', fg: 'ink3', bg: 'paper3', target: 'UI', exempt: 'WCAG 1.4.3 豁免「无效控件」' }
]

/** `$name: 值;`（允许行尾 `//` 注释）。 */
const SCSS_DECL = /^\$([a-z0-9-]+):\s*(.+?);\s*(?:\/\/.*)?$/
/** `var(--k-x, 兜底字面量)` —— 只认单个兜底值那种写法。 */
const SCSS_VAR_FALLBACK = /^var\(\s*--k-[a-z0-9-]+\s*,\s*(.+?)\s*\)$/
const COLOR_LITERAL = /^(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))$/

/**
 * 从一行 `$x: …;` 里取出它**实际生效的颜色字面量**。
 *
 * 主题化之后 tokens.scss 会变成 `$board: var(--k-board, #f1e8d0);` ——
 * 兜底字面量就是默认主题真正渲染的值，所以要把 `var(...)` 拆开再比对。
 * 别名（`$btn-magic-edge: $magic-d;`）与函数值（`$grain: url(…)`）返回 null。
 */
function declaredColor(line) {
  const m = line.match(SCSS_DECL)
  if (!m) return null
  let value = m[2].trim()
  const wrapped = value.match(SCSS_VAR_FALLBACK)
  if (wrapped) value = wrapped[1].trim()
  if (!COLOR_LITERAL.test(value)) return null
  return { name: m[1], value: value.replace(/\s+/g, '') }
}

/**
 * 核对上面那份手抄的默认主题色值与 `tokens.scss` 一致。
 *
 * 只核「能机械比对」的那些：别名（`$opt-default: $paper2`）、函数值（`rpx()`、
 * `url()`）与 `var()` 里没有兜底字面量的行都跳过 —— 它们不是颜色字面量。
 */
function assertDefaultMatchesSource() {
  const source = fs.readFileSync(
    path.join(FRONTEND, 'src', 'styles', 'tokens.scss'),
    'utf8'
  )
  const found = new Map()
  for (const line of source.split('\n')) {
    const decl = declaredColor(line)
    if (decl) found.set(decl.name, decl.value)
  }

  const mismatches = []
  for (const [key, expected] of Object.entries(PAPER_TOKENS)) {
    if (expected === null) continue
    const actual = found.get(key)
    if (actual === undefined) {
      // tokens.scss 里的令牌名与 css 变量名不同（paper2 / ink2 / magic-d …），
      // 这里只在「名字恰好存在但值不同」时报错，缺失交给下一条断言处理。
      continue
    }
    const norm = (s) => String(s).toLowerCase().replace(/\s+/g, '').replace(/0\./g, '.')
    if (norm(actual) !== norm(expected)) {
      mismatches.push(`${key}：tokens.scss=${actual} 本文件=${expected}`)
    }
  }
  if (mismatches.length > 0) {
    console.error('体检脚本里手抄的默认主题色值与 tokens.scss 不一致：')
    for (const line of mismatches) console.error(`  ! ${line}`)
    console.error('请先对齐（默认主题的真源就是 tokens.scss，不是本文件）。')
    process.exit(1)
  }

  return found.size
}

/**
 * 把 `frontend/src` 下全部 `.scss` 里的颜色字面量收成一个集合。
 *
 * 用途：上面那份手抄表里有一多半的令牌**不在 tokens.scss 里**
 * （它们是 `base.scss` 与各页面 scss 里的硬编码色，本次才被起名）。
 * 那些名字没法按名字核对，就按**值**核对 —— 只要这个值在源码里真实存在，
 * 手抄时抄错一位就会当场失败。
 */
function collectSourceColorLiterals() {
  const files = []
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.scss')) files.push(full)
    }
  }
  walk(path.join(FRONTEND, 'src'))

  const literals = new Set()
  const re = /#[0-9a-fA-F]{6}\b|rgba?\([^)]*\)/g
  for (const file of files) {
    for (const m of fs.readFileSync(file, 'utf8').matchAll(re)) {
      literals.add(normalizeLiteral(m[0]))
    }
  }
  return { literals, fileCount: files.length }
}

/** 归一化：去掉空白、小写、`0.34` → `.34`。两边都这么处理才能逐字比对。 */
function normalizeLiteral(text) {
  return String(text)
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/(^|[^\d])0\./g, '$1.')
}

/**
 * 断言：手抄表里每一个「非别名」的值都能在源码里找到同名/同值的字面量。
 *
 * 别名（`opt-sel-border` 这类）跳过 —— 它们的值由被指向的令牌决定。
 */
function assertValuesExistInSource() {
  const { literals, fileCount } = collectSourceColorLiterals()
  const aliases = new Set(['btn-magic-edge', 'btn-gold-edge', 'opt-sel-border', 'opt-ok-border', 'opt-bad-border'])

  const missing = []
  for (const [key, value] of Object.entries(PAPER_TOKENS)) {
    if (value === null || aliases.has(key)) continue
    // `magic` 与 `bad`/`seal` 之类同值不同名是正常的，这里只要求
    // 「这个值在源码里确实出现过」—— 抄错一位就找不到。
    if (!literals.has(normalizeLiteral(value))) {
      missing.push(`${key} = ${value}`)
    }
  }
  return { missing, fileCount, literalCount: literals.size }
}

// -----------------------------------------------------------------------------
// 跑
// -----------------------------------------------------------------------------

const tokensInSource = assertDefaultMatchesSource()
const sourceValues = assertValuesExistInSource()
if (sourceValues.missing.length > 0) {
  console.error('体检脚本里的默认主题色值在源码里找不到对应字面量（疑似抄错）：')
  for (const line of sourceValues.missing) console.error(`  ! ${line}`)
  console.error('默认主题的真源是 frontend/src 下的 scss，不是本文件。')
  process.exit(1)
}

const themes = loadThemes()
const all = [
  { id: 'paper', name: '纸与印', mode: 'light', isDefault: true },
  ...themes.map((t) => ({ id: t.id, name: t.name, mode: t.mode, isDefault: false }))
]

const tables = new Map()
tables.set('paper', TOKENS.filter((t) => t.scss !== 'grain').map((t) => ({
  scss: t.scss,
  css: t.css,
  value: PAPER_TOKENS[t.scss]
})))
for (const t of themes) {
  tables.set(t.id, deriveTheme(t).filter((row) => row.scss !== 'grain'))
}

const failures = []
const preExisting = []
let checked = 0

console.log(`主题真源：${path.join(REPO_ROOT, 'shared', 'ui-themes.json')}`)
console.log(`默认主题：${path.join(FRONTEND, 'src', 'styles', 'tokens.scss')}（已核对 ${tokensInSource} 条字面量）`)
console.log(`默认主题色值反查：${sourceValues.fileCount} 个 scss / ${sourceValues.literalCount} 个字面量，全部命中`)
console.log(`主题套数：${all.length}（默认 1 + 新增 ${themes.length}）`)
console.log('')

for (const theme of all) {
  const table = tables.get(theme.id)
  const get = (scss) => {
    const row = table.find((r) => r.scss === scss)
    if (!row) throw new Error(`主题 ${theme.id} 缺少令牌 ${scss}`)
    return row.value
  }
  /**
   * 把带透明度的值合成到纸色上，得到一个不透明色。
   *
   * 关键一步：对比度必须在**合成后**的颜色上算。半透明色直接拿去算，
   * 得到的是「同一种颜色」的对比度，而不是用户真正看到的那一层 ——
   * 例如 `rgba(150,120,72,.3)` 的亮度与它压在纸上的结果差了将近一倍。
   */
  const solidOf = (value) => {
    const p = parseColor(value)
    return p.a >= 1 ? p : composite(p, get('paper'))
  }

  const lines = []
  for (const check of CHECKS) {
    const target = check.target === 'TEXT' ? TEXT_TARGET : UI_TARGET
    const margin = check.target === 'TEXT' ? TEXT_MARGIN : UI_MARGIN
    const bg = get(check.bg)
    const fg = get(check.fg)
    const bgSolid = solidOf(bg)
    const ratio = contrast(solidOf(composite(fg, bgSolid)), bgSolid)
    checked += 1

    // 1e-9 只吃浮点误差 —— 求解器保证量化后 ≥ want，两边算法必须一致。
    const pass = ratio >= target + margin - 1e-9
    const label = `${check.label}`
    const detail = `${ratio.toFixed(2)}:1（门槛 ${target}${margin ? ` + ${margin}` : ''}）`

    if (check.exempt) {
      lines.push(`  · 豁免 ${label} — ${detail}｜${check.exempt}`)
      continue
    }
    if (pass) {
      lines.push(`  ✓ ${label} — ${detail}`)
    } else if (theme.isDefault) {
      preExisting.push(`[${theme.id}] ${label} — ${detail}`)
      lines.push(`  △ 既有 ${label} — ${detail}`)
    } else {
      failures.push(`[${theme.id}] ${label} — ${detail}`)
      lines.push(`  ✗ ${label} — ${detail}`)
    }
  }

  console.log(`── ${theme.id} ${theme.name}（${theme.mode}）${theme.isDefault ? ' · 默认' : ''}`)
  for (const line of lines) console.log(line)
  console.log('')
}

if (process.argv.includes('--table')) {
  console.log('='.repeat(78))
  console.log('完整派生表')
  console.log('='.repeat(78))
  for (const theme of all) {
    console.log(`\n── ${theme.id} ${theme.name}`)
    for (const row of tables.get(theme.id)) {
      const actual = theme.isDefault ? PAPER_TOKENS[row.scss] : row.value
      console.log(`  $${row.scss.padEnd(22)} ${row.css.padEnd(24)} ${actual}`)
    }
  }
}

console.log('='.repeat(78))
console.log(`断言 ${checked} 项 · ${all.length} 套主题`)
console.log(`令牌数：每套 ${TOKENS.length}（其中 ${TOKENS.filter((t) => t.scss === 'grain').length} 条为数据 URI，不参与对比度）`)

if (preExisting.length > 0) {
  console.log('')
  console.log(`默认主题（paper）里低于 AA 的既有项 ${preExisting.length} 条 —— 本次不改（改了就破坏零漂移），如实登记：`)
  for (const line of preExisting) console.log(`  △ ${line}`)
}

if (failures.length > 0) {
  console.error('')
  console.error(`新增主题里发现 ${failures.length} 处不达标：`)
  for (const line of failures) console.error(`  ! ${line}`)
  console.error('')
  console.error('请调整 shared/ui-themes.json 的核心色，或在 lib/ui-theme-recipe.mjs 里收紧张量。')
  process.exit(1)
}

console.log('')
console.log(`达标：新增 ${themes.length} 套主题的语义色对全部满足门槛并留有余量。`)
