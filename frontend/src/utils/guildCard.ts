/**
 * 公会卡导出：把 04·2 的卡面画到 Canvas 上，再存进相册（FR-D2）。
 *
 * ## 为什么只有小程序走这条路
 *
 * H5 没有 `saveImageToPhotosAlbum`，浏览器里「保存图片」是另一套动作
 * （右键另存为 / 新开标签页）。方案 §7.3 因此明确：**H5 端隐藏这个按钮**。
 * 与其在浏览器里做一个不像样的替代品，不如不给 —— 页面上的 H5 版本
 * 只剩「分享给好友」的引导，这与「不给点了没反应的按钮」是同一条纪律。
 *
 * ## 为什么是重画一遍，而不是截图
 *
 * 页面上那张卡是 DOM，无法直接位图化（小程序没有 DOM 截图能力）。
 * 所以这里按同一份数据**重画**一遍。代价是版式有两份实现，
 * 好处是导出的图不受屏幕尺寸影响（设备再宽，导出的也是这张定尺卡）。
 *
 * ⚠️ 两份版式必须一起改：改 `.profile-card__*` 的间距时，这里的
 * 常量要跟着动，否则会出现「屏幕上的卡」与「存下来的卡」不一样。
 *
 * ## 字体
 *
 * Canvas 上的数字拿不到 `Baloo 2`（那是 CSS 字体，小程序还得走
 * `wx.loadFontFace` 才有）。这里退回系统字体栈，并把字体名写进
 * `FONT_FAMILY` 一处 —— 将来真接了字体加载，只改这一行。
 *
 * ## 头像画不出来时不报错
 *
 * 预置头像是 SVG 的 data URI，`createImage()` 对 SVG 的支持在各端并不一致。
 * 加载失败时画一个纸色圆 + 昵称首字（而不是留一个洞，也不是让整个保存失败）：
 * 「存下来一张没有头像的卡」比「点了保存没反应」好得多。
 */

import Taro from '@tarojs/taro'

import { absoluteMediaUrl } from './media'

/** 导出卡片的逻辑尺寸（px）。改动时 `index.scss` 的 `--export-w/h` 注释要同步 */
export const CARD_W = 300
export const CARD_H = 310

/** 保存 canvas 节点的容器 id（页面里的 `<Canvas id>` 必须与它一致） */
export const GUILD_CARD_CANVAS_ID = 'guild-card-canvas'

/** 画布上的字体：`Baloo 2` 拿不到时按系统字体渲染（见文件头） */
const FONT_FAMILY =
  '-apple-system, "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei", sans-serif'

const COLOR = {
  paper: '#FEFCF6',
  /** 纸面内侧 1px 描边 = `$stroke-knob-strong: rgba(150,120,72,.34)` */
  edge: 'rgba(150,120,72,0.34)',
  label: '#6B5A45', // $ink2
  name: '#2A2018', // $ink
  goldBg: '#F8EFD6', // $paper-gold
  goldText: '#9C6E15', // $gold-d
  blueBg: '#DCE9FB', // $opt-selected
  blueText: '#1F4694', // $magic-d
  divider: '#EADFC4', // $paper3
  statLabel: '#9A8870', // $ink3
  avatarFallback: '#F5EDD8' // $paper2
}

export interface GuildCardData {
  nickname: string
  level: number
  levelTitle: string
  /**
   * 三宫格：**值 + 标签一起传进来**。
   *
   * 本模块只负责画，不认识「副本 / 正确率 / 连续天数」这些词 ——
   * 它们是文案，归 `copy.ts`。把措辞放在这里会出现「屏幕上写连续天数、
   * 存下来写连击」这种只在导出图上才看得见的偏差。
   */
  stats: Array<{ value: string; label: string }>
  /** 「职业倾向 · X」里的 X */
  tendency: string
  /** 「加入第 N 天」里的 N；`0` 表示算不出来，此时**不画这一句** */
  joinDay: number
  /** 自定义头像（优先）；没有时按预置精灵画 */
  avatarUrl: string | null
  /** 预置精灵的 data URI；`null` 表示连兜底图都没有 */
  sprite: string | null
  /** 卡面顶部的归属行 */
  cardLabel: string
}

export type SaveResult =
  | { ok: true }
  /** 用户拒绝了相册权限 —— 与「画不出来」是两件事，提示语不同 */
  | { ok: false; reason: 'permission' }
  | { ok: false; reason: 'failed' }

