/**
 * 设置（原型 07·5）。
 *
 * ## 原型 8 行 + 方案要求新增的 1 行
 *
 * 第 1 行「头像与昵称」是方案 §7.4 明确要求新增的（原型没有这一屏），
 * 放在**最上方** —— 原型图注写「设置项按使用频率排序，把账号相关放在最下方」，
 * 换头像昵称是这一屏里频率最高的动作，所以它排在最前，而「账号与安全」不动。
 *
 * ## 开关为什么是「先改界面、再提交、失败翻回去」
 *
 * 开关是**零延迟**的控件：用户拨完就认为已经生效。等一次网络往返再动会让人
 * 以为没点上、于是再拨一次（发出两个相反的请求）。所以这里先改本地，
 * 提交失败时**把它翻回原状**并说一句「没保存成功」—— 界面最终停在服务端
 * 认可的那个状态，用户不会带着一个假的开关离开。
 *
 * ## 三个开关的落点
 *
 * `sound_enabled` / `auto_load_images` / `eye_care` 都是**用户偏好**，
 * 存在 `user_settings` 里、跨设备跟着账号走。本轮它们被记录与回显，
 * 但**不改变答题页的表现** —— 那是后续批次的事。所以这一屏没有假装
 * 「关掉音效就没声音了」的文案，行描述沿用原型原文。
 *
 * ## 「清理缓存」显示的是真实占用
 *
 * 需求 FR-D4 点名要求这一条。数据来自 `utils/cache.ts`（按字节真算），
 * 不是原型上的「12.6 MB」占位数字。见该文件的说明。
 *
 * ## 「账号与安全」的绑定状态由本端判定
 *
 * 服务端不暴露 `openid`（它是登录凭据，见 `models/user.py` 的说明），
 * 所以没有字段可以直接读。但账号**本来就是靠微信身份建立的**：
 * 小程序端走 `wx.login`，账号与微信一一对应；H5 是本地调试 / 预览，
 * 没有微信这一层。因此这里按平台给状态，而不是编一个「已绑定」。
 *
 * ## 昵称与账号编号取自**本地登录态快照**
 *
 * 这一屏只请求了 `/users/me/settings`，里面没有昵称。为两行弹层文案
 * 再去拉一次 `GET /users/me` 是多余的：`session.getUser()` 里就有
 * 登录 / 结算时写进去的那份快照，而昵称改名后也会立刻被 `updateUser` 更新。
 */

import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useCallback, useState } from 'react'

import ArchiveState from '../../components/ArchiveState'
import PhoneShell from '../../components/PhoneShell'
import { APP_COPY, ARCHIVE_COMMON, SETTINGS_COPY } from '../../constants/copy'
import { useAsyncData } from '../../hooks/useAsyncData'
import { getUser } from '../../services/session'
import { fetchSettings, updateSettings } from '../../services/settings'
import type { UserSettingsPublic } from '../../types/api'
import { cacheBytes, clearCache, formatBytes } from '../../utils/cache'
import { goPage } from '../../utils/navigation'
import { isH5 } from '../../utils/platform'

import './index.scss'

/** 三个可切换的开关 —— 值都是 `boolean`，所以能共用一个处理函数 */
type ToggleKey = 'sound_enabled' | 'auto_load_images' | 'eye_care'

/** 三行开关的图标 / 名称 / 描述（原型逐字） */
const TOGGLE_ROWS: ReadonlyArray<{
  key: ToggleKey
  icon: string
  name: string
  desc: string
}> = [
  {
    key: 'sound_enabled',
    icon: SETTINGS_COPY.iconSound,
    name: SETTINGS_COPY.rowSound,
    desc: SETTINGS_COPY.rowSoundDesc
  },
  {
    key: 'auto_load_images',
    icon: SETTINGS_COPY.iconTraffic,
    name: SETTINGS_COPY.rowTraffic,
    desc: SETTINGS_COPY.rowTrafficDesc
  },
  {
    key: 'eye_care',
    icon: SETTINGS_COPY.iconEye,
    name: SETTINGS_COPY.rowEye,
    desc: SETTINGS_COPY.rowEyeDesc
  }
]

