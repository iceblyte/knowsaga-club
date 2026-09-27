#!/usr/bin/env node
/**
 * 标签栏图标（PNG 位图）与主题色的一致性校核。
 *
 * ## 为什么要有它
 *
 * 图标颜色**烘焙在像素里** —— CSS 变量够不到它，所以每套主题各有一套 PNG
 * （`assets/icons/png/<theme>/`）。这带来一个新的漂移面：
 *
 *     改了 shared/ui-themes.json → 重新生成 _themes.scss → **忘了重新生成 PNG**
 *
 * 这时 CSS 侧的标签栏底与文字已经是新色、图标还是旧色，而 `tsc`、双端构建、
 * 对比度体检**全都看不出来**（它们只读 scss / TS，不读 PNG）。本项目已经在
 * 「生成物或真源脱钩」上栽过三次（`$grain` 没包 `var()` → 别名掐断令牌 →
 * 体检表本身有盲区），所以把这条等式钉住：
 *
 *     PNG 里像素的 RGB  ==  该主题的 --k-ink-3（未选中）/ --k-magic-ink（选中）
 *
 * ## 取色来源（与 rasterize_tab_icons.py 完全同源，两处都不手抄）
 *
 *     paper       src/styles/tokens.scss 里 $ink3 / $magic-ink 的 var() 兜底字面量
 *     其余 4 套   src/styles/_themes.scss 的 --k-ink-3 / --k-magic-ink（生成物）
 *
 * ## 解码范围（够用即可，刻意不做通用 PNG 解码器）
 *
 * 只认 8bit RGBA（colorType 6）+ filter 0 —— 这正是
 * `frontend/scripts/rasterize_tab_icons.py` 写出来的格式。遇到别的格式
 * **直接报错**，不静默出结论：一个悄悄读错字节的校验器比没有校验器更糟。
 *
 * ## 用法
 *
 * ```
 * cd frontend && node scripts/check_icon_parity.mjs
 * cd frontend && node scripts/check_icon_parity.mjs --table   # 附逐张读数
 * ```
 *
 * 退出码：0 = 全部对上；1 = 缺文件 / 多文件 / 色值不符 / 解码不了。
 */

import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')
const SRC = path.join(FRONTEND, 'src')
const PNG_ROOT = path.join(SRC, 'assets', 'icons', 'png')
const TOKENS_SCSS = path.join(SRC, 'styles', 'tokens.scss')
const THEMES_SCSS = path.join(SRC, 'styles', '_themes.scss')
const THEMES_JSON = path.resolve(FRONTEND, '..', 'shared', 'ui-themes.json')

/** 图标尺寸（微信标签栏推荐值；改了这里也等于改了视觉规格，所以钉住）。 */
const ICON_SIZE = 81

