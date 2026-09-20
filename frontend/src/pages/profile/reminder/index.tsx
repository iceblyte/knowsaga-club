/**
 * 复习提醒（原型 04·8）。
 *
 * ## 它是「页内提醒」的落地页，不是推送的附属品
 *
 * 需求文档把「微信订阅消息真下发」列入不做（本轮没有模板 ID），降级为
 * **页内提醒**，并明确要求这一屏的**视觉与交互完整保留**。所以这一页不依赖
 * 任何推送通道：大厅与个人中心的「今日有到期错题」入口（见 `components/
 * ReminderPrompt`）直接跳到这里，用户从任何地方进来看到的都是同一屏。
 *
 * ## 三宫格的数字与「今天先不复习」互不影响
 *
 * 「今天先不复习」只写 `remind_snooze_date`，**不改任何错题的排期**
 * （后端口径）—— 所以点完之后 `due_count` 不变，变的是「还催不催」。
 * 这一页因此在忽略成功后**回到上一屏**：它的全部职责就是「请你现在复习」，
 * 用户说了「今天不」，这一屏就没有别的事可做了。再次进来时，
 * 忽略按钮会显示为已跳过的状态（`snoozed_today`），而不是又催一遍。
 *
 * ## 主视觉是鸢鸢（飘行）
 *
 * 00-设计规范把鸢鸢分给「邀请 · 等待 · 分享 · 复习提醒」这一语义域，
 * 原型这一屏也是它，尺寸 126、`drift` 动效（与渲染结果一致）。
 *
 * ## 「开始重温」与 04·7 是同一个动作
 *
 * 走 `POST /review/start` 把所有到期错题组成一局，`start()` 生成新的交卷令牌
 * —— 所以复习这一局是一条**独立的挑战记录**，不会覆盖错题来源的那一局。
 */

import { Button, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import Sprite from '../../../components/Sprite'
import { ARCHIVE_COMMON, REMINDER_COPY, reminderHint } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchRemindersToday, snoozeReminders } from '../../../services/reminders'
import { startReview } from '../../../services/review'
import { useQuizStore } from '../../../store/useQuizStore'
import { goPage, goTab } from '../../../utils/navigation'

import './index.scss'

/** 正在进行中的动作；同刻只允许一个，避免「开始」与「忽略」互相踩 */
type Busy = null | 'start' | 'snooze'

export default function ReminderPage() {
  const { status, data, reload } = useAsyncData(() => fetchRemindersToday())
  const [busy, setBusy] = useState<Busy>(null)

  if (!data) {
    return (
      <PhoneShell navTitle={REMINDER_COPY.navTitle} screenClassName='reminder'>
        {status === 'error' ? (
          <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  if (data.due_count === 0) {
    return (
      <PhoneShell navTitle={REMINDER_COPY.navTitle} screenClassName='reminder'>
        <ArchiveState
          kind='empty'
          title={REMINDER_COPY.emptyTitle}
          body={REMINDER_COPY.emptyBody}
          actionText={REMINDER_COPY.emptyCta}
          onAction={() => goTab('/pages/hall/index')}
        />
      </PhoneShell>
    )
  }

  const handleStart = async () => {
    if (busy) return
    setBusy('start')
    try {
      const result = await startReview()
      useQuizStore.getState().start(result.quiz)
      goPage('/pages/quiz/index', 'redirect')
    } catch (error) {
      // 「没到期」与「组卷失败」要分开说：前者刷新一下就消失了，后者要重试
      const code = (error as { code?: number } | null)?.code
      Taro.showToast({
        title: code === 4005 ? REMINDER_COPY.startEmpty : REMINDER_COPY.startFailed,
        icon: 'none'
      })
      if (code === 4005) reload()
    } finally {
      setBusy(null)
    }
  }

  const handleSnooze = async () => {
    if (busy) return
    setBusy('snooze')
    try {
      await snoozeReminders()
      Taro.showToast({ title: REMINDER_COPY.snoozed, icon: 'none' })
      // 这一屏的目的就是「请你现在复习」，用户说「今天不」之后没有别的事可做 ——
      // 留着会在他们刚拒绝之后继续显示「你有 3 道旧识在等你」。
      // 页面本身仍然可以从我的档案再进来，忽略的是今天的提醒，不是这些题。
      Taro.navigateBack({ delta: 1 }).catch(() => goTab('/pages/hall/index'))
    } catch {
      Taro.showToast({ title: REMINDER_COPY.snoozeFailed, icon: 'none' })
    } finally {
      setBusy(null)
    }
  }

  const snoozed = data.snoozed_today

  return (
    <PhoneShell navTitle={REMINDER_COPY.navTitle} screenClassName='reminder'>
      <View className='spacer' />

      <View className='reminder__hero'>
        {/* 名字与动效都对齐原型渲染结果（`class="sprite drift"`、126px） */}
        <Sprite name='yuanyuan' size={126} motion='drift' />

        <View className='reminder__copy'>
          <View className='h'>{REMINDER_COPY.title(data.due_count)}</View>
          <View className='body sm reminder__hint'>{reminderHint(data.hint)}</View>
        </View>

        {/* 三宫格：值与标签都跟着数据走，不写死原型里的 2m / 3 / +60 */}
        <View className='card plain reminder__stats'>
          <View className='reminder__stat'>
            <View className='stat sm c-gold'>{REMINDER_COPY.minutes(data.estimated_minutes)}</View>
            <View className='statlab'>{REMINDER_COPY.statMinutes}</View>
          </View>
          <View className='reminder__stat'>
            <View className='stat sm c-blue'>{data.due_count}</View>
            <View className='statlab'>{REMINDER_COPY.statDue}</View>
          </View>
          <View className='reminder__stat'>
            <View className='stat sm c-rare'>{REMINDER_COPY.xp(data.available_xp)}</View>
            <View className='statlab'>{REMINDER_COPY.statXp}</View>
          </View>
        </View>
      </View>

      <View className='spacer' />

      <Button
        className={`btn${busy === 'start' ? ' dis' : ''}`}
        disabled={busy !== null}
        onClick={handleStart}
      >
        {busy === 'start' ? REMINDER_COPY.starting : REMINDER_COPY.start}
      </Button>

      {/* 已经忽略过就显示为「今天已跳过」并禁用 —— 不是错误，是这件事已经做完了 */}
      <Button
        className={`btn ghost${snoozed ? ' dis' : ''}`}
        disabled={snoozed || busy !== null}
        onClick={handleSnooze}
      >
        {snoozed
          ? REMINDER_COPY.snoozedNote
          : busy === 'snooze'
            ? REMINDER_COPY.snoozing
            : REMINDER_COPY.snooze}
      </Button>
    </PhoneShell>
  )
}