// -----------------------------------------------------------------------------
// 绘制原语
// -----------------------------------------------------------------------------
function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
): void {
  const radius = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.lineTo(x + w - radius, y)
  ctx.arcTo(x + w, y, x + w, y + radius, radius)
  ctx.lineTo(x + w, y + h - radius)
  ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius)
  ctx.lineTo(x + radius, y + h)
  ctx.arcTo(x, y + h, x, y + h - radius, radius)
  ctx.lineTo(x, y + radius)
  ctx.arcTo(x, y, x + radius, y, radius)
  ctx.closePath()
}

/** 文本宽度（自带 `ctx.measureText` 没有时的保守估算） */
function textWidth(ctx: CanvasRenderingContext2D, text: string): number {
  if (typeof ctx.measureText === 'function') return ctx.measureText(text).width
  // 中文按字号全宽、ASCII 按半宽估；只在拿不到 measureText 时用到
  let width = 0
  for (const ch of text) width += /[\u4e00-\u9fa5]/.test(ch) ? 12 : 6
  return width
}

/** 超出可用宽度时逐级缩号，仍放不下就截断加省略号 */
function fontFor(
  ctx: CanvasRenderingContext2D,
  text: string,
  size: number,
  weight: string,
  maxWidth: number
): string {
  let current = size
  while (current > 9) {
    const font = `${weight} ${current}px ${FONT_FAMILY}`
    ctx.font = font
    if (textWidth(ctx, text) <= maxWidth) return font
    current -= 1
  }
  return `${weight} ${current}px ${FONT_FAMILY}`
}

function clampText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (textWidth(ctx, text) <= maxWidth) return text
  let out = text
  while (out.length > 1 && textWidth(ctx, `${out}…`) > maxWidth) {
    out = out.slice(0, -1)
  }
  return `${out}…`
}

/** 居中画一颗胶囊，返回它占的宽度（用于把一排胶囊整体居中） */
function drawPill(
  ctx: CanvasRenderingContext2D,
  x: number,
  centerY: number,
  text: string,
  bg: string,
  fg: string
): number {
  const h = 20
  ctx.font = `600 11px ${FONT_FAMILY}`
  const textW = textWidth(ctx, text)
  const w = textW + 20

  roundRect(ctx, x, centerY - h / 2, w, h, 10)
  ctx.fillStyle = bg
  ctx.fill()

  ctx.fillStyle = fg
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, x + w / 2, centerY + 0.5)
  return w
}

