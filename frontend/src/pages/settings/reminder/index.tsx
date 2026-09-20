/**
 * 学习提醒设置（原型 07·6）。
 *
 * ## 为什么这一屏是「改完再按保存」，而 07·5 的开关是即时的
 *
 * 07·5 上那三个开关是**布尔量**：拨一下就有一个明确结果，等一次网络往返再动
 * 只会让人以为没点上。而这一屏是一组**互相有关**的字段（时间 / 星期 / 两个额外
 * 提醒），用户要来回比较「20:00 还是 22:00」—— 每点一下就提交，等于把还没定下的
 * 选择写进服务端，而且原型本来就在最下面给了「保存设置」这颗按钮。
 *
 * ## 提交的是**差异**，不是整份设置
 *
 * `save()` 里逐字段与基线比，改过的才进 patch。理由见 `services/settings.ts`：
 * 整份回传在两个页面同时开着时会盖掉对方。
 *
 * 保存成功后用**接口返回**更新基线，而不是 `reload()` —— `useAsyncData` 重新
 * 加载期间会**保留上一次的 `data`**，`reload()` 会让界面闪回保存前的样子，
 * 用户会以为没存上。
 *
 * ## 至少保留一天
 *
 * 服务端不接受空的 `reminder_days`（空集合等于「每天都不提醒」，与
 * `reminder_enabled` 表达同一件事却互相矛盾）。所以最后一个选中日**点不掉**，
 * 并且把原因说出来 —— 静默忽略一次点击，用户只会以为界面卡了。
 *
 * ## 「已开启 / 已关闭」那颗胶囊是可以点的
 *
 * 原型在这一屏只画了一颗状态胶囊，没有额外的开关控件，而图注写的是
 * 「默认开启但必须可关闭」。于是胶囊兼作开关，**整行都是热区** ——
 * 10.5px 的胶囊本身远不到 100rpx 的点击热区下限。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import Sprite from '../../../components/Sprite'
import { ARCHIVE_COMMON, SETTINGS_REMINDER_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchSettings, updateSettings } from '../../../services/settings'
import type { UserSettingsPublic, UserSettingsUpdateRequest } from '../../../types/api'

import './index.scss'

/** 这一屏管的 5 个字段（其余属于 07·5，不要在这一屏里顺手带上） */
type ReminderDraft = Pick<
  UserSettingsPublic,
  | 'reminder_enabled'
  | 'reminder_time'
  | 'reminder_days'
  | 'remind_streak_break'
  | 'remind_review_due'
>

/** 两个「额外提醒」开关的键 */
type ExtraKey = 'remind_streak_break' | 'remind_review_due'

/** 两个「额外提醒」开关的展示信息 —— 行为完全一致，共用一段渲染 */
const EXTRA_ROWS: ReadonlyArray<{ key: ExtraKey; label: string }> = [
  { key: 'remind_streak_break', label: SETTINGS_REMINDER_COPY.extraStreak },
  { key: 'remind_review_due', label: SETTINGS_REMINDER_COPY.extraReview }
]

function pickReminder(source: UserSettingsPublic): ReminderDraft {
  return {
    reminder_enabled: source.reminder_enabled,
    reminder_time: source.reminder_time,
    reminder_days: source.reminder_days,
    remind_streak_break: source.remind_streak_break,
    remind_review_due: source.remind_review_due
  }
}

/**
 * 星期集合是否相同。
 *
 * 服务端保证已排序，但**不能靠顺序**判断相等：`draft` 是本地拼出来的
 * （`[...days, day].sort()`），只要哪天排序逻辑变了，`[1,2]` 与 `[2,1]`
 * 就会被当成「改过了」而多发一个请求。
 */
function sameDays(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false
  const left = [...a].sort((x, y) => x - y)
  const right = [...b].sort((x, y) => x - y)
  return left.every((day, index) => day === right[index])
}

