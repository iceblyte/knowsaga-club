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
 * 原型 04·1 只有三个入口行。另外两行都不是「顺手加的」，每一行都补掉了
 * 一个**在原型里无处安放**的页面：
 *
 * - **错题本（04·7）**：原型的标签栏把 04·7 划给「我的」，但它不在
 *   04·1 的入口列表里 —— 于是它在原型里只能靠「今日有到期错题」的页内
 *   提醒进入。那意味着没有到期错题的用户永远打不开这一页，
 *   而错题本恰恰是最该随时能看的一页。
 * - **公会卡（04·2）**：它需要一个入口，而它既不该挤进导览栏，也不该把
 *   身份卡做成隐式按钮（原型的身份卡没有任何可点的暗示）。
 * - **设置（07·5）**：原型把「设置」长在导览栏右侧，而那一处已按全局口径
 *   去掉 —— 于是它在原型里唯一的位置没有了。设置是 Phase E 的页面，
 *   必须有一个**看得见**的入口，所以按其它入口行的做法落在这里。
 *
 * 知识树与勋章墙仍按原型直接跳转。
 *
 * ## 「历史卷轴」那一行已被移除（本轮修复第 7 条）
 *
 * 原型这里有一行「历史卷轴」（04·5）。它与标签页「冒险日志」是同一件东西的
 * 两个入口 —— 两处都列同一份 `attempts`、都跳 `profile/scroll-detail`。
 * 现在「冒险日志」标签页自己在顶部列出全部日志供选择，这一行就成了同一个
 * 列表的第二个副本，所以去掉。`pages/profile/scrolls/index` 这个路由**没有删**：
 * 报告页的断网态与全局断网页的「查看历史日志」仍然指向它，它依旧可达。
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
 *
 * ## 身份卡现在可以点（本轮修复）
 *
 * 原来改头像/昵称只有一条路：往下滚到入口列 → 设置 → 头像与昵称，两跳。
 * 用户看到自己的头像与昵称，第一反应是**点它** —— 点了没反应，就以为
 * 这个功能没做。现在整行可点，直接进 07·4；右上角补一颗「编辑」胶囊
 * 把「可点」这件事说出来（可点本身没有视觉暗示）。
 *
 * ## 入口行为什么走 `navigate` 而不是 `redirect`（本轮修复）
 *
 * 这一页是**标签页**，也就是页面栈的根。原来这些入口用的是默认的
 * `redirectTo` —— 它会把当前页关掉，于是栈里只剩子页面一页。
 * 子页面的返回键 `navigateBack` 找不到上一页，兜底逻辑就把用户
 * **送回了社团大厅**（看起来像「返回按钮坏了」）。
 * 改 `navigate` 后栈是「我的 → 子页面」，返回就是回到这一屏。
 */

import { Image, Text, View } from '@tarojs/components'
import { useDidShow } from '@tarojs/taro'
import { useRef, useState } from 'react'

import ArchiveState from '../../components/ArchiveState'
import Avatar from '../../components/Avatar'
import PhoneShell from '../../components/PhoneShell'
import ReminderPrompt from '../../components/ReminderPrompt'
import { PROFILE_ICONS, type ProfileIconName } from '../../assets/profile-icons'
import { ARCHIVE_COMMON, PROFILE_COPY } from '../../constants/copy'
import { useAsyncData } from '../../hooks/useAsyncData'
import { useTabPage } from '../../hooks/useTabPage'
import { fetchProfile } from '../../services/archive'
import { goPage } from '../../utils/navigation'
import { squareStyle, styleOf } from '../../utils/style'

import './index.scss'

/**
 * 入口行图标在 28px 方块里的实际绘制尺寸（原型 px）。
 *
 * 方块是 `$size-li-ico`（28 × 2.259 ≈ 63rpx），图标留一圈内边距 ——
 * 顶满会让六个图标在视觉上比原来的汉字重得多。18 × 2.259 ≈ 41rpx。
 */
const ROW_ICON_RPX = 41

