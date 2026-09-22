/**
 * 勋章墙（原型 04·9）。
 *
 * ## 折叠态与展开态
 *
 * 原型这一屏只画了 8 枚（4 亮 4 灰）加一个「查看全部成就」按钮 —— 也就是说
 * 原型的墙是**预览**，全部成就另有一屏。本实现把「全部」做成同一页的展开态：
 *
 * - 折叠：8 枚（已解锁的排在前面，未解锁的补满），走原型的 4 列方格；
 * - 展开：全部 18 枚，换成账本行（`.li`）—— 因为每枚都要带上**解锁条件**，
 *   而 4 列方格里塞不下这句话（11px 的字在 60px 宽里会折成三行，行高参差）。
 *
 * ## 折叠态为什么不是「注册表前 8 枚」
 *
 * 原型的前 8 枚里恰好前 4 枚已解锁，所以看起来就是注册表顺序。真实数据下
 * 「已解锁的」不会刚好落在最前面 —— 一个只解锁了「卷轴百卷」的用户，
 * 按注册表顺序预览会看到 8 枚全灰，等于什么都没说。
 * 所以折叠态**已解锁优先**，两组内部各自保持注册表顺序（顺序本身仍不重排）。
 *
 * ## 未解锁的也带名称与条件
 *
 * 原型图注明确要求「保留轮廓与名称，让用户知道还有什么可追求」。
 * 全灰的圆点等于什么都没说，所以展开态必须给出条件。
 *
 * ## 勋章从「单字」换成了「图案」
 *
 * 后端 `BadgeItem.icon` 给的是一个汉字（「启」「连」「百」…），早期把它直接
 * 摆在圆底里 —— 18 枚并排时像一墙标签。现在统一走 `components/BadgeIcon`：
 * 缎带 + 圆盘 + 徽记的矢量图案（`scripts/generate_badge_icons.py` 生成，
 * 走 base64 data URI，H5 与微信两端都能画）。后端的单字**没有删**，
 * 它在图案缺失时作为兜底文字使用 —— 后端新增勋章不会在墙上留一个白洞。
 */

import { Button, Text, View } from '@tarojs/components'
import { useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import BadgeIcon, { artTier } from '../../../components/BadgeIcon'
import PhoneShell from '../../../components/PhoneShell'
import { ARCHIVE_COMMON, BADGES_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchBadges } from '../../../services/archive'
import type { BadgeItem } from '../../../types/api'
import { formatDateRelative } from '../../../utils/datetime'
import { styleOf } from '../../../utils/style'

import './index.scss'

/** 折叠态显示几枚（原型画的就是 8 枚） */
const PREVIEW_COUNT = 8

/** 已解锁的排前面；两组内部都保持注册表顺序（后端已按注册表顺序返回） */
function previewOrder(items: BadgeItem[]): BadgeItem[] {
  const unlocked = items.filter((item) => item.unlocked)
  const locked = items.filter((item) => !item.unlocked)
  return [...unlocked, ...locked].slice(0, PREVIEW_COUNT)
}

/**
 * 折叠态勋章尺寸。
 *
 * 取原型的 `medal(48)`（04·9 的方格用的是 48px 方图），**不是** `.badge` 的 62 ——
 * 62 是原型在「挑战副本」等页面上给圆形分数底定的尺寸，比这里的方格大一圈。
 * 早先照 62 摆的实测结果：4 列 × 72.8px + 3 × 14.04px = 333.3px，
 * 而卡片内容宽只有 308.1px → **第 4 列整列溢出卡片右边缘 25px**（被裁掉半个）。
 * 48px 对应 108rpx，列宽是 135rpx，留得下。
 */
const GRID_BADGE_SIZE = 48
/** 展开态账本行里的勋章尺寸 —— 比方格小一圈，和行高相称 */
const ROW_BADGE_SIZE = 30

export default function BadgesPage() {
  const { status, data, reload } = useAsyncData(() => fetchBadges())
  const [expanded, setExpanded] = useState(false)

  if (!data) {
    return (
      <PhoneShell navTitle={BADGES_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  const lockedCount = data.total - data.unlocked_count
  const progress = data.total > 0 ? Math.round((data.unlocked_count / data.total) * 100) : 0
  const shown = expanded ? data.items : previewOrder(data.items)

  return (
    <PhoneShell navTitle={BADGES_COPY.navTitle}>
      {/* ---- 进度 ---- */}
      <View className='card'>
        <View className='between'>
          <Text className='tiny'>{BADGES_COPY.unlockedLabel}</Text>
          <Text className='tiny c-gold'>{BADGES_COPY.progress(data.unlocked_count, data.total)}</Text>
        </View>

        <View className='badges__gap' />

        {/* 原型这里用的是稀有色的进度条 —— 勋章墙是全站唯一的「收藏」语义，
            用紫色把它和其它进度条区分开 */}
        <View className='bar rare'>
          <View style={styleOf({ width: `${progress}%` })} />
        </View>
      </View>

      {/* ---- 勋章 ---- */}
      <View className='card plain'>
        {expanded ? (
          <View className='stack tight'>
            {shown.map((item) => (
              <View className='li' key={item.key}>
                {/* 图案而不是单字：勋章是「收集品」，行里也该看到它本身 */}
                <BadgeIcon
                  badgeKey={item.key}
                  tier={artTier(item.unlocked, item.tier)}
                  size={ROW_BADGE_SIZE}
                  fallback={item.icon}
                />

                <View className='tx'>
                  <View className='n'>{item.name}</View>
                  <View className='d'>
                    {item.desc}
                    {item.unlocked && item.unlocked_at
                      ? ` · ${BADGES_COPY.unlockedAt(formatDateRelative(item.unlocked_at))}`
                      : ''}
                  </View>
                </View>

                <Text className={item.unlocked ? 'pill gold' : 'pill'}>
                  {item.unlocked ? BADGES_COPY.unlockedLabel : BADGES_COPY.lockedAt}
                </Text>
              </View>
            ))}
          </View>
        ) : (
          <View className='grid4 badges__grid'>
            {shown.map((item) => (
              <View className='badges__cell' key={item.key}>
                <View className='badges__cell-icon'>
                  {/* 与展开态同一套图案：两处各判一次档位就会出现
                      「格子是灰的、列表是金的」 */}
                  <BadgeIcon
                    badgeKey={item.key}
                    tier={artTier(item.unlocked, item.tier)}
                    size={GRID_BADGE_SIZE}
                    fallback={item.icon}
                  />
                </View>
                <Text className='tiny badges__name'>{item.name}</Text>
              </View>
            ))}
          </View>
        )}
      </View>

      <View className='spacer' />

      {lockedCount > 0 ? (
        <Button className='btn ghost' onClick={() => setExpanded((value) => !value)}>
          {expanded ? BADGES_COPY.collapse : BADGES_COPY.viewAll}
        </Button>
      ) : (
        <View className='tiny badges__all'>{BADGES_COPY.allUnlocked}</View>
      )}
    </PhoneShell>
  )
}