/** 画头像：自定义照片 → 预置精灵 → 纸色圆 + 首字（三级降级，见文件头） */
async function drawAvatar(
  node: { createImage?: () => any },
  ctx: CanvasRenderingContext2D,
  data: GuildCardData,
  cx: number,
  cy: number,
  r: number
): Promise<void> {
  // 自定义头像是服务端给的站内相对路径，`createImage()` 拿它加载不出来，
  // 必须先拼成绝对地址（见 `utils/media`）；预置精灵是 data URI，原样可用。
  const source = absoluteMediaUrl(data.avatarUrl) || data.sprite

  if (source && typeof node.createImage === 'function') {
    const image = node.createImage()
    const loaded = await new Promise<boolean>((resolve) => {
      let settled = false
      const done = (value: boolean) => {
        if (settled) return
        settled = true
        resolve(value)
      }
      image.onload = () => done(true)
      image.onerror = () => done(false)
      image.src = source
    })

    if (loaded) {
      ctx.save()
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.clip()
      try {
        ctx.drawImage(image, cx - r, cy - r, r * 2, r * 2)
        ctx.restore()
        return
      } catch {
        ctx.restore()
      }
    }
  }

  // 兜底：纸色圆 + 昵称首字。宁可少一张脸，也不要一个洞
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = COLOR.avatarFallback
  ctx.fill()
  ctx.fillStyle = COLOR.name
  ctx.font = `700 ${Math.round(r * 0.9)}px ${FONT_FAMILY}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText((data.nickname || '冒').slice(0, 1), cx, cy)
}

// -----------------------------------------------------------------------------
// 主流程
// -----------------------------------------------------------------------------
/** 把卡面画到 canvas 节点上（不含保存动作，便于单独验证绘制） */
export async function drawGuildCard(
  node: any,
  ctx: CanvasRenderingContext2D,
  data: GuildCardData,
  dpr: number
): Promise<void> {
  node.width = CARD_W * dpr
  node.height = CARD_H * dpr
  ctx.scale(dpr, dpr)

  // 纸面
  roundRect(ctx, 0.5, 0.5, CARD_W - 1, CARD_H - 1, 6)
  ctx.fillStyle = COLOR.paper
  ctx.fill()
  ctx.strokeStyle = COLOR.edge
  ctx.lineWidth = 1
  ctx.stroke()

  const centerX = CARD_W / 2
  const innerW = CARD_W - 44

  // 归属行
  ctx.textAlign = 'center'
  ctx.textBaseline = 'alphabetic'
  ctx.fillStyle = COLOR.label
  ctx.font = `400 11px ${FONT_FAMILY}`
  ctx.fillText(clampText(ctx, data.cardLabel, innerW), centerX, 32)

  // 头像
  await drawAvatar(node, ctx, data, centerX, 90, 38)

  // 昵称
  ctx.fillStyle = COLOR.name
  ctx.font = fontFor(ctx, data.nickname, 17, '700', innerW)
  ctx.fillText(clampText(ctx, data.nickname, innerW), centerX, 152)

  // 等级胶囊（两颗整体居中）
  ctx.font = `600 11px ${FONT_FAMILY}`
  const lvText = `Lv.${data.level}`
  const titleText = data.levelTitle || ''
  const lvW = textWidth(ctx, lvText) + 20
  const titleW = titleText ? textWidth(ctx, titleText) + 20 : 0
  const gap = 6
  const totalW = lvW + (titleW ? titleW + gap : 0)
  let cursor = centerX - totalW / 2
  cursor += drawPill(ctx, cursor, 176, lvText, COLOR.goldBg, COLOR.goldText)
  if (titleW) cursor += gap + drawPill(ctx, cursor, 176, titleText, COLOR.blueBg, COLOR.blueText)

  // 分隔线
  ctx.beginPath()
  ctx.moveTo(22, 208)
  ctx.lineTo(CARD_W - 22, 208)
  ctx.strokeStyle = COLOR.divider
  ctx.lineWidth = 1
  ctx.stroke()

  // 三宫格：等宽三列，每列中心在 1/6、3/6、5/6 处
  data.stats.slice(0, 3).forEach((stat, index) => {
    const x = CARD_W * ((index * 2 + 1) / 6)
    ctx.textAlign = 'center'

    ctx.fillStyle = COLOR.name
    ctx.font = fontFor(ctx, stat.value, 18, '700', CARD_W / 3 - 12)
    ctx.fillText(clampText(ctx, stat.value, CARD_W / 3 - 12), x, 234)

    ctx.fillStyle = COLOR.statLabel
    ctx.font = `400 11px ${FONT_FAMILY}`
    ctx.fillText(clampText(ctx, stat.label, CARD_W / 3 - 12), x, 252)
  })

  // 页脚：职业倾向 / 加入第 N 天
  ctx.fillStyle = COLOR.label
  ctx.font = `400 11px ${FONT_FAMILY}`
  ctx.textAlign = 'left'
  ctx.fillText(clampText(ctx, data.tendency, innerW / 2), 22, 286)

  if (data.joinDay > 0) {
    ctx.textAlign = 'right'
    ctx.fillText(clampText(ctx, `加入第 ${data.joinDay} 天`, innerW / 2), CARD_W - 22, 286)
  }
}

/** 相册权限被拒时的错误文案特征（各端 `errMsg` 措辞不同，一律按关键词判） */
function isPermissionError(error: unknown): boolean {
  const message = String((error as { errMsg?: string })?.errMsg || error || '')
  return /auth|deny|denied|permission/i.test(message)
}

/**
 * 绘制并保存公会卡。**只在非 H5 环境调用**（见文件头）。
 *
 * 返回结果而不抛异常：调用方要区分「权限被拒」与「画不出来」，
 * 两者的提示语不一样，而这两种失败都不该冒泡成未捕获的 Promise。
 */
export async function saveGuildCard(data: GuildCardData): Promise<SaveResult> {
  try {
    const node = await new Promise<any>((resolve) => {
      Taro.createSelectorQuery()
        .select(`#${GUILD_CARD_CANVAS_ID}`)
        .fields({ node: true, size: true })
        .exec((res) => resolve((res?.[0] as { node?: any } | undefined)?.node ?? null))
    })

    if (!node) return { ok: false, reason: 'failed' }

    let dpr = 2
    try {
      dpr = Taro.getSystemInfoSync().pixelRatio || 2
    } catch {
      dpr = 2
    }

    const ctx = node.getContext('2d')
    await drawGuildCard(node, ctx, data, dpr)

    const filePath = await new Promise<string>((resolve, reject) => {
      Taro.canvasToTempFilePath({
        canvas: node,
        x: 0,
        y: 0,
        width: CARD_W,
        height: CARD_H,
        destWidth: CARD_W * dpr,
        destHeight: CARD_H * dpr,
        success: (res) => resolve(res.tempFilePath),
        fail: reject
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any)
    })

    await Taro.saveImageToPhotosAlbum({ filePath })
    return { ok: true }
  } catch (error) {
    return { ok: false, reason: isPermissionError(error) ? 'permission' : 'failed' }
  }
}