/** 入口行左侧的图标方块。底色与尺寸都仍由全局 `.ico` 给，这里只换里面的孩子。 */
function RowIcon({ name }: { name: ProfileIconName }) {
  return (
    <View className='ico'>
      <Image
        className='profile__row-ico'
        src={PROFILE_ICONS[name]}
        mode='aspectFit'
        style={squareStyle(ROW_ICON_RPX)}
      />
    </View>
  )
}

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

  /**
   * 身份卡 → 07·4「头像与昵称」。
   *
   * 用 `navigate`（不是默认的 `redirect`）：这一页是标签页、是页面栈的根，
   * `redirectTo` 会把它一起关掉，子页面的返回键就没有上一页可回 ——
   * 表现就是「点左上角返回，直接回到了社团大厅」。
   */
  const goEditIdentity = () => goPage('/pages/settings/profile/index', 'navigate')

  return (
    <PhoneShell navTitle={PROFILE_COPY.navTitle} showBack={false} reserveTabBar>
      {/* ---- 今日有到期错题的页内提示（方案 §8.5）----
          自己判断要不要出现：今日无到期错题、或今天已点过「今天先不复习」时它什么都不渲染 */}
      <ReminderPrompt refreshKey={showSeq} />

      {/* ---- 身份卡 ---- */}
      <View className='card gold'>
        {/* 整行可点：点头像或昵称就能改（见文件头「身份卡现在可以点」）。
            右侧的「编辑」胶囊把「可点」这件事说出来 —— 只给热区不给暗示，
            用户仍然不会去点。 */}
        <View className='row profile__who' onClick={goEditIdentity}>
          <Avatar avatarKey={user.avatar_key} avatarUrl={user.avatar_url} size={58} />

          <View className='profile__who-body'>
            {/* 块级换行：<Text> 默认 inline，两行会挤在同一行 */}
            <View className='profile__name'>{user.nickname}</View>
            <View className='row profile__pills'>
              <Text className='pill gold'>Lv.{user.level}</Text>
              <Text className='pill blue'>{user.level_title}</Text>
            </View>
          </View>

          {/* 这一颗是**动作**不是状态（同页其它 `.pill` 都是状态：Lv.3 / 见习冒险者），
              所以走 `.pill.solid` 的实心蓝，与「查看」那几行的淡底胶囊区分开 */}
          <Text className='pill solid profile__edit'>{PROFILE_COPY.editIdentity}</Text>
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
        <View
          className='li'
          onClick={() => goPage('/pages/profile/knowledge-tree/index', 'navigate')}
        >
          <RowIcon name='knowledgeTree' />
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowKnowledgeTree}</View>
            <View className='d'>{PROFILE_COPY.rowKnowledgeTreeDesc(stats.lit_kp_count)}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>

        {/* 错题本（04·7）。原型把这一屏划给「我的」却没有给它入口行，
            于是没有到期错题的时期它整页不可达 —— 理由见 `PROFILE_COPY.rowReview`。 */}
        <View className='li' onClick={() => goPage('/pages/profile/review/index', 'navigate')}>
          <RowIcon name='review' />
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowReview}</View>
            <View className='d'>{PROFILE_COPY.rowReviewDesc}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>

        {/* ⚠️ 原型的「历史卷轴」（04·5）这一行**已被移除**（本轮修复第 7 条）。
            它与标签页「冒险日志」是同一件东西的两个入口：两处都列同一个
            `attempts` 列表、都跳 `profile/scroll-detail`。现在「冒险日志」标签页
            自己在顶部列出全部日志供选择，这里再放一行就是同一个列表的第二个副本。
            `pages/profile/scrolls/index` 这个路由**没有删** —— 报告页的断网态
            与全局断网页的「查看历史日志」仍然指向它，它依旧可达。 */}

        <View className='li' onClick={() => goPage('/pages/profile/badges/index', 'navigate')}>
          <RowIcon name='badges' />
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
        <View className='li' onClick={() => goPage('/pages/profile/card/index', 'navigate')}>
          <RowIcon name='card' />
          <View className='tx'>
            <View className='n'>{PROFILE_COPY.rowCard}</View>
            <View className='d'>{PROFILE_COPY.rowCardDesc}</View>
          </View>
          <Text className='pill'>{PROFILE_COPY.rowView}</Text>
        </View>

        {/* 设置（07·5）。原型的「设置」长在导览栏右侧，而那一处全站不放文字，
            所以它按其它入口行的做法落进这一列。理由见 `PROFILE_COPY.rowSettings`。 */}
        <View className='li' onClick={() => goPage('/pages/settings/index', 'navigate')}>
          <RowIcon name='settings' />
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
