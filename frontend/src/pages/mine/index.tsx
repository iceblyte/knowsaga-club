/**
 * 我的档案 · 个人中心（原型 04·1）。
 *
 * 改造自 `ComingSoon` 占位页 —— 方案 §7.3 把它列在「改造 3 页」的第一项
 * （`pages/mine`：静态演示 → 真实个人中心）。
 *
 * ## 一个接口把整屏取回来
 *
 * 身份 + 等级进度 + 三宫格 + 三个入口的计数**全部来自 `GET /users/me`**。
 * 不拆成四个请求的理由很直接：这些数字在同一个屏幕上，拆开必然出现
 * 「昵称已经在了、等级还是空的」这类中间态，而用户看到的是界面在抽动。
 *
 * ## 与原型的一处必要差异：导览栏右侧的「设置」没有了
 *
 * 原型把「设置」放在导览栏右侧。全站已锁定「导览栏右侧不放文字」
 * （方案 §7.6 明确把「设置」「近 30 天」「6 / 18」「重做」「分享」「保存」
 * 全部列入要去掉的名单），所以这里连占位都不给 —— 标题居中由
 * `PhoneShell` 自己保留等宽空白来维持。
 *
 * 设置页（07·5）是 Phase E 的页面，本轮没有任何入口指向它，
 * 因此这里也不放一个「点了没反应」的设置按钮。历史卷轴那一行同理：
 * 入口**保留在版面上**（抽掉一行会让这一屏看起来像没做完），
 * 但点击时明说还没开放，而不是静默失败。
 *
 * ## 数字不在这里算
 *
 * 等级、下一级门槛、进度百分比、三宫格的三个统计值全部由服务端给
 * （`services/level_service.py` 与 `user_service.build_profile`）。
 * 前端若自己按 `xp_total` 再算一遍，某天后端调了曲线就会出现
 * 「个人中心写 Lv.3、结算页写 Lv.4」这种同一用户两个等级的情况。
 *
 * ## 每次重新显示都要刷新
 *
 * 这是标签页，页面实例在切走时**不会卸载**。刚打完一局副本再切回来，
 * 「闯关副本 12」必须变成 13 —— 只在挂载时取一次数据的话，用户会看到
 * 一个永远停在进页面那一刻的档案。所以在 `useDidShow` 里重取，
 * 并跳过首次（挂载时的那次请求已经由 `useAsyncData` 发起了）。
 */

import { Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useRef } from 'react'

import ArchiveState from '../../components/ArchiveState'
import Avatar from '../../components/Avatar'
import PhoneShell from '../../components/PhoneShell'
import { ARCHIVE_COMMON, COMMON_COPY, PROFILE_COPY } from '../../constants/copy'
import { useAsyncData } from '../../hooks/useAsyncData'
import { useTabPage } from '../../hooks/useTabPage'
import { fetchProfile } from '../../services/archive'
import { goPage } from '../../utils/navigation'
import { styleOf } from '../../utils/style'

import './index.scss'

export default function MinePage() {
  useTabPage('mine')

  const { status, data, reload } = useAsyncData(() => fetchProfile())

  // 首次（挂载时）跳过：那次刷新由 useAsyncData 自己完成，
  // 不跳过的话首屏会连发两个一模一样的请求
  const firstShowRef = useRef(true)
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false
      return
    }
    reload()
  })

  if (!data) {
    return (
      <PhoneShell navTitle={PROFILE_COPY.navTitle} showBack={false} reserveTabBar>
        {status === 'error' ? (
          <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  const { user, stats } = data
  const maxed = user.xp_to_next_level <= 0

  return (
    <PhoneShell navTitle={PROFILE_COPY.navTitle} showBack={false} reserveTabBar>
      {/* ---- 身份卡 ---- */}
      <View className='card gold'>
        <View className='row profile__who'>
          <Avatar avatarKey={user.avatar_key} avatarUrl={user.avatar_url} size={58} />

          <View className='profile__who-body'>
            {/* 块级换行：<Text> 默认 inline，两行会挤在同一行 */}
            <View className='profile__name'>{user.nickname}</View>
            <View className='row profile__pills'>
              <Text className='pill gold'>Lv.{user.level}</Text>
              <Text className='pill blue'>{user.level_title}</Text>
            </View>
          </View>
        </View>

        <View className='profile__gap-lg' />

        <View className='between'>
          <Text className='tiny'>
            {maxed
              ? PROFILE_COPY.levelMaxed
              : PROFILE_COPY.levelRemaining(user.level + 1, user.xp_to_next_level)}
          </Text>
          <Text className='tiny c-blue'>
            {PROFILE_COPY.xpFraction(user.xp_total, user.next_level_xp)}
          </Text>
        </View>

        <View className='profile__gap-sm' />

        <View className='bar blue'>
          <View style={styleOf({ width: `${user.level_progress}%` })} />
        </View>
      </View>

      {/* ---- 三宫格 ---- */}
      <View className='grid3'>
        <View className='card plain'>
          <View className='stat sm c-blue'>{stats.attempt_count}</View>
          <View className='statlab'>{PROFILE_COPY.statAttempts}</View>
        </View>
        <View className='card plain'>
          <View className='stat sm c-gold'>{user.xp_total}</View>
          <View className='statlab'>{PROFILE_COPY.statXp}</View>
        </View>
        <View className='card plain'>
          <View className='stat sm c-ok'>{stats.avg_accuracy}%</View>
          <View className='statlab'>{PROFILE_COPY.statAccuracy}</View>
        </View>
      </View>

      {/* ---- 三个入口 ----
          直接铺在纸板上、不套卡片：原型里这三行就是「账本横格行」
          （`.li` 自带虚线分隔），套一层卡片反而变成三张一模一样的圆角卡。 */}
      <View className='profile__rows'>
        <View className='li' onClick={() => goPage('/pages/profile/knowledge-tree/index')}>
          <View className='ico'>{PROFILE_COPY.iconTree}</View>
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowKnowledgeTree}</View>
            <View className='d'>{PROFILE_COPY.rowKnowledgeTreeDesc(stats.lit_kp_count)}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>

        {/* 历史卷轴属 Phase E：入口留着，点击明说还没开放 */}
        <View
          className='li'
          onClick={() => Taro.showToast({ title: COMMON_COPY.comingSoon, icon: 'none' })}
        >
          <View className='ico'>{PROFILE_COPY.iconScroll}</View>
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowScrolls}</View>
            <View className='d'>{PROFILE_COPY.rowScrollsDesc(stats.scroll_count)}</View>
          </View>
          <Text className='pill'>{stats.scroll_count}</Text>
        </View>

        <View className='li' onClick={() => goPage('/pages/profile/badges/index')}>
          <View className='ico'>{PROFILE_COPY.iconBadge}</View>
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowBadges}</View>
            <View className='d'>
              {PROFILE_COPY.rowBadgesDesc(stats.badge_unlocked, stats.badge_total)}
            </View>
          </View>
          <Text className='pill'>{stats.badge_unlocked}</Text>
        </View>
      </View>
    </PhoneShell>
  )
}
