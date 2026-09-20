/**
 * 冒险者卡片 · 公会卡（原型 04·2）。
 *
 * ## 这一屏不请求新接口
 *
 * 卡面上的每一个数字（等级、称号、副本数、正确率、连续天数、头像、昵称）
 * 都在 `GET /users/me` 里 —— 与 04·1 是同一份数据。单独再取一次会制造
 * 「列表页写 12、卡片写 11」的窗口期，而用户恰恰会把这两屏并排截图。
 *
 * ## 「保存公会卡」只在非 H5 出现（方案 §7.3）
 *
 * 小程序端走画布绘制 + 存相册（`utils/guildCard.ts`）；H5 没有
 * `saveImageToPhotosAlbum`，所以**整个按钮不渲染**，而不是渲染一个点了提示
 * 「请用小程序打开」的按钮 —— 那是个只有自己看得懂的出口。
 *
 * 画布是一块离屏的 `<Canvas>`，只在需要时被 `saveGuildCard()` 查询并绘制。
 * 它在 H5 分支下同样不渲染：那段代码永远不会执行，留一块空画布没有意义。
 *
 * ## 「分享给好友」按钮不假装自己能转发
 *
 * 微信的转发入口只在右上角「…」里，页面内的按钮点不出转发面板。
 * 所以它的职责是**指路**（`showShareMenu` + 一句「点右上角」），
 * 与冒险日志的分享按钮一致（见 `pages/report`）。
 *
 * ## 「加入第 N 天」可能没有
 *
 * `daysSinceJoin` 解析失败时返回 `0`，此时**整句不渲染** ——
 * 「加入第 0 天」比不写这一句更让人困惑。同理，解析失败不进画布。
 */

import { Button, Canvas, Text, View } from '@tarojs/components'
import Taro, { useShareAppMessage } from '@tarojs/taro'
import { useRef, useState } from 'react'

import { SPRITES } from '../../../assets/sprites'
import ArchiveState from '../../../components/ArchiveState'
import Avatar, { spriteNameForAvatarKey } from '../../../components/Avatar'
import PhoneShell from '../../../components/PhoneShell'
import {
  ARCHIVE_COMMON,
  CAREER_FALLBACK_KEY,
  CAREER_TENDENCY,
  PROFILE_CARD_COPY
} from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchProfile } from '../../../services/archive'
import { daysSinceJoin } from '../../../utils/datetime'
import { GUILD_CARD_CANVAS_ID, saveGuildCard, type GuildCardData } from '../../../utils/guildCard'
import { isH5 } from '../../../utils/platform'

import './index.scss'

