/**
 * UI 主题配方 —— 从 `shared/ui-themes.json` 的「核心色」推出全部 `--k-*` 令牌。
 *
 * ## 为什么要有这一层
 *
 * 换肤要把颜色来源从「编译期字面量」搬成「运行时可变的 CSS 自定义属性」，
 * 于是 `tokens.scss` / `base.scss` 里每一个**具体的颜色**都必须有名字。
 * 那些颜色里绝大多数不是随手挑的，而是「某个语义色 + 一个透明度」
 * （例如 `.card.blue` 的描边 = 主色 32%）。如果把 60 多个值逐个手抄进
 * JSON，四个主题就是 250 多个手抄数字，改一处基准色要记得连带改十几处 ——
 * 这正是本项目在算分上吃过亏的「同一口径两处实现」。
 *
 * 所以：**JSON 只写核心色（每套 17 个），其余全部按本文件的配方算**。
 * 配方是唯一的实现，生成器与体检都 import 它。
 *
 * ## 配方原则
 *
 * 1. **淡底 = 语义色按固定透明度压在纸色上**。CSS 里允许半透明底，但
 *    同一个 `paper-blue` 会落在纸面、卡片、板色三种父底上，半透明会因为父底
 *    不同而变色；而默认主题里这些值是**不透明**的。所以统一合成为不透明色。
 * 2. **中性描边 = 一个基准色 × 一个强度缩放**。默认主题用
 *    `rgba(150,120,72, α)` 这一族暖褐色，α 从 0.30 到 0.52 分了七档；
 *    新主题沿用「同一个基准色 + 同样的相对档位」，只把整体强度缩到
 *    设计实验室的观感。这样描边的**层次关系**不变，只是密度变了。
 * 3. **当文字用的颜色一律「求解」**，不当文字用的（填充、装饰线）原样取自 JSON。
 *
 * ## ⚠️ 为什么要区分「填充」与「文字」两套主色
 *
 * 默认主题的 `$magic`（#2f6bd8）既能当按钮底色（上面压浅字 4.7:1），
 * 又能直接当文字（写在纸上 4.9:1）—— 因为它是个中间调。**浅色的品牌色做不到
 * 这件事**：文字要够暗才读得清，底色要够亮才压得住白字，两者在同一个值上
 * 不可能同时成立（青柠的 #70C000 当文字只有 2.28:1）。设计实验室第三轮的
 * 做法是拆成 `--brand`（填充）与 `--brand-ink`（当文字）两个令牌 ——
 * 本文件沿用这个结论，对应 `$magic` 与 `$magic-ink`。
 * 默认主题里 `magic-ink` 就等于 `magic`，所以拆出来**不产生任何视觉变化**。
 *
 * ## 求解发生在「背景」这一侧
 *
 * 一个颜色可能同时出现在纸面、次级纸面、板色、以及自己的淡底上（`.pill.ok`
 * 就是「正确色文字压在正确色淡底上」）。所以求解不是对着单一背景算，
 * 而是 `solveAgainstAll`：把每个背景允许的亮度上（下）界都算出来取最紧的那个。
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// -----------------------------------------------------------------------------
// 颜色工具
// -----------------------------------------------------------------------------

/**
 * 把 `#rgb` / `#rrggbb` / `rgb()` / `rgba()` 解析成 `{ r, g, b, a }`（0–255 / 0–1）。
 *
 * 已经解析过的对象原样返回 —— 内部函数之间会互相传递颜色对象。
 */
export function parseColor(input) {
  if (input && typeof input === 'object' && 'r' in input && 'g' in input && 'b' in input) {
    return { r: input.r, g: input.g, b: input.b, a: input.a === undefined ? 1 : input.a }
  }
  const text = String(input).trim()

  const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hex) {
    const h = hex[1]
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
    return {
      r: parseInt(full.slice(0, 2), 16),
      g: parseInt(full.slice(2, 4), 16),
      b: parseInt(full.slice(4, 6), 16),
      a: 1
    }
  }

  const fn = text.match(/^rgba?\(([^)]+)\)$/i)
  if (fn) {
    const parts = fn[1].split(',').map((p) => p.trim())
    return {
      r: Number(parts[0]),
      g: Number(parts[1]),
      b: Number(parts[2]),
      a: parts.length > 3 ? Number(parts[3]) : 1
    }
  }

  throw new Error(`无法解析颜色：${input}`)
}