/** `$ink3: var(--k-ink-3, #9a8870);` —— 只取有兜底字面量的写法。 */
const VAR_FALLBACK = /^\$([a-z0-9-]+)\s*:\s*var\(\s*--k-[a-z0-9-]+\s*,\s*(#[0-9a-fA-F]{6})\s*\)/gm
/** `--k-ink-3: #8f959f;`（主题块内，形状与 ui-theme-recipe 的渲染一致） */
const VAR_DECL = /--k-([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})/g
const THEME_BLOCK = /\.ui-theme--([a-z0-9-]+)\s*\{([^}]*)\}/g

function readDefaultTokens() {
  const out = new Map()
  for (const m of fs.readFileSync(TOKENS_SCSS, 'utf8').matchAll(VAR_FALLBACK)) {
    out.set(m[1], m[2].toLowerCase())
  }
  return out
}

function readThemeBlocks() {
  const out = new Map()
  for (const m of fs.readFileSync(THEMES_SCSS, 'utf8').matchAll(THEME_BLOCK)) {
    const vars = new Map()
    for (const v of m[2].matchAll(VAR_DECL)) vars.set(v[1], v[2].toLowerCase())
    out.set(m[1], vars)
  }
  return out
}

/** 校验用的一组失败（不在遇到第一个就退出 —— 一次列全才方便一次改完）。 */
const failures = []

function expect(condition, message) {
  if (!condition) failures.push(message)
  return condition
}

/**
 * 解出 PNG 里每个 alpha > 0 的像素的 RGB（→ 计数）。
 *
 * 透明像素的颜色没有意义，跳过；**半透明边缘要算进来** —— 我们的生成器
 * 对所有像素写同一个 RGB、只改 alpha，所以边缘也应当是目标色。若某一层
 * 边缘是别的颜色，说明这套 PNG 不是用当前配方生成的。
 */
function readIconColors(file) {
  const buf = fs.readFileSync(file)
  if (buf.length < 8 || buf.readUInt32BE(0) !== 0x89504e47) {
    throw new Error('不是 PNG（签名不匹配）')
  }

  let width = 0
  let height = 0
  let bitDepth = 0
  let colorType = 0
  const idat = []
  let off = 8
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off)
    const tag = buf.toString('ascii', off + 4, off + 8)
    const data = buf.subarray(off + 8, off + 8 + len)
    if (tag === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      bitDepth = data[8]
      colorType = data[9]
    } else if (tag === 'IDAT') {
      idat.push(data)
    } else if (tag === 'IEND') {
      break
    }
    off += 12 + len
  }

  if (bitDepth !== 8 || colorType !== 6) {
    throw new Error(`只支持 8bit RGBA，收到 bitDepth=${bitDepth} colorType=${colorType}`)
  }
  if (width !== ICON_SIZE || height !== ICON_SIZE) {
    throw new Error(`尺寸应为 ${ICON_SIZE}×${ICON_SIZE}，实际 ${width}×${height}`)
  }

  const raw = zlib.inflateSync(Buffer.concat(idat))
  const stride = width * 4
  const colors = new Map()
  for (let y = 0; y < height; y++) {
    const at = y * (stride + 1)
    const filter = raw[at]
    if (filter !== 0) {
      throw new Error(
        `只实现了 filter 0，遇到 filter ${filter} —— 换工具重新生成过图标？` +
          '请先补实现（见文件头「解码范围」），不要绕过这条校核。'
      )
    }
    const row = raw.subarray(at + 1, at + 1 + stride)
    for (let i = 0; i < row.length; i += 4) {
      if (row[i + 3] === 0) continue
      const hex = `#${row.subarray(i, i + 3).toString('hex')}`
      colors.set(hex, (colors.get(hex) ?? 0) + 1)
    }
  }
  return colors
}

// -----------------------------------------------------------------------------
// 期望色（读真源）
// -----------------------------------------------------------------------------

const tokens = readDefaultTokens()
const blocks = readThemeBlocks()

const themes = (() => {
  const list = []
  const normal = tokens.get('ink3')
  const active = tokens.get('magic-ink')
  if (!normal || !active) {
    console.error('tokens.scss 里找不到 $ink3 / $magic-ink 的 var() 兜底字面量。')
    process.exit(1)
  }
  list.push({ id: 'paper', name: '纸与印', normal, active, from: 'tokens.scss' })

  const json = JSON.parse(fs.readFileSync(THEMES_JSON, 'utf8'))
  for (const t of json.themes) {
    const vars = blocks.get(t.id)
    if (!vars) {
      console.error(`_themes.scss 里没有 .ui-theme--${t.id} 块（先跑 npm run gen:theme）。`)
      process.exit(1)
    }
    const n = vars.get('ink-3')
    const a = vars.get('magic-ink')
    if (!n || !a) {
      console.error(`主题 ${t.id} 的块里缺 --k-ink-3 / --k-magic-ink，无法核对图标色。`)
      process.exit(1)
    }
    list.push({ id: t.id, name: t.name, normal: n, active: a, from: '_themes.scss' })
  }
  return list
})()