export default function ProfileCardPage() {
  const { status, data, reload } = useAsyncData(() => fetchProfile())
  const [saving, setSaving] = useState(false)
  /** 连点保护：一次保存要画图 + 写相册，重复触发会产生多张重复图片 */
  const busyRef = useRef(false)

  /** 微信原生转发（与冒险日志同口径，见该页说明） */
  useShareAppMessage(() => ({
    title: PROFILE_CARD_COPY.shareTitle,
    path: '/pages/hall/index'
  }))

  if (!data) {
    return (
      <PhoneShell navTitle={PROFILE_CARD_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState
            kind='error'
            title={PROFILE_CARD_COPY.loadFailed}
            actionText={ARCHIVE_COMMON.retry}
            onAction={reload}
          />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  const { user, stats } = data
  const h5 = isH5()

  // 认不出的头像键退到与 `Avatar` 相同的兜底，避免「头像画学者、倾向写工匠」
  const tendency = CAREER_TENDENCY[user.avatar_key] ?? CAREER_TENDENCY[CAREER_FALLBACK_KEY]
  const joinDay = daysSinceJoin(user.created_at)

  /** 画布用的数据：值与标签都由这里给全，`guildCard.ts` 只负责画 */
  const card: GuildCardData = {
    nickname: user.nickname,
    level: user.level,
    levelTitle: user.level_title,
    stats: [
      { value: String(stats.attempt_count), label: PROFILE_CARD_COPY.statAttempts },
      { value: `${stats.avg_accuracy}%`, label: PROFILE_CARD_COPY.statAccuracy },
      { value: String(user.streak_days), label: PROFILE_CARD_COPY.statStreak }
    ],
    tendency: PROFILE_CARD_COPY.career(tendency),
    joinDay,
    avatarUrl: user.avatar_url,
    sprite: SPRITES[spriteNameForAvatarKey(user.avatar_key)],
    cardLabel: PROFILE_CARD_COPY.cardLabel
  }

  const handleSave = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setSaving(true)
    try {
      const result = await saveGuildCard(card)
      if (result.ok) {
        Taro.showToast({ title: PROFILE_CARD_COPY.saveOk, icon: 'success' })
        return
      }
      // 权限被拒与绘制失败要分开说：前者用户自己去开权限就能解决
      Taro.showToast({
        title: result.reason === 'permission' ? PROFILE_CARD_COPY.saveDenied : PROFILE_CARD_COPY.saveFailed,
        icon: 'none'
      })
    } finally {
      busyRef.current = false
      setSaving(false)
    }
  }

  const handleShare = () => {
    if (h5) {
      // H5 没有原生转发能力。给一个点了没反应的按钮比直说更糟
      Taro.showToast({ title: PROFILE_CARD_COPY.shareH5Hint, icon: 'none' })
      return
    }
    Taro.showShareMenu({ withShareTicket: true })
      .then(() => Taro.showToast({ title: PROFILE_CARD_COPY.shareGuide, icon: 'none' }))
      .catch(() => Taro.showToast({ title: PROFILE_CARD_COPY.shareGuide, icon: 'none' }))
  }

  return (
    <PhoneShell navTitle={PROFILE_CARD_COPY.navTitle} screenClassName='guild-card'>
      <View className='card parch'>
        <View className='guild-card__inner'>
          <Text className='tiny'>{PROFILE_CARD_COPY.cardLabel}</Text>

          <View className='guild-card__gap-lg' />

          <View className='row guild-card__avatar'>
            <Avatar avatarKey={user.avatar_key} avatarUrl={user.avatar_url} size={84} />
          </View>

          <View className='guild-card__name'>{user.nickname}</View>

          <View className='row guild-card__pills'>
            <Text className='pill gold'>Lv.{user.level}</Text>
            <Text className='pill blue'>{user.level_title}</Text>
          </View>

          <View className='guild-card__gap-lg' />

          <View className='grid3'>
            <View>
              <View className='stat sm'>{stats.attempt_count}</View>
              <View className='statlab'>{PROFILE_CARD_COPY.statAttempts}</View>
            </View>
            <View>
              <View className='stat sm'>{stats.avg_accuracy}%</View>
              <View className='statlab'>{PROFILE_CARD_COPY.statAccuracy}</View>
            </View>
            <View>
              <View className='stat sm'>{user.streak_days}</View>
              <View className='statlab'>{PROFILE_CARD_COPY.statStreak}</View>
            </View>
          </View>

          <View className='guild-card__gap-lg' />

          <View className='guild-card__divider' />

          <View className='row between guild-card__foot'>
            <Text className='tiny'>{PROFILE_CARD_COPY.career(tendency)}</Text>
            {joinDay > 0 ? (
              <Text className='tiny'>{PROFILE_CARD_COPY.joinDay(joinDay)}</Text>
            ) : null}
          </View>
        </View>
      </View>

      <View className='spacer' />

      {!h5 ? (
        <Button
          className={`btn${saving ? ' dis' : ''}`}
          disabled={saving}
          loading={saving}
          onClick={handleSave}
        >
          {saving ? PROFILE_CARD_COPY.saving : PROFILE_CARD_COPY.save}
        </Button>
      ) : null}

      <Button className='btn ghost' onClick={handleShare}>
        {PROFILE_CARD_COPY.share}
      </Button>

      {/* 离屏画布：只为导出存在，不参与版面（见 index.scss 的说明与文件头） */}
      {!h5 ? (
        <Canvas
          className='guild-card__canvas'
          id={GUILD_CARD_CANVAS_ID}
          canvasId={GUILD_CARD_CANVAS_ID}
          type='2d'
        />
      ) : null}
    </PhoneShell>
  )
}
