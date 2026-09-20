/**
 * 页内复习提醒（方案 §8.5）。
 *
 * 本轮不做订阅消息真下发（没有模板 ID），复习提醒降级成**页内提示**：
 * 进小程序时若今日有到期错题，在社团大厅与个人中心给一个入口。
 *
 * ## 它自己取数，而不是让页面传进来
 *
 * 大厅与个人中心的页面数据都与「到期错题」无关（一个是输入框、一个是档案），
 * 为这一条提示去改那两个接口的契约，是让主数据背上一件它不关心的事。
 * 所以组件自己拉 `GET /users/me/reminders/today` —— 两个页面各自写一遍
 * 「判断要不要显示」的后果是，某天只改了其中一处。
 *
 * ## 拉不到就当没有
 *
 * 失败时**静默返回 `null`**，把页面推进错误态是错的：这一条是「顺带告诉你」，
 * 没有它页面依然完整（用户仍可从我的档案进复习提醒）。同理，
 * `snoozed_today`（今天已点过「今天先不复习」）与 `due_count` 为 0 都不显示
 * —— 方案 §8.5 明确要求当日不再提示。
 *
 * ## 刷新靠 `refreshKey`
 *
 * `useDidShow` 是页面级 hook，子组件拿不到。所以调用方在页面重新显示时
 * 递增一个计数传进来。不这么做的话，用户在大厅复习完再切回来，
 * 提示还挂着「今天有 3 道旧识在等你」。
 */

import { Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'

import { REMINDER_PROMPT_COPY } from '../../constants/copy'
import { fetchRemindersToday } from '../../services/reminders'
import { goPage } from '../../utils/navigation'
import Sprite from '../Sprite'

import './index.scss'

export interface ReminderPromptProps {
  /** 变化即重新拉取（页面在 `useDidShow` 里递增）。不传则只在挂载时拉一次 */
  refreshKey?: number | string
}

/** 有东西可提示时的两个数；`null` = 不显示这一条 */
interface PromptSummary {
  due: number
  minutes: number
}

export default function ReminderPrompt({ refreshKey }: ReminderPromptProps) {
  const [summary, setSummary] = useState<PromptSummary | null>(null)

  useEffect(() => {
    let alive = true

    fetchRemindersToday()
      .then((data) => {
        if (!alive) return
        const shouldShow = data.due_count > 0 && !data.snoozed_today
        setSummary(shouldShow ? { due: data.due_count, minutes: data.estimated_minutes } : null)
      })
      .catch(() => {
        // 见文件头：提醒拿不到不算错，页面照常
        if (alive) setSummary(null)
      })

    return () => {
      alive = false
    }
  }, [refreshKey])

  if (!summary) return null

  return (
    <View className='reminder-prompt' onClick={() => goPage('/pages/profile/reminder/index')}>
      {/* 鸢鸢负责「传递 / 提醒」这一语义域（00-设计规范） */}
      <Sprite name='yuanyuan' size={28} />

      <View className='reminder-prompt__tx'>
        <View className='reminder-prompt__title'>{REMINDER_PROMPT_COPY.title(summary.due)}</View>
        <View className='tiny'>{REMINDER_PROMPT_COPY.sub(summary.minutes)}</View>
      </View>

      {/* 实心胶囊（见 base.scss 的 `.pill.solid`）：这一条自己就是淡蓝底，
          `.pill.blue` 铺上去会和容器同色，整块胶囊消失 */}
      <Text className='pill solid'>{REMINDER_PROMPT_COPY.action}</Text>
    </View>
  )
}