// -----------------------------------------------------------------------------
// 逐个主题核对
// -----------------------------------------------------------------------------

const dirOf = (id) => path.join(PNG_ROOT, id)
const pngNames = (id) => {
  const dir = dirOf(id)
  if (!fs.existsSync(dir)) return null
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.png'))
    .sort()
}

const reference = pngNames('paper')
if (!reference || reference.length === 0) {
  console.error(`找不到基准图标目录：${dirOf('paper')}`)
  process.exit(1)
}

const showTable = process.argv.includes('--table')
let checked = 0

for (const theme of themes) {
  const names = pngNames(theme.id)
  if (!expect(names !== null, `${theme.id}：目录不存在（${path.relative(FRONTEND, dirOf(theme.id))}）`)) {
    continue
  }
  if (
    !expect(
      names.length === reference.length,
      `${theme.id}：PNG 数量 ${names.length}，预期 ${reference.length}（与 paper 对齐）`
    )
  ) {
    continue
  }
  for (const expectedMissing of reference.filter((n) => !names.includes(n))) {
    failures.push(`${theme.id}：缺少 ${expectedMissing}`)
  }

  for (const name of names) {
    const file = path.join(dirOf(theme.id), name)
    const isActive = name.endsWith('-active.png')
    const isNormal = name.endsWith('-normal.png')
    if (!isActive && !isNormal) {
      failures.push(`${theme.id}/${name}：文件名既不以 -normal 也不以 -active 结尾`)
      continue
    }
    const expected = (isActive ? theme.active : theme.normal).toLowerCase()

    let colors
    try {
      colors = readIconColors(file)
    } catch (err) {
      failures.push(`${theme.id}/${name}：${err.message}`)
      continue
    }
    if (colors.size === 0) {
      failures.push(`${theme.id}/${name}：整张图都是透明的（没有可核对的不透明像素）`)
      continue
    }

    checked += 1
    const wrong = [...colors.keys()].filter((c) => c !== expected)
    if (wrong.length > 0) {
      failures.push(
        `${theme.id}/${name}：像素色 ${wrong.join(' / ')}，预期 ${expected}` +
          `（该主题 --k-ink-3=${theme.normal} / --k-magic-ink=${theme.active}）` +
          ' ⇒ 改了主题色但没重新生成图标？跑 `python frontend/scripts/rasterize_tab_icons.py`'
      )
      continue
    }

    if (showTable) {
      const pixels = [...colors.values()].reduce((a, b) => a + b, 0)
      console.log(
        `  ✓ ${theme.id.padEnd(10)} ${name.padEnd(22)} ${expected}  不透明像素 ${pixels}`
      )
    }
  }
}

// -----------------------------------------------------------------------------
// 汇总
// -----------------------------------------------------------------------------

console.log('标签栏图标 ↔ 主题色 一致性校核')
console.log(`  图标目录：${path.relative(FRONTEND, PNG_ROOT).replace(/\\/g, '/')}/<theme>/`)
console.log(`  期望色来源：tokens.scss（paper）+ _themes.scss（其余 ${themes.length - 1} 套）`)
for (const t of themes) {
  console.log(
    `    ${t.id.padEnd(10)} ${t.name.padEnd(8)} 未选中 ${t.normal}  选中 ${t.active}   ← ${t.from}`
  )
}
console.log(`  核对 ${themes.length} 套 × ${reference.length / 2} 个图标 × 2 个状态 = ${checked} 张`)
console.log('')

if (failures.length > 0) {
  console.error(`图标与主题色不一致，${failures.length} 处：`)
  for (const line of failures) console.error(`  ! ${line}`)
  console.error('')
  console.error('图标是生成物；真源是 shared/ui-themes.json（+ tokens.scss）。')
  process.exit(1)
}

console.log(`一致：${checked} 张图标的像素色都与各自主题的令牌相符。`)