export default function SettingsPage() {
  const { status, data, reload } = useAsyncData(() => fetchSettings())

  /**
   * 本地改动（含**还没被服务端确认**的）。
   *
   * 显示用 `{ ...data, ...draft }`：提交成功后**不删**这一项 ——
   * `data` 还是进页面时那份旧值，删掉会让开关自己跳回去。
   * 只有提交**失败**时才删，那正是「翻回去」这个动作。
   */
  const [draft, setDraft] = useState<Partial<UserSettingsPublic>>({})
  /** 正在提交的键：期间不接受同一行的第二次点击，避免发出两个相反的请求 */
  const [busyKey, setBusyKey] = useState<ToggleKey | null>(null)

  /**
   * 缓存占用。
   *
   * 用 `useState` 的惰性初值只算一次（同步读 Storage，没必要每次渲染都读）；
   * 清理之后手动重算。
   */
  const [cacheSize, setCacheSize] = useState(() => cacheBytes())

  const toggle = useCallback(
    async (key: ToggleKey, next: boolean) => {
      if (busyKey) return
      setBusyKey(key)
      setDraft((prev) => ({ ...prev, [key]: next }))

      try {
        await updateSettings({ [key]: next })
      } catch {
        setDraft((prev) => {
          const rolled = { ...prev }
          delete rolled[key]
          return rolled
        })
        Taro.showToast({ title: SETTINGS_COPY.switchFailed, icon: 'none' })
      } finally {
        setBusyKey(null)
      }
    },
    [busyKey]
  )

  const handleClearCache = () => {
    const removed = clearCache()
    setCacheSize(cacheBytes())
    Taro.showToast({ title: SETTINGS_COPY.cacheCleared(removed), icon: 'none' })
  }

  const showAccount = () => {
    const me = getUser()
    Taro.showModal({
      title: SETTINGS_COPY.accountTitle,
      content: [
        `${SETTINGS_COPY.accountNicknameLabel}：${me?.nickname ?? '—'}`,
        `${SETTINGS_COPY.accountIdLabel}：${me?.id ?? '—'}`,
        `${SETTINGS_COPY.accountBindingLabel}：${
          isH5() ? SETTINGS_COPY.accountUnbound : SETTINGS_COPY.accountBound
        }`
      ].join('\n'),
      showCancel: false,
      confirmText: SETTINGS_COPY.dismiss
    })
  }

  const showAbout = () => {
    Taro.showModal({
      title: SETTINGS_COPY.rowAbout,
      content: `${APP_COPY.name} v${APP_COPY.version}\n${APP_COPY.slogan}`,
      showCancel: false,
      confirmText: SETTINGS_COPY.dismiss
    })
  }

  if (!data) {
    return (
      <PhoneShell navTitle={SETTINGS_COPY.navTitle} screenClassName='settings'>
        {status === 'error' ? (
          <ArchiveState
            kind='error'
            title={SETTINGS_COPY.loadFailed}
            actionText={ARCHIVE_COMMON.retry}
            onAction={reload}
          />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  const view: UserSettingsPublic = { ...data, ...draft }
  const binding = isH5() ? SETTINGS_COPY.accountUnbound : SETTINGS_COPY.accountBound

  return (
    <PhoneShell navTitle={SETTINGS_COPY.navTitle} screenClassName='settings'>
      {/* ---- 1. 头像与昵称（方案 §7.4 新增，排在最上）---- */}
      <View className='li' onClick={() => goPage('/pages/settings/profile/index')}>
        <View className='ico'>{SETTINGS_COPY.iconProfile}</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_COPY.rowProfile}</View>
          <View className='d'>{SETTINGS_COPY.rowProfileDesc}</View>
        </View>
        <Text className='pill'>{SETTINGS_COPY.rowView}</Text>
      </View>

      {/* ---- 2. 学习提醒：这一行显示的是当前设置，不是开关 ---- */}
      <View className='li' onClick={() => goPage('/pages/settings/reminder/index')}>
        <View className='ico'>{SETTINGS_COPY.iconReminder}</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_COPY.rowReminder}</View>
          <View className='d'>
            {view.reminder_enabled
              ? SETTINGS_COPY.rowReminderOn(view.reminder_time)
              : SETTINGS_COPY.rowReminderOff}
          </View>
        </View>
        <Text className={`pill${view.reminder_enabled ? ' ok' : ''}`}>
          {view.reminder_enabled ? SETTINGS_COPY.switchOn : SETTINGS_COPY.switchOff}
        </Text>
      </View>

      {/* ---- 3–5. 三个开关 ---- */}
      {TOGGLE_ROWS.map((row) => {
        const on = view[row.key]
        return (
          <View
            key={row.key}
            className={`li${busyKey === row.key ? ' settings__row--busy' : ''}`}
            onClick={() => void toggle(row.key, !on)}
          >
            <View className='ico'>{row.icon}</View>
            <View className='tx'>
              <View className='n'>{row.name}</View>
              <View className='d'>{row.desc}</View>
            </View>
            {/* 颜色 + 文字双重表达（原型图注），不只依赖颜色 */}
            <Text className={`pill${on ? ' ok' : ''}`}>
              {on ? SETTINGS_COPY.switchOn : SETTINGS_COPY.switchOff}
            </Text>
          </View>
        )
      })}

      {/* ---- 6. 清理缓存：显示真实占用 ---- */}
      <View className='li' onClick={handleClearCache}>
        <View className='ico'>{SETTINGS_COPY.iconCache}</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_COPY.rowCache}</View>
          <View className='d'>{SETTINGS_COPY.cacheUsage(formatBytes(cacheSize))}</View>
        </View>
        <Text className='pill'>{SETTINGS_COPY.cacheAction}</Text>
      </View>

      {/* ---- 7. 账号与安全 ---- */}
      <View className='li' onClick={showAccount}>
        <View className='ico'>{SETTINGS_COPY.iconAccount}</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_COPY.rowAccount}</View>
          <View className='d'>{binding}</View>
        </View>
      </View>

      {/* ---- 8. 帮助与反馈 ---- */}
      <View className='li' onClick={() => goPage('/pages/settings/help/index')}>
        <View className='ico'>{SETTINGS_COPY.iconHelp}</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_COPY.rowHelp}</View>
          <View className='d'>{SETTINGS_COPY.rowHelpDesc}</View>
        </View>
      </View>

      {/* ---- 9. 关于 ---- */}
      <View className='li' onClick={showAbout}>
        <View className='ico'>{SETTINGS_COPY.iconAbout}</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_COPY.rowAbout}</View>
          <View className='d'>{SETTINGS_COPY.appVersion(APP_COPY.version)}</View>
        </View>
      </View>
    </PhoneShell>
  )
}
