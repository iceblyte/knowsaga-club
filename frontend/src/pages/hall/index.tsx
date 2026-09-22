/**
 * 社团大厅（原型 01 第 2 / 3 屏）。
 *
 * 全屏只有一个目标：让用户把想学的东西写下来。所以：
 * - 输入区占满剩余高度（`.scrollbox{flex:1}`），视觉上就是页面的主角
 * - 空态给预设热门问题 chip，**点一下直接召唤**（见下）
 * - 已输入态把 chip 换成「追加资料」类动作
 *
 * 与原型的两处说明：
 * 1. 原型把 `AI 将联网补充` 这个 pill 画死在已输入态。实际上它取决于后端
 *    `search_enabled` 开关，所以这里做成动态：开启时是蓝色的「AI 将联网补充」，
 *    关闭时换成中性的「基于已有知识出题」—— 保留同一个版位，但不说假话。
 * 2. `上传文档 / 粘贴网址 / 追加背景资料` 属于 P1「卷轴工坊」的多源输入能力，
 *    本期未实现，点击给出明确提示而不是静默失败。
 * 3. 底部那张冒险者档案卡（等级 / 累计 XP / 连续天数）原本是写死的演示数据，
 *    现在读 `GET /users/me`。它是这一屏唯一需要联网的东西，所以它自己
 *    承担加载态 —— 读不到时只出占位符，整屏不因此变成空页面。见 `HALL_PROFILE_COPY`。
 *
 * ## 预设问题从「填入输入框」改成了「直接召唤」（本轮修复第 4 条）
 *
 * 原来点 chip 只是把它填进输入框，用户还得自己再点一次「召唤副本」。
 * 空态放 chip 的全部意义是「少打字、快点出题」，只填不发等于把省下的
 * 那一步又还回去 —— 用户的反馈正是「点了没反应、发不出去」。
 * 现在点击即走，并且同一句话也写进 `useAppStore.userInput`：召唤页点返回时
 * 输入框里仍是这一条，可以改几个字再发。
 *
 * ⚠️ 换文案时要守住「每一条 ≥ 8 字」（`INPUT_MIN_LEN`，真源在后端
 * `text_cleaner`）—— 短于 8 字的一键发送会被服务端判 4001。
 */

import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useRef, useState } from 'react'

import PhoneShell from '../../components/PhoneShell'
import ReminderPrompt from '../../components/ReminderPrompt'
import Sprite from '../../components/Sprite'
import { ARCHIVE_COMMON, COMMON_COPY, HALL_PROFILE_COPY } from '../../constants/copy'
import {
  INPUT_MAX_LEN,
  INPUT_MIN_LEN,
  MOCK_ATTACH_CHIPS,
  MOCK_SUGGESTIONS
} from '../../constants/mock'
import { useAsyncData } from '../../hooks/useAsyncData'
import { useTabPage } from '../../hooks/useTabPage'
import { fetchProfile } from '../../services/archive'
import { useAppStore } from '../../store/useAppStore'
import type { UserPublic } from '../../types/api'
import { goPage } from '../../utils/navigation'
import { styleOf } from '../../utils/style'

import './index.scss'

/**
 * 档案副行（原型「1280 / 2000 XP」）。
 *
 * 三种「不在正常态」的情况合成一处，因为它们在这一行里长得一样 ——
 * 都是「这里现在没有数字」：
 *
 * - `user` 为 `null` 且还没失败 → 占位破折号；
 * - `user` 为 `null` 且已经失败 → 说明读不到的原因，而不是继续摆破折号
 *   （一个永远不动的破折号看起来像界面坏了，说不清是哪一边的问题）；
 * - 满级 → 分母取自身，写成分数就是「8000 / 8000」，只报累计值。
 */
function xpLine(user: UserPublic | null, failed: boolean): string {
  if (!user) return failed ? ARCHIVE_COMMON.loadFailed : HALL_PROFILE_COPY.unknown
  if (user.xp_to_next_level <= 0) return HALL_PROFILE_COPY.xpTotal(user.xp_total)
  return HALL_PROFILE_COPY.xpFraction(user.xp_total, user.next_level_xp)
}

