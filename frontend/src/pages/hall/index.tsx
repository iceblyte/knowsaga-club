/**
 * 社团大厅（原型 01 第 2 / 3 屏）。
 *
 * 全屏只有一个目标：让用户把想学的东西写下来。所以：
 * - 输入区占满剩余高度（`.scrollbox{flex:1}`），视觉上就是页面的主角
 * - 空态给推荐 chip 减少键盘输入（能显著提升首题生成率）
 * - 已输入态把 chip 换成「追加资料」类动作
 *
 * 与原型的两处说明：
 * 1. 原型把 `AI 将联网补充` 这个 pill 画死在已输入态。实际上它取决于后端
 *    `search_enabled` 开关，所以这里做成动态：开启时是蓝色的「AI 将联网补充」，
 *    关闭时换成中性的「基于已有知识出题」—— 保留同一个版位，但不说假话。
 * 2. `上传文档 / 粘贴网址 / 追加背景资料` 属于 P1「卷轴工坊」的多源输入能力，
 *    本期未实现，点击给出明确提示而不是静默失败。
 */

import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useMemo, useState } from 'react'

import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { useTabPage } from '../../hooks/useTabPage'
import { COMMON_COPY } from '../../constants/copy'
import {
  INPUT_MAX_LEN,
  INPUT_MIN_LEN,
  MOCK_ATTACH_CHIPS,
  MOCK_LEVEL_PERCENT,
  MOCK_SUGGESTIONS
} from '../../constants/mock'
import { useAppStore } from '../../store/useAppStore'

import './index.scss'

export default function HallPage() {
  useTabPage('hall')

  const userInput = useAppStore((s) => s.userInput)
  const setUserInput = useAppStore((s) => s.setUserInput)
  const searchEnabled = useAppStore((s) => s.searchEnabled)
  const adventurer = useAppStore((s) => s.adventurer)

  const [draft, setDraft] = useState(userInput)

  useDidShow(() => {
    // 从召唤页返回时同步回已提交的输入
    setDraft(useAppStore.getState().userInput)
  })

  const trimmedLen = draft.trim().length
  const canSubmit = trimmedLen >= INPUT_MIN_LEN
  const hasInput = trimmedLen > 0

  /** 空态用推荐 chip，已输入态换成追加资料类动作 */
  const chips = useMemo(
    () => (hasInput ? [...MOCK_ATTACH_CHIPS] : [...MOCK_SUGGESTIONS]),
    [hasInput]
  )

  const handleChipTap = (chip: string) => {
    if (hasInput) {
      // P1 能力，明确告知而不是静默失败
      Taro.showToast({ title: COMMON_COPY.comingSoon, icon: 'none' })
      return
    }
    const next = draft ? `${draft}${draft.endsWith(' ') ? '' : ' '}${chip}` : chip
    setDraft(next.slice(0, INPUT_MAX_LEN))
  }

  const handleSubmit = () => {
    if (!canSubmit) {
      Taro.showToast({
        title: `再多写几个字吧（至少 ${INPUT_MIN_LEN} 个）`,
        icon: 'none'
      })
      return
    }
    setUserInput(draft.trim())
    Taro.navigateTo({ url: '/pages/summon/index' })
  }

  return (
    <PhoneShell
      navTitle='社团大厅'
      showBack={false}
      navRight='我的'
      onNavRightTap={() => Taro.switchTab({ url: '/pages/mine/index' })}
      scroll={false}
      reserveTabBar
    >
      {/* 身份欢迎卡 */}
      <View className='card'>
        <View className='row'>
          <View className='hall__sprite-slot'>
            <Sprite name='shishi' size={46} />
          </View>
          <View className='hall__welcome-text'>
            {/* 这两行在原型里是 <div>（块级）。小程序里 <text> 默认 inline，
                两行会挤在同一行，所以这里必须用 View 才等于原型的换行效果。 */}
            <View className='h sm'>冒险者，欢迎回到社团大厅</View>
            <View className='sub hall__welcome-sub'>今天想拾取哪一块知识？</View>
          </View>
        </View>
      </View>

      {/* 卷轴输入框：占满剩余高度 */}
      <View className='scrollbox hall__input'>
        <View className='inner'>
          <Textarea
            className='hall__textarea'
            placeholderClass='hall__placeholder'
            value={draft}
            placeholder={'说出你想学的任何知识…\n一句话 / 一段文字 / 一个网址 / 一份文档'}
            maxlength={INPUT_MAX_LEN}
            autoHeight={false}
            cursorSpacing={24}
            onInput={(e) => setDraft(e.detail.value.slice(0, INPUT_MAX_LEN))}
          />
          <View className='between'>
            {hasInput ? (
              <Text className={`pill${searchEnabled ? ' blue' : ''}`}>
                {searchEnabled ? 'AI 将联网补充' : '基于已有知识出题'}
              </Text>
            ) : (
              <View />
            )}
            <Text className='tiny'>
              {draft.length} / {INPUT_MAX_LEN}
            </Text>
          </View>
        </View>
      </View>

      {/* 推荐 / 追加资料 chip */}
      <View className='row hall__chips'>
        {chips.map((chip) => (
          <Text key={chip} className='chip' onClick={() => handleChipTap(chip)}>
            {chip}
          </Text>
        ))}
      </View>

      <Button className={`btn${canSubmit ? '' : ' dis'}`} disabled={!canSubmit} onClick={handleSubmit}>
        召唤副本
      </Button>

      {/* 冒险者档案（演示数据，见 constants/mock.ts） */}
      <View className='card'>
        <View className='between'>
          <View className='row hall__adventurer'>
            <Sprite name='scholar' size={32} />
            <View>
              {/* 同上：原型是 <div>，块级才换行 */}
              <View className='hall__level'>{adventurer.levelLabel}</View>
              <View className='tiny'>
                {adventurer.xpCurrent} / {adventurer.xpTotal} XP
              </View>
            </View>
          </View>
          <Text className='pill gold'>连续 {adventurer.streakDays} 天</Text>
        </View>
      </View>

      <View className='hall__gap' />

      <View className='bar blue'>
        <View style={{ width: `${MOCK_LEVEL_PERCENT}%` }} />
      </View>
    </PhoneShell>
  )
}
