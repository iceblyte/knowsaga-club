/**
 * 冒险者头像（原型 00 的 `.advatar`，即「圆形裁切后的角色」）。
 *
 * ## 为什么要抽出来
 *
 * 头像是「自定义优先、预置兜底」的**两套来源**（方案 §7.4）：
 *
 * | `avatar_url` | `avatar_key` | 渲染 |
 * |---|---|---|
 * | 有 | 忽略 | 用户上传的照片，圆形裁切 + 金属描边 |
 * | 无 | 预置键 | 对应职业精灵（学徒 / 学者 / 骑士 / 法师 / 游侠 / 工匠） |
 *
 * 这段判断在个人中心（04·1）、公会卡（04·2）、头像昵称页（07·4）三处都要写。
 * 三处各写一遍的结果是**某一天只改了两处** —— 而这类不一致表现出来是
 * 「设置页换过头像了，个人中心还是旧的」，很难被当成 bug 提上来。
 *
 * ## 为什么不复用 `Sprite`
 *
 * `Sprite` 只管预置精灵，签名里没有「自定义图片」这一路。与其给它加两个
 * 只有一处用得上的可选参数（并把「哪个优先」的规则塞进它），不如让
 * `Sprite` 保持单一职责，这里按需分别渲染。
 *
 * ## 类名用 `.advatar` 而不是 `.avatar`（重要）
 *
 * 这两个名字差一个字母，但**是两个不同的东西**：
 *
 * - `.avatar` —— 设计规范里的**彩色圆底占位**（`background:#E7EFFB` + 蓝描边，
 *   另有 `.gold` / `.rare` / `.sm`），表示「这里有一张圆形的东西」；
 * - `.advatar` —— 原型给**角色图**用的类（`display:block; overflow:visible`）。
 *
 * 早前本组件用的正是 `.avatar`，于是预置精灵背后多出一层蓝色圆底与一圈蓝描边 ——
 * 而它在 `tsc` 与 `build` 里都看不出来，只有量 DOM 才会发现（实测
 * `backgroundColor` 是 `rgb(231,239,251)` 而非透明）。所以这里改用原型的 `.advatar`，
 * 并且**不在本文件里重定义它**，避免与 `styles/base.scss` 的两份定义互相抢覆盖。
 *
 * ## 照片为什么不直接给 `<image>` 加内描边
 *
 * 内描边（`box-shadow: inset`）画在 `<image>` 上时，小程序端由原生图层绘制
 * 图片内容，这条声明**可能既不出错也不生效** —— 也就是静默失效。
 * 所以照片分支套一层 `View`，描边走它自己的 `border`（`box-sizing: border-box`，
 * 图片被压进内圈，描边因此永远在图片之上），两端行为一致。
 *
 * ## 兜底而不是报错
 *
 * `avatar_key` 是服务端给的字符串。若将来服务端加了新职业而前端还没跟上，
 * 这里退回「学者」而不是渲染成空白 —— 界面上少一张头像比多一个洞更难解释。
 */

import { Image, View } from '@tarojs/components'

import { SPRITES, type SpriteName } from '../../assets/sprites'
import { squareStyle } from '../../utils/style'

import './index.scss'

/** 换算系数：750 ÷ 332，与 `Sprite` 的约定一致 */
const PX_RATIO = 2.259

/**
 * 预置头像键 → 精灵名。
 *
 * 六个键与后端 `utils/crypto.py` 的 `AVATAR_KEYS` **一一对应且顺序相同**；
 * 两边同名，所以这里是一张显式表而不是 `as SpriteName` 断言 ——
 * 断言会让「后端加了键、前端漏了映射」变成一个编译期不报错的运行时空洞。
 */
const PRESET_AVATAR: Record<string, SpriteName> = {
  apprentice: 'apprentice',
  scholar: 'scholar',
  knight: 'knight',
  mage: 'mage',
  ranger: 'ranger',
  artisan: 'artisan'
}

/** `avatar_key` 认不出来时的兜底（与后端 `DEFAULT_AVATAR_KEY` 一致） */
const FALLBACK_AVATAR: SpriteName = 'scholar'

export interface AvatarProps {
  /** 预置头像键；**不能叫 `key`**，那是 React 的保留 prop，读不到 */
  avatarKey?: string | null
  /** 自定义头像地址；有值时优先 */
  avatarUrl?: string | null
  /** 尺寸，**直接写原型 px**（如原型 58×58 就传 58），内部换算 */
  size: number
  className?: string
}

export default function Avatar({ avatarKey, avatarUrl, size, className = '' }: AvatarProps) {
  const style = squareStyle(Math.round(size * PX_RATIO))
  const cls = ['advatar', className].filter(Boolean).join(' ')

  if (avatarUrl) {
    return (
      <View className={`${cls} advatar--photo`} style={style}>
        <Image className='advatar__img' src={avatarUrl} mode='aspectFill' />
      </View>
    )
  }

  const name = PRESET_AVATAR[avatarKey ?? ''] ?? FALLBACK_AVATAR
  return (
    <Image className={cls} style={style} src={SPRITES[name]} mode='aspectFit' aria-label='预置头像' />
  )
}