export default function HallPage() {
  useTabPage('hall')

  const userInput = useAppStore((s) => s.userInput)
  const setUserInput = useAppStore((s) => s.setUserInput)
  const searchEnabled = useAppStore((s) => s.searchEnabled)

  /** 冒险者档案（原型 01 底部那张卡）。`me` 为 `null` 时卡片只出占位符 */
  const { status, data, reload } = useAsyncData(() => fetchProfile())
  const me = data?.user ?? null

  const [draft, setDraft] = useState(userInput)

  /** 每次重新显示递增，透给页内提醒让它重新判断该不该出现（刚复习完就该消失） */
  const [showSeq, setShowSeq] = useState(0)

  // 首次（挂载时）跳过刷新：那一次由 `useAsyncData` 自己发起，
  // 不跳过的话进大厅会连发两个一模一样的 `/users/me`
  const firstShowRef = useRef(true)

  useDidShow(() => {
    // 从召唤页返回时同步回已提交的输入
    setDraft(useAppStore.getState().userInput)
    setShowSeq((value) => value + 1)

    // 这是标签页，打完一局再切回来页面不会卸载 —— 档案卡上的等级与 XP
    // 必须重取，否则它会永远停在进这一屏的那一刻。
    // `useAsyncData` 重新加载期间保留旧数据，所以这里不会闪空。
    if (firstShowRef.current) {
      firstShowRef.current = false
      return
    }
    reload()
  })

  const trimmedLen = draft.trim().length
  const canSubmit = trimmedLen >= INPUT_MIN_LEN
  const hasInput = trimmedLen > 0

  /**
   * 点预设问题 = **直接召唤**（本轮修复第 4 条）。
   *
   * 原来这里只把问题填进输入框，用户还得自己再点一次「召唤副本」——
   * 而空态放 chip 的全部意义就是「少打字、快点出题」，只填不发等于
   * 把省下的那一步又还回去了（用户的反馈正是「点了一直没反应」）。
   *
   * 同时写进 store，而不是只传参：召唤页读的是 `useAppStore.userInput`，
   * 而输入框里也留着同一句话 —— 用户在召唤页点返回，看到的仍是他点的那一条，
   * 可以直接改几个字再发（而不是回到一个空输入框）。
   */
  const summonWithPreset = (question: string) => {
    setDraft(question)
    setUserInput(question)
    goPage('/pages/summon/index', 'navigate')
  }

  const handleAttachTap = () => {
    // P1 能力，明确告知而不是静默失败
    Taro.showToast({ title: COMMON_COPY.comingSoon, icon: 'none' })
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
    goPage('/pages/summon/index', 'navigate')
  }

  return (
    <PhoneShell navTitle='社团大厅' showBack={false} scroll={false} reserveTabBar>
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

      {/* 今日有到期错题的页内提示（方案 §8.5）。
          放在欢迎卡之后、输入框之前：它是一条「顺带告诉你」，
          不该抢输入框的位置，也不该被压到屏幕底部看不见。
          今日无到期错题、或今天已点过「今天先不复习」时它什么都不渲染。 */}
      <ReminderPrompt refreshKey={showSeq} />

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

      {/* 空态：预设热门问题 / 已输入态：追加资料 chip。
          两种状态的 chip **动作完全不同**（一个是「立刻出题」，
          一个是「本期还没做的多源输入」），所以不再共用一个 handler。 */}
      {hasInput ? (
        <View className='row hall__chips'>
          {MOCK_ATTACH_CHIPS.map((chip) => (
            <Text key={chip} className='chip' onClick={handleAttachTap}>
              {chip}
            </Text>
          ))}
        </View>
      ) : (
        <>
          {/* 一句说明不能省：chip 上没有任何「点一下会直接开始出题」的暗示，
              不写出来用户会以为它和原来一样只负责填空 */}
          <View className='tiny hall__chips-label'>
            热门问题 · 点一下直接召唤副本
          </View>
          <View className='row hall__chips'>
            {MOCK_SUGGESTIONS.map((question) => (
              <Text key={question} className='chip' onClick={() => summonWithPreset(question)}>
                {question}
              </Text>
            ))}
          </View>
        </>
      )}

      <Button className={`btn${canSubmit ? '' : ' dis'}`} disabled={!canSubmit} onClick={handleSubmit}>
        召唤副本
      </Button>

      {/* 冒险者档案（真实数据：`GET /users/me`，见 `HALL_PROFILE_COPY`）。
          注意：等级进度条属于**卡片内部**的元素 —— 原型里 `.between` 之后紧跟一个
          8px 留白，然后才是 `.bar.blue`，但整条 bar 仍在 `.card` 里。
          早前把它写在 `card` 闭合之后，于是变成一条悬在卡片与标签栏之间的孤立蓝条
          （轨道色 $paper3 与底板 $board 接近，看上去就只剩那条 64% 的蓝色）。

          读不到数据时这张卡**照样在**，只是数字位置变成占位符 ——
          它不能整块消失，也不能退回默认值：`.hall__input` 是 `flex:1`，
          卡片一旦消失，上面的输入框会立刻长高，等数据回来再缩回去，
          看上去就是「页面自己抖了一下」。 */}
      <View className='card'>
        <View className='between'>
          <View className='row hall__adventurer'>
            <Sprite name='scholar' size={32} />
            <View>
              {/* 同上：原型是 <div>，块级才换行 */}
              <View className='hall__level'>
                {me ? HALL_PROFILE_COPY.level(me.level, me.level_title) : HALL_PROFILE_COPY.unknown}
              </View>
              <View className='tiny'>{xpLine(me, status === 'error')}</View>
            </View>
          </View>
          {/* 连续天数是胶囊，缺数据时**整个不渲染**：它在右侧，
              消失不会挪动左边的头像与等级（`between` 只把两端撑开） */}
          {me ? (
            <Text className='pill gold'>{HALL_PROFILE_COPY.streak(me.streak_days)}</Text>
          ) : null}
        </View>

        {/* 原型 `<div style="height:8px">`：档案行与进度条之间的留白 */}
        <View className='hall__gap' />

        {/* 等级进度条，宽度由服务端给的 `level_progress` 决定 */}
        <View className='bar blue'>
          <View style={styleOf({ width: `${me?.level_progress ?? 0}%` })} />
        </View>
      </View>
    </PhoneShell>
  )
}