const clamp255 = (n) => Math.max(0, Math.min(255, Math.round(n)))

/** 输出 `#rrggbb`（丢弃透明度）。 */
export function toHex(color) {
  const { r, g, b } = color
  return `#${[r, g, b].map((v) => clamp255(v).toString(16).padStart(2, '0')).join('')}`
}

/** 输出 `rgba(r, g, b, a)`，a 保留 3 位小数。 */
export function toRgba(color) {
  const a = Math.round(color.a * 1000) / 1000
  return `rgba(${clamp255(color.r)}, ${clamp255(color.g)}, ${clamp255(color.b)}, ${a})`
}

/** 小写 hex；若带透明度则输出 rgba()。用于生成物里的最终字面量。 */
export function formatColor(color) {
  const p = parseColor(color)
  return p.a >= 1 ? toHex(p) : toRgba(p)
}

/** `rgba(color, alpha)` —— 只换透明度，不动色相。 */
export function withAlpha(c, alpha) {
  const p = parseColor(c)
  return { r: p.r, g: p.g, b: p.b, a: alpha }
}

/**
 * 把 `fg`（可带自身透明度）压在 `bg`（必须不透明）上，得到不透明的合成色。
 * 这就是 CSS 里半透明色真正呈现出来的样子。
 */
export function composite(fg, bg) {
  const f = parseColor(fg)
  const b = parseColor(bg)
  return {
    r: f.r * f.a + b.r * (1 - f.a),
    g: f.g * f.a + b.g * (1 - f.a),
    b: f.b * f.a + b.b * (1 - f.a),
    a: 1
  }
}

/** 线性插值：t=0 得 a，t=1 得 b。 */
export function mix(a, b, t) {
  const x = parseColor(a)
  const y = parseColor(b)
  return {
    r: x.r + (y.r - x.r) * t,
    g: x.g + (y.g - x.g) * t,
    b: x.b + (y.b - x.b) * t,
    a: x.a + (y.a - x.a) * t
  }
}