export default function SettingsReminderPage() {
  const { status, data, reload } = useAsyncData(() => fetchSettings())

  /** 改过但**还没保存**的字段 */
  const [draft, setDraft] = useState<Partial<ReminderDraft>>({})
  /** 已保存的基线；为 `null` 时基线就是进页面时读到的那份 */
  const [base, setBase] = useState<ReminderDraft | null>(null)
  const [saving, setSaving] = useState(false)

  if (!data) {
    return (
      <PhoneShell navTitle={SETTINGS_REMINDER_COPY.navTitle} screenClassName='settings-reminder'>
        {status === 'error' ? (
          <ArchiveState
            kind='error'
            title={SETTINGS_REMINDER_COPY.loadFailed}
            actionText={ARCHIVE_COMMON.retry}
            onAction={reload}
          />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  const baseline = base ?? pickReminder(data)
  /** 显示用：基线之上盖住本地改动 */
  const view: ReminderDraft = { ...baseline, ...draft }

  /** 记下一批改动 */
  const apply = (next: Partial<ReminderDraft>): void => {
    setDraft((prev) => ({ ...prev, ...next }))
  }

  /**
   * 两个额外提醒共用一次提交。
   *
   * 不写成 `apply({ [key]: value })`：计算属性名在 TS 里退化成
   * `{ [x: string]: boolean }`，既不能赋给 `Partial<ReminderDraft>`
   * （`reminder_days` 是数组），也要靠类型断言才写得过 —— 一个两分支的
   * 三元表达式比一次 `as` 更便宜。
   */
  const setExtra = (key: ExtraKey, value: boolean): void => {
    apply(
      key === 'remind_streak_break' ? { remind_streak_break: value } : { remind_review_due: value }
    )
  }

  const toggleDay = (day: number): void => {
    const selected = view.reminder_days.includes(day)
    if (selected && view.reminder_days.length === 1) {
      Taro.showToast({ title: SETTINGS_REMINDER_COPY.daysMinOne, icon: 'none' })
      return
    }
    const next = selected
      ? view.reminder_days.filter((item) => item !== day)
      : [...view.reminder_days, day].sort((a, b) => a - b)
    apply({ reminder_days: next })
  }

  const save = async (): Promise<void> => {
    if (saving) return

    const patch: UserSettingsUpdateRequest = {}
    if (view.reminder_enabled !== baseline.reminder_enabled) {
      patch.reminder_enabled = view.reminder_enabled
    }
    if (view.reminder_time !== baseline.reminder_time) {
      patch.reminder_time = view.reminder_time
    }
    if (!sameDays(view.reminder_days, baseline.reminder_days)) {
      patch.reminder_days = view.reminder_days
    }
    if (view.remind_streak_break !== baseline.remind_streak_break) {
      patch.remind_streak_break = view.remind_streak_break
    }
    if (view.remind_review_due !== baseline.remind_review_due) {
      patch.remind_review_due = view.remind_review_due
    }

    if (Object.keys(patch).length === 0) {
      Taro.showToast({ title: SETTINGS_REMINDER_COPY.unchanged, icon: 'none' })
      return
    }

    setSaving(true)
    try {
      const saved = await updateSettings(patch)
      setBase(pickReminder(saved))
      setDraft({})
      Taro.showToast({ title: SETTINGS_REMINDER_COPY.saved, icon: 'none' })
    } catch {
      // 失败时**保留** draft：用户的选择还留在界面上，再点一次保存就是重试
      Taro.showToast({ title: SETTINGS_REMINDER_COPY.saveFailed, icon: 'none' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <PhoneShell navTitle={SETTINGS_REMINDER_COPY.navTitle} screenClassName='settings-reminder'>
      {/* ---- 主卡：状态胶囊 + 一句说明（原型的 `.card.parch`）---- */}
      <View className='card parch'>
        <View
          className='between reminder-settings__head'
          onClick={() => apply({ reminder_enabled: !view.reminder_enabled })}
        >
          <Text className='reminder-settings__head-name'>
            {SETTINGS_REMINDER_COPY.sectionTitle}
          </Text>
          <Text className={`pill${view.reminder_enabled ? ' ok' : ''}`}>
            {view.reminder_enabled
              ? SETTINGS_REMINDER_COPY.enabled
              : SETTINGS_REMINDER_COPY.disabled}
          </Text>
        </View>

        <View className='row reminder-settings__intro'>
          <Sprite name='yuanyuan' size={58} />
          <View className='body sm reminder-settings__intro-copy'>
            {SETTINGS_REMINDER_COPY.intro}
          </View>
        </View>
      </View>

      {/* ---- 提醒时间：4 个固定时段（原型给了这 4 个 chip）---- */}
      <View className='card plain'>
        <View className='tiny reminder-settings__label'>{SETTINGS_REMINDER_COPY.timeLabel}</View>
        <View className='row reminder-settings__chips'>
          {SETTINGS_REMINDER_COPY.timeOptions.map((time) => (
            <Text
              key={time}
              className={`chip${view.reminder_time === time ? ' on' : ''}`}
              onClick={() => apply({ reminder_time: time })}
            >
              {time}
            </Text>
          ))}
        </View>
      </View>

      {/* ---- 提醒日：下标 + 1 即 1–7（周一–周日），与后端 `reminder_days` 同口径 ---- */}
      <View className='card plain'>
        <View className='tiny reminder-settings__label'>{SETTINGS_REMINDER_COPY.daysLabel}</View>
        <View className='row reminder-settings__chips reminder-settings__chips--days'>
          {SETTINGS_REMINDER_COPY.dayLabels.map((label, index) => {
            const day = index + 1
            return (
              <Text
                key={label}
                className={`chip${view.reminder_days.includes(day) ? ' on' : ''}`}
                onClick={() => toggleDay(day)}
              >
                {label}
              </Text>
            )
          })}
        </View>
      </View>

      {/* ---- 额外提醒：两个开关，形态与主卡的状态胶囊一致 ---- */}
      <View className='card plain'>
        <View className='tiny reminder-settings__label'>{SETTINGS_REMINDER_COPY.extraLabel}</View>
        {EXTRA_ROWS.map((row, index) => {
          const on = view[row.key]
          return (
            <View key={row.key}>
              {index > 0 && <View className='reminder-settings__gap' />}
              <View className='between' onClick={() => setExtra(row.key, !on)}>
                <Text className='body sm'>{row.label}</Text>
                <Text className={`pill${on ? ' ok' : ''}`}>
                  {on ? SETTINGS_REMINDER_COPY.extraOn : SETTINGS_REMINDER_COPY.extraOff}
                </Text>
              </View>
            </View>
          )
        })}
      </View>

      <View className='spacer' />

      <Button className='btn' disabled={saving} onClick={() => void save()}>
        {saving ? SETTINGS_REMINDER_COPY.saving : SETTINGS_REMINDER_COPY.save}
      </Button>
    </PhoneShell>
  )
}
