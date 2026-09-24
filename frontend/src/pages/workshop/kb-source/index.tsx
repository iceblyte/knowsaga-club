/**
 * 选择输入方式（原型 05·1）。
 *
 * ## 它是「多源输入」的落地页，也是大厅那三个 chip 的去处
 *
 * 原型的批注写得很清楚：把「一句话」以外的输入源收在一处，主流程不受干扰；
 * 四种方式**平铺、不折叠成菜单**，降低发现成本。所以这一页不做什么花活 ——
 * 一张导语卡 + 四行入口。
 *
 * ## 只有两行能进，而**不能进的那两行也照常渲染**
 *
 * 本期落地的是「一句话」（回大厅）与「上传文档」（去上传页）；
 * 网页链接与视频链接不做（网页已由「用户给的链接必读」覆盖，视频见
 * `openspec/changes/add-private-knowledge-base/proposal.md` 的 Non-goals）。
 *
 * 做法是**渲染但压暗，点了明确说「还没开放」**，而不是隐藏：
 *
 * - 隐藏：用户不知道这里以后会有什么，也看不出这一页是「四选一」；
 * - 静默不可点：最难查的一种失败（看起来像坏了）；
 * - 原型里这四项本来就是并排的，砍掉两行会让版面变成另一种设计。
 *
 * 导语也跟着改了（原型写「一句话、一份文档、一个网页或一段视频」）——
 * 四个入口里两个进不去，而导语承诺四个都能用，那是最直接的一种骗人。
 * 两条都已登记进 `constants/copy.ts` 文件头第 5 条。
 */

import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import PhoneShell from '../../../components/PhoneShell'
import { KB_SOURCE_COPY } from '../../../constants/copy'
import { goPage, goTab } from '../../../utils/navigation'

import './index.scss'

/** 四个入口在原型里的方块字：「文 / 档 / 链 / 影」 */
type SourceKey = 'text' | 'doc' | 'link' | 'video'

const MARKS: Record<SourceKey, string> = {
  text: '文',
  doc: '档',
  link: '链',
  video: '影'
}

/** 入口顺序与原型一致：最快 → 文档 → 链接 → 视频 */
const ORDER: SourceKey[] = ['text', 'doc', 'link', 'video']

/** 本期开放的两个入口。没在这里面的就是「还没开放」 */
const OPEN: SourceKey[] = ['text', 'doc']

export default function KbSourcePage() {
  const handlePick = (key: SourceKey) => {
    if (key === 'text') {
      // 「一句话」的输入框在大厅 —— 不在这里复制一个，
      // 那会让两处输入框的校验（8–200 字）有一天对不上
      goTab('/pages/hall/index')
      return
    }
    if (key === 'doc') {
      // 不带 kb_id：落到默认库（design D16）
      goPage('/pages/workshop/kb-upload/index', 'navigate')
      return
    }
    Taro.showToast({ title: KB_SOURCE_COPY.notReady, icon: 'none' })
  }

  return (
    <PhoneShell navTitle={KB_SOURCE_COPY.navTitle}>
      <View className='card'>
        <View className='h'>{KB_SOURCE_COPY.title}</View>
        <View className='sub'>{KB_SOURCE_COPY.body}</View>
      </View>

      {ORDER.map((key) => {
        const item = KB_SOURCE_COPY.items[key]
        const open = OPEN.includes(key)
        return (
          <View
            className={`li${open ? '' : ' kb-source__off'}`}
            key={key}
            onClick={() => handlePick(key)}
          >
            <View className='ico'>
              <Text className='kb-source__mark'>{MARKS[key]}</Text>
            </View>
            <View className='tx'>
              <View className='n'>{item.label}</View>
              <View className='d'>{item.desc}</View>
            </View>
            <Text className='tiny'>›</Text>
          </View>
        )
      })}

      <View className='tiny kb-source__footer'>{KB_SOURCE_COPY.footer}</View>

      <View className='spacer' />
    </PhoneShell>
  )
}