const srgbToLinear = (v) => {
  const c = v / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

/** WCAG 相对亮度。 */
export function luminance(c) {
  const p = parseColor(c)
  return (
    0.2126 * srgbToLinear(p.r) + 0.7152 * srgbToLinear(p.g) + 0.0722 * srgbToLinear(p.b)
  )
}

/**
 * WCAG 对比度。
 *
 * ⚠️ 判定必须在**合成后**的颜色上做：半透明色直接拿去算，得到的是
 * 「同一种颜色」的对比度，而不是用户看到的那一层。所以调用方传进来的
 * 应当已经是不透明色（`composite` 的结果）。
 */
export function contrast(a, b) {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

// -----------------------------------------------------------------------------
// 求解
// -----------------------------------------------------------------------------

/** RGB → HSL（h 0–360，s/l 0–1）。 */
function rgbToHsl(c) {
  const p = parseColor(c)
  const r = p.r / 255
  const g = p.g / 255
  const b = p.b / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const l = (max + min) / 2
  if (max === min) return { h: 0, s: 0, l, a: p.a }

  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60
  else if (max === g) h = ((b - r) / d + 2) * 60
  else h = ((r - g) / d + 4) * 60
  return { h, s, l, a: p.a }
}

function hslToRgb({ h, s, l, a = 1 }) {
  const c = (1 - Math.abs(2 * l - 1)) * s
  const hp = (((h % 360) + 360) % 360) / 60
  const x = c * (1 - Math.abs((hp % 2) - 1))
  const [r1, g1, b1] =
    hp < 1 ? [c, x, 0]
    : hp < 2 ? [x, c, 0]
    : hp < 3 ? [0, c, x]
    : hp < 4 ? [0, x, c]
    : hp < 5 ? [x, 0, c]
    : [c, 0, x]
  const m = l - c / 2
  return { r: (r1 + m) * 255, g: (g1 + m) * 255, b: (b1 + m) * 255, a }
}

/**
 * 把 `seed` 的**亮度**推到「对每一个背景都达标」的位置，色相与饱和度不动。
 *
 * ⚠️ 达标必须按**量化后**的颜色判。最终落盘的是 8bit 的 `#rrggbb`，而二分
 * 是在浮点亮度上做的 —— 恰好停在门槛上的浮点色，四舍五入到 8bit 会掉回门槛
 * 之下（实测 4.62 → 4.61，青柠一次中了 4 条）。所以 `fits()` 里先量化再比。
 *
 * @param seed   种子色（决定色相与饱和度）
 * @param bgs    它会出现其上的全部背景（都必须是不透明色）
 * @param target WCAG 门槛（4.5 正文 / 3.0 大字与非文本）
 * @param margin 安全余量 —— 防止「刚好 4.50」在 8bit 量化后翻到 4.49
 */
export function solveAgainstAll(seed, bgs, target, margin = 0.12) {
  const want = target + margin
  const base = parseColor(seed)
  const list = bgs.map((bg) => parseColor(bg))
  // 1e-9 只吃浮点误差；真正防量化的是 `margin` 本身。
  const fits = (c) => {
    const q = parseColor(toHex(c))
    return list.every((bg) => contrast(q, bg) >= want - 1e-9)
  }

  if (fits(base)) return { r: base.r, g: base.g, b: base.b, a: 1 }

  const hsl = rgbToHsl(base)
  const at = (l) => hslToRgb({ ...hsl, l })

  // 往亮还是往暗：先按「种子落在背景族的哪一侧」定方向；那一侧走不通就翻到
  // 另一侧 —— 浅色品牌把深字压到很暗之后反而需要亮字，走的就是这条翻转路。
  const seedLum = luminance(base)
  const avgBg = list.reduce((sum, bg) => sum + luminance(bg), 0) / list.length
  const lighterOk = fits(at(1))
  const darkerOk = fits(at(0))
  if (!lighterOk && !darkerOk) {
    throw new Error(
      `无法为 ${toHex(base)} 在背景 ${list.map((bg) => toHex(bg)).join(' / ')} 上达到 ${want.toFixed(2)}:1`
    )
  }
  const goLighter = seedLum > avgBg ? lighterOk : !darkerOk

  // 二分出「刚好越界」的那个亮度 —— 既达标，又尽量贴着种子。
  let lo = 0
  let hi = 1
  let best = at(goLighter ? 1 : 0)
  for (let i = 0; i < 64; i += 1) {
    const mid = (lo + hi) / 2
    if (fits(at(mid))) {
      best = at(mid)
      if (goLighter) hi = mid
      else lo = mid
    } else if (goLighter) {
      lo = mid
    } else {
      hi = mid
    }
  }
  const picked = parseColor(toHex(best))
  return { r: picked.r, g: picked.g, b: picked.b, a: 1 }
}

// -----------------------------------------------------------------------------
// 配方参数（改这里 = 改所有主题的派生值）
// -----------------------------------------------------------------------------

/** 淡底的透明度：语义色压在纸色上的比例（只影响底色观感，不承担对比度）。 */
const TINT = { magic: 0.12, ok: 0.11, bad: 0.1, gold: 0.13, rare: 0.1 }

/** 答题选项四态的底色浓度 —— 比淡底重一档，因为它是「这一屏的主控件」。 */
const OPT_TINT = 0.14

/** 默认主题里那七档中性描边的原始透明度（档位关系必须原样保留）。 */
const STROKE_ALPHA = {
  knob: 0.3,
  knobStrong: 0.34,
  edge: 0.36,
  lineDash: 0.45,
  stroke32: 0.32,
  dash44: 0.44,
  dash52: 0.52
}

/** 语义色描边 / 光晕的透明度 —— 沿用默认主题，不参与缩放（否则暗色下会消失）。 */
const EDGE_ALPHA = {
  magic32: 0.32,
  magic34: 0.34,
  magic42: 0.42,
  ok34: 0.34,
  bad34: 0.34,
  gold36: 0.36,
  gold42: 0.42,
  gold50: 0.5,
  rare32: 0.32,
  rare36: 0.36,
  rare44: 0.44
}

/**
 * 纸浆颗粒的 SVG。
 *
 * 与 `tokens.scss` 里那份**必须逐字一致**（除了 `opacity`）——
 * 只有暗色主题换不透明度，其余主题继续用 tokens.scss 的兜底值。
 */
export const GRAIN_SVG = (opacity) =>
  `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='4' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23g)' opacity='${opacity}'/%3E%3C/svg%3E")`

/** 默认主题颗粒的不透明度（= tokens.scss 里的值）。 */
export const GRAIN_OPACITY_DEFAULT = '.13'
/** 暗色主题颗粒的不透明度 —— 灰噪点压在暗底上会整体提亮，必须更轻。 */
export const GRAIN_OPACITY_DARK = '.05'

// -----------------------------------------------------------------------------
// 令牌表
//
// `derive(ctx, v)` 里：
//   · `ctx.core`  —— JSON 里写的核心色（原始值，可能被后面的求解改过）
//   · `v(name)`   —— 取**已经算好**的同名前序令牌（例如求解项要读自己那层淡底）
//   · `ctx.isDark`
//
// 顺序即依赖顺序，不能随便调：淡底在前，用它做背景的文字色在后。
// -----------------------------------------------------------------------------

/** 正文与「非文本」门槛 + 余量。 */
const TEXT = 4.5
const TEXT_MARGIN = 0.12
const UI = 3.0
const UI_MARGIN = 0.1

export const TOKENS = [
  // ---- 纸与墨 ----
  { scss: 'board', css: '--k-board', derive: ({ core }) => core.board },
  { scss: 'paper', css: '--k-paper', derive: ({ core }) => core.paper },
  { scss: 'paper2', css: '--k-paper-2', derive: ({ core }) => core.paper2 },
  { scss: 'paper3', css: '--k-paper-3', derive: ({ core }) => core.paper3 },
  {
    scss: 'paper-plain',
    css: '--k-paper-plain',
    // 「最亮的纸」：默认主题里它比 $paper 亮一丝（#fffdf6 vs #fefcf6）。
    // 暗色主题里 paper 已经很暗，往白里提一点点才有「干净纸面」的意思。
    derive: ({ core, isDark }) => mix(core.paper, '#FFFFFF', isDark ? 0.06 : 0.5)
  },
  { scss: 'line', css: '--k-line', derive: ({ core }) => mix(core.ink3, core.paper3, 0.45) },

  // ---- 淡底（先算：后面「当文字用的语义色」要拿它们当背景求解）----
  { scss: 'paper-blue', css: '--k-paper-blue', derive: ({ core }) => composite(withAlpha(core.magic, TINT.magic), core.paper) },
  { scss: 'paper-ok', css: '--k-paper-ok', derive: ({ core }) => composite(withAlpha(core.ok, TINT.ok), core.paper) },
  { scss: 'paper-bad', css: '--k-paper-bad', derive: ({ core }) => composite(withAlpha(core.bad, TINT.bad), core.paper) },
  { scss: 'paper-gold', css: '--k-paper-gold', derive: ({ core }) => composite(withAlpha(core.gold, TINT.gold), core.paper) },
  { scss: 'paper-rare', css: '--k-paper-rare', derive: ({ core }) => composite(withAlpha(core.rare, TINT.rare), core.paper) },
  { scss: 'opt-selected', css: '--k-opt-selected', derive: ({ core }) => composite(withAlpha(core.magic, OPT_TINT), core.paper) },
  { scss: 'opt-correct', css: '--k-opt-correct', derive: ({ core }) => composite(withAlpha(core.ok, OPT_TINT), core.paper) },
  { scss: 'opt-wrong', css: '--k-opt-wrong', derive: ({ core }) => composite(withAlpha(core.bad, OPT_TINT), core.paper) },

  // ---- 文字：墨阶（对纸面、板色、次级纸面都达标）----
  { scss: 'ink', css: '--k-ink', derive: ({ core }) => core.ink },
  { scss: 'ink2', css: '--k-ink-2', derive: ({ core, v }) => solveAgainstAll(core.ink2, [core.paper, core.paper2, core.board], TEXT, TEXT_MARGIN) },
  { scss: 'ink3', css: '--k-ink-3', derive: ({ core, v }) => solveAgainstAll(core.ink3, [core.paper, core.paper2, core.board], TEXT, TEXT_MARGIN) },

  // ---- 文字：语义色 ----
  // 主色当文字（`.c-blue`、标签栏选中项）—— 与当填充的 `magic` 分开，见文件头。
  {
    scss: 'magic-ink',
    css: '--k-magic-ink',
    derive: ({ core }) => solveAgainstAll(core.magicInk || core.magic, [core.paper, core.paper2, core.board], TEXT, TEXT_MARGIN)
  },
  // 主色深：当文字压在「主色淡底 / 已选底」上（`.pill.blue`、`.chip.on`），
  // 同时兼任按钮底边。浅色主题下求解结果与 JSON 里给的深色基本一致。
  {
    scss: 'magic-d',
    css: '--k-magic-d',
    derive: ({ core, v }) => solveAgainstAll(core.magicDark, [v('paper-blue'), v('opt-selected')], TEXT, TEXT_MARGIN)
  },
  { scss: 'seal', css: '--k-seal', derive: ({ core }) => solveAgainstAll(core.seal, [core.paper], TEXT, TEXT_MARGIN) },
  {
    scss: 'ok',
    css: '--k-ok',
    derive: ({ core, v }) => solveAgainstAll(core.ok, [core.paper, core.board, v('paper-ok')], TEXT, TEXT_MARGIN)
  },
  {
    scss: 'bad',
    css: '--k-bad',
    derive: ({ core, v }) => solveAgainstAll(core.bad, [core.paper, core.board, v('paper-bad')], TEXT, TEXT_MARGIN)
  },
  {
    scss: 'gold-d',
    css: '--k-gold-d',
    derive: ({ core, v }) => solveAgainstAll(core.goldDark, [core.paper, core.board, v('paper-gold')], TEXT, TEXT_MARGIN)
  },
  {
    scss: 'rare',
    css: '--k-rare',
    derive: ({ core, v }) => solveAgainstAll(core.rare, [core.paper, v('paper-rare')], TEXT, TEXT_MARGIN)
  },
  {
    scss: 'on-gold',
    css: '--k-on-gold',
    derive: ({ core }) => solveAgainstAll(core.onGold, [core.gold], TEXT, TEXT_MARGIN)
  },

  // ---- 填充：主色与黄铜（不求解，原样取自 JSON）----
  { scss: 'magic', css: '--k-magic', derive: ({ core }) => core.magic },
  { scss: 'gold', css: '--k-gold', derive: ({ core }) => core.gold },
  {
    scss: 'on-magic',
    css: '--k-on-magic',
    // 填充上的字：对主色求解（青柠是深字压亮底，夜航是深字压金底）。
    derive: ({ core }) => solveAgainstAll(core.onMagic, [core.magic], TEXT, TEXT_MARGIN)
  },
  // 语义实心块上的字：`.opt.ok .k` / `.opt.bad .k` 的题号方块。
  // 默认主题里两者都与 `$on-magic` 同值（拆出来零漂移）；但浅色品牌的
  // `ok` / `bad` 为了当文字用会被压暗，压暗之后原先的深字就只剩 2.5:1 ——
  // 一份 `on-magic` 兼不了「压亮底」与「压压暗后的状态色」两件事。
  {
    scss: 'on-ok',
    css: '--k-on-ok',
    derive: ({ core, v }) => solveAgainstAll(core.onMagic, [v('ok')], TEXT, TEXT_MARGIN)
  },
  {
    scss: 'on-bad',
    css: '--k-on-bad',
    derive: ({ core, v }) => solveAgainstAll(core.onMagic, [v('bad')], TEXT, TEXT_MARGIN)
  },

  // ---- 状态描边与交互边界（非文本，3:1）----
  {
    scss: 'opt-sel-border',
    css: '--k-opt-sel-border',
    // 已选选项的描边。默认主题的 `$magic` 本来就在 4.05:1，求解不会改动它；
    // 浅色品牌（青柠）会被压深到 3:1 —— 这正是这一项要独立成令牌的原因。
    derive: ({ core, v }) => solveAgainstAll(core.magic, [v('opt-selected')], UI, UI_MARGIN)
  },
  { scss: 'opt-ok-border', css: '--k-opt-ok-border', derive: ({ v }) => v('ok') },
  { scss: 'opt-bad-border', css: '--k-opt-bad-border', derive: ({ v }) => v('bad') },
  {
    scss: 'chip-sel-border',
    css: '--k-chip-sel-border',
    // 选中 chip 的描边：比主色浅一档，但浅到看不见就失去意义，所以仍按 3:1 求解。
    derive: ({ core, v }) => solveAgainstAll(mix(core.magic, core.paper, 0.35), [v('opt-selected')], UI, UI_MARGIN)
  },
  {
    scss: 'stroke-ghost',
    css: '--k-stroke-ghost',
    // 表单 / 次级按钮的实边，按 3:1 求解（不参与下面那些装饰描边的缩放）。
    derive: ({ core }) => solveAgainstAll(mix(core.ink, core.paper, 0.6), [core.paper], UI, UI_MARGIN)
  },

  // ---- 按钮暗面 ----
  { scss: 'btn-magic-edge', css: '--k-btn-magic-edge', derive: ({ v }) => v('magic-d') },
  { scss: 'btn-gold-edge', css: '--k-btn-gold-edge', derive: ({ v }) => v('gold-d') },
  {
    scss: 'btn-ok-edge',
    css: '--k-btn-ok-edge',
    derive: ({ core }) => solveAgainstAll(core.ok, [core.paper], UI, UI_MARGIN)
  },
  {
    scss: 'btn-dis-edge',
    css: '--k-btn-dis-edge',
    // 禁用按钮的底边是装饰（按钮整体被 1.4.3 豁免），跟着纸阶走即可。
    derive: ({ core, v }) => mix(v('paper3'), v('ink3'), 0.35)
  },

  // ---- 中性描边（基准色 × 强度缩放）----
  { scss: 'stroke-knob', css: '--k-stroke-knob', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.knob * stroke.scale) },
  { scss: 'stroke-knob-strong', css: '--k-stroke-knob-strong', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.knobStrong * stroke.scale) },
  { scss: 'stroke-edge', css: '--k-stroke-edge', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.edge * stroke.scale) },
  { scss: 'stroke-line-dash', css: '--k-stroke-line-dash', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.lineDash * stroke.scale) },
  { scss: 'stroke-32', css: '--k-stroke-32', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.stroke32 * stroke.scale) },
  { scss: 'stroke-dash-44', css: '--k-stroke-dash-44', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.dash44 * stroke.scale) },
  { scss: 'stroke-dash-52', css: '--k-stroke-dash-52', derive: ({ stroke }) => withAlpha(stroke.base, STROKE_ALPHA.dash52 * stroke.scale) },

  // ---- 投影 ----
  { scss: 'shadow-slip', css: '--k-shadow-slip', derive: ({ stroke, isDark }) => withAlpha(isDark ? '#000000' : stroke.base, isDark ? 0.44 : 0.2) },
  { scss: 'shadow-sheet', css: '--k-shadow-sheet', derive: ({ stroke, isDark }) => withAlpha(isDark ? '#000000' : stroke.base, isDark ? 0.4 : 0.18) },

  // ---- 语义色描边 / 光晕 ----
  { scss: 'edge-magic-32', css: '--k-edge-magic-32', derive: ({ core }) => withAlpha(core.magic, EDGE_ALPHA.magic32) },
  { scss: 'edge-magic-34', css: '--k-edge-magic-34', derive: ({ core }) => withAlpha(core.magic, EDGE_ALPHA.magic34) },
  { scss: 'edge-magic-42', css: '--k-edge-magic-42', derive: ({ core }) => withAlpha(core.magic, EDGE_ALPHA.magic42) },
  { scss: 'edge-ok-34', css: '--k-edge-ok-34', derive: ({ core }) => withAlpha(core.ok, EDGE_ALPHA.ok34) },
  { scss: 'edge-bad-34', css: '--k-edge-bad-34', derive: ({ core }) => withAlpha(core.bad, EDGE_ALPHA.bad34) },
  { scss: 'edge-gold-36', css: '--k-edge-gold-36', derive: ({ core }) => withAlpha(core.gold, EDGE_ALPHA.gold36) },
  { scss: 'edge-gold-42', css: '--k-edge-gold-42', derive: ({ core }) => withAlpha(core.gold, EDGE_ALPHA.gold42) },
  { scss: 'edge-gold-50', css: '--k-edge-gold-50', derive: ({ core }) => withAlpha(core.gold, EDGE_ALPHA.gold50) },
  { scss: 'edge-rare-32', css: '--k-edge-rare-32', derive: ({ core }) => withAlpha(core.rare, EDGE_ALPHA.rare32) },
  { scss: 'edge-rare-36', css: '--k-edge-rare-36', derive: ({ core }) => withAlpha(core.rare, EDGE_ALPHA.rare36) },
  { scss: 'edge-rare-44', css: '--k-edge-rare-44', derive: ({ core }) => withAlpha(core.rare, EDGE_ALPHA.rare44) },

  // ---- 整页背景（三层叠加里的两层色 + 颗粒）----
  // 默认主题是「左上白高光 + 右下暖暗 + 颗粒」。暗色下白高光会糊成一层灰，
  // 暖暗则几乎不可见 —— 两个都得换方向。
  { scss: 'grad-hi', css: '--k-grad-hi', derive: ({ isDark }) => withAlpha('#FFFFFF', isDark ? 0.05 : 0.55) },
  { scss: 'grad-lo', css: '--k-grad-lo', derive: ({ stroke, isDark }) => withAlpha(isDark ? '#000000' : stroke.base, isDark ? 0.3 : 0.1) },
  // 卡片的白色内高光（`inset 0 1px 0`）：暗底上 0.7 的白会变成一道亮边。
  { scss: 'hi-inset', css: '--k-hi-inset', derive: ({ isDark }) => withAlpha('#FFFFFF', isDark ? 0.06 : 0.7) },
  // `raw: true` —— 值不是颜色（是一段 SVG 的 data URI），不做颜色格式化。
  { scss: 'grain', css: '--k-grain', raw: true, derive: ({ isDark }) => GRAIN_SVG(isDark ? GRAIN_OPACITY_DARK : GRAIN_OPACITY_DEFAULT) },

  // ---- 其它页面 / 组件里仍在用的硬编码色 ----
  { scss: 'mask', css: '--k-mask', derive: ({ core, isDark }) => withAlpha(isDark ? '#000000' : core.ink, 0.44) },
  // 卷轴两侧的木轴。轴体贴着纸色（浅色主题下是浅木色，暗色下是深木色）；
  // 轴的轮廓取「金的另一侧」—— 浅色主题里压向墨 ⇒ 比轴体**暗**，
  // 暗色主题里墨比纸亮 ⇒ 轮廓翻成一条亮金边。暗底上做不出「比轴体更暗的
  // 轮廓」，反过来做亮边才是同一个意思：「这根轴有明确的一圈边」。
  { scss: 'rod', css: '--k-rod', derive: ({ core }) => mix(core.gold, core.paper, 0.62) },
  { scss: 'rod-edge', css: '--k-rod-edge', derive: ({ core }) => mix(core.gold, core.ink, 0.28) },
  // 正确率圆环的轨道
  { scss: 'line-ring', css: '--k-line-ring', derive: ({ core }) => mix(core.paper3, core.ink3, 0.18) },
  // 冒险日志柱状图的「已往」档
  { scss: 'bar-past', css: '--k-bar-past', derive: ({ core }) => mix(core.magic, core.paper, 0.55) },
  // 知识树的金色辉光
  { scss: 'glow-gold', css: '--k-glow-gold', derive: ({ core }) => withAlpha(core.gold, 0.12) }
]

