/**
 * 我的档案 · 个人中心（原型 04·1）。
 *
 * 改造自 `ComingSoon` 占位页 —— 方案 §7.3 把它列在「改造 3 页」的第一项
 * （`pages/mine`：静态演示 → 真实个人中心）。
 *
 * ## 一个接口把整屏取回来
 *
 * 身份 + 等级进度 + 三宫格 + 各个入口的计数**全部来自 `GET /users/me`**。
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
 * ## 入口行从三行变成了五行
 *
 * 原型 04·1 只有三个入口行。Phase E 加了两行，两行都不是「顺手加的」：
 *
 * - **公会卡（04·2）**：它需要一个入口，而它既不该挤进导览栏，也不该把
 *   身份卡做成隐式按钮（原型的身份卡没有任何可点的暗示）。
 * - **设置（07·5）**：原型把「设置」长在导览栏右侧，而那一处已按全局口径
 *   去掉 —— 于是它在原型里唯一的位置没有了。设置是 Phase E 的页面，
 *   必须有一个**看得见**的入口，所以按其它入口行的做法落在这里。
 *
 * 历史卷轴（04·5 / 04·6）那一行也不再是占位：它已随 Phase E 落地，
 * 与知识树、勋章墙一样直接跳转。
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
 *
 * 在设置页换过头像或昵称之后回到这一屏，也靠它刷新 ——
 * 「设置里改完、个人中心还是旧的」是这类页面最典型的一种不一致。
 */

import { Text, View } from '@tarojs/components'
import { useDidShow } from '@tarojs/taro'
import { useRef, useState } from 'react'

import ArchiveState from '../../components/ArchiveState'
import Avatar from '../../components/Avatar'
import PhoneShell from '../../components/PhoneShell'
import ReminderPrompt from '../../components/ReminderPrompt'
import { ARCHIVE_COMMON, PROFILE_COPY } from '../../constants/copy'
import { useAsyncData } from '../../hooks/useAsyncData'
import { useTabPage } from '../../hooks/useTabPage'
import { fetchProfile } from '../../services/archive'
import { goPage } from '../../utils/navigation'
import { styleOf } from '../../utils/style'

import './index.scss'

export default function MinePage() {
  useTabPage('mine')

  const { status, data, reload } = useAsyncData(() => fetchProfile())

  /** 每次「重新显示」递增，透给页内提醒让它也重新判断该不该出现 */
  const [showSeq, setShowSeq] = useState(0)

  // 首次（挂载时）跳过：那次刷新由 useAsyncData 自己完成，
  // 不跳过的话首屏会连发两个一模一样的请求
  const firstShowRef = useRef(true)
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false
      return
    }
    reload()
    setShowSeq((value) => value + 1)
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
      {/* ---- 今日有到期错题的页内提示（方案 §8.5）----
          自己判断要不要出现：今日无到期错题、或今天已点过「今天先不复习」时它什么都不渲染 */}
      <ReminderPrompt refreshKey={showSeq} />

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

      {/* ---- 入口行 ----
          直接铺在纸板上、不套卡片：原型里这几行就是「账本横格行」
          （`.li` 自带虚线分隔），套一层卡片反而会变成几张一模一样的圆角卡。 */}
      <View className='profile__rows'>
        <View className='li' onClick={() => goPage('/pages/profile/knowledge-tree/index')}>
          <View className='ico'>{PROFILE_COPY.iconTree}</View>
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowKnowledgeTree}</View>
            <View className='d'>{PROFILE_COPY.rowKnowledgeTreeDesc(stats.lit_kp_count)}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>

        {/* 历史卷轴（04·5 / 04·6）已随 Phase E 落地，不再是「点了没反应」的占位 */}
        <View className='li' onClick={() => goPage('/pages/profile/scrolls/index')}>
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

        {/* 公会卡（04·2）。原型只有上面三行，这一行是 Phase E 新增的入口 ——
            04·2 需要一个入口，而把身份卡做成隐式按钮（原型没有任何可点的暗示）
            是另一种形式的不可发现。理由见 `PROFILE_COPY.rowCard` 的说明。 */}
        <View className='li' onClick={() => goPage('/pages/profile/card/index')}>
          <View className='ico'>{PROFILE_COPY.iconCard}</View>
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowCard}</View>
            <View className='d'>{PROFILE_COPY.rowCardDesc}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>

        {/* 设置（07·5）。原型的「设置」长在导览栏右侧，而那一处全站不放文字，
            所以它按其它入口行的做法落进这一列。理由见 `PROFILE_COPY.rowSettings`。 */}
        <View className='li' onClick={() => goPage('/pages/settings/index')}>
          <View className='ico'>{PROFILE_COPY.iconSettings}</View>
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowSettings}</View>
            <View className='d'>{PROFILE_COPY.rowSettingsDesc}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>
      </View>
    </PhoneShell>
  )
}