// -----------------------------------------------------------------------------
// 入口
// -----------------------------------------------------------------------------

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = path.resolve(HERE, '..', '..', '..')
export const THEMES_JSON = path.join(REPO_ROOT, 'shared', 'ui-themes.json')

export function loadThemes() {
  const raw = JSON.parse(fs.readFileSync(THEMES_JSON, 'utf8'))
  return raw.themes
}

/** 把一套主题的核心色展开成 `{ scss, css, value }` 的有序数组。 */
export function deriveTheme(theme) {
  const values = new Map()
  const v = (name) => {
    if (!values.has(name)) throw new Error(`主题 ${theme.id}：令牌 ${name} 尚未计算（请检查 TOKENS 顺序）`)
    return values.get(name)
  }
  const ctx = {
    core: theme.core,
    mode: theme.mode,
    isDark: theme.mode === 'dark',
    stroke: theme.stroke,
    v
  }

  return TOKENS.map(({ scss, css, derive, raw }) => {
    const computed = derive(ctx)
    // `raw` 的令牌（目前只有 `$grain`）值本身不是颜色，原样输出。
    const value = raw ? String(computed) : formatColor(computed)
    values.set(scss, value)
    return { scss, css, value }
  })
}

export const CSS_VAR_OF_SCSS = Object.fromEntries(TOKENS.map((t) => [t.scss, t.css]))
