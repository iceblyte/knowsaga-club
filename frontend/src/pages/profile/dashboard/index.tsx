/**
 * 数据看板（原型 04·3）。
 *
 * ## 版面与原型的一处必要差异
 *
 * 原型把「近 30 天」这个区间切换放在**导览栏右侧**。全站已锁定「导览栏右侧
 * 不放文字」（`PhoneShell` 的说明），所以切换控件落到页面里 ——
 * 位置选在**它真正影响的两张卡之前**（正确率 / 平均用时），而不是页面顶部。
 *
 * 原因是这个看板里有两种口径同时存在：
 *
 * - 柱状图恒为**最近 7 天**（原型图注：再密就不可读了），与区间无关；
 * - 正确率与平均用时按所选区间统计。
 *
 * 若把控件放在顶部，用户切到 30 天会以为柱子也该变多；放在两张卡之前，
 * 「下面这两项按此区间算」一目了然。领域掌握度是全量口径，所以排在控件之后、
 * 并且不随区间变化（它也不是「这段时间的掌握度」——掌握度是累计量）。
 *
 * ## 为什么把服务端的 0 显示成「—」
 *
 * 空窗口里 `accuracy` 与 `avg_duration_ms` 都是 0。直接渲染是
 * 「正确率 0% · 平均用时 0 秒」，读起来像考砸了，实际只是这段时间没来。
 * 靠 `range_has_data` 区分，见 `DASHBOARD_COPY.rangeEmpty` 的说明。
 */

import { Text, View } from '@tarojs/components'
import { useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import { ARCHIVE_COMMON, DASHBOARD_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchDashboard } from '../../../services/archive'
import type { DashboardRange } from '../../../types/api'
import { formatDuration } from '../../../utils/datetime'
import { goTab } from '../../../utils/navigation'
import { styleOf } from '../../../utils/style'

import './index.scss'

/** 柱高上限（占柱区高度的百分比）。原型最高柱 60px / 柱区 88px ≈ 68% */
const BAR_MAX_PERCENT = 68
/** 有数据但极小的一天，也至少留这么高，否则看起来像没有数据 */
const BAR_MIN_PERCENT = 7
/** 零答题的一天只留一个「刻度点」 */
const BAR_ZERO_PERCENT = 2

/** 掌握度分档：≥90 绿（已点亮同档），<60 朱砂，其余黄铜 —— 与原型三行样例一致 */
const LIT_THRESHOLD = 90
const LOW_THRESHOLD = 60

const RANGES: ReadonlyArray<{ value: DashboardRange; label: string }> = [
  { value: '7d', label: DASHBOARD_COPY.range7 },
  { value: '30d', label: DASHBOARD_COPY.range30 }
]

/** 一行环比文案 + 它的颜色类。`null`（无基准）不是 0，所以单独处理 */
interface DeltaLine {
  text: string
  className: string
}

function barsDelta(percent: number | null): DeltaLine {
  if (percent === null) return { text: DASHBOARD_COPY.deltaNoBaseline, className: '' }
  if (percent > 0) return { text: DASHBOARD_COPY.barsDeltaUp(percent), className: 'c-ok' }
  if (percent < 0) return { text: DASHBOARD_COPY.barsDeltaDown(percent), className: 'c-bad' }
  return { text: DASHBOARD_COPY.barsDeltaFlat, className: '' }
}

function accuracyDelta(points: number | null): DeltaLine {
  if (points === null) return { text: DASHBOARD_COPY.deltaNoBaseline, className: '' }
  if (points > 0) return { text: DASHBOARD_COPY.periodDeltaUp(points), className: 'c-ok' }
  if (points < 0) return { text: DASHBOARD_COPY.periodDeltaDown(points), className: 'c-bad' }
  return { text: DASHBOARD_COPY.periodDeltaFlat, className: '' }
}

function durationDelta(ms: number | null): DeltaLine {
  if (ms === null) return { text: DASHBOARD_COPY.deltaNoBaseline, className: '' }
  if (ms > 0) {
    return { text: DASHBOARD_COPY.periodSlower(formatDuration(ms)), className: 'c-bad' }
  }
  if (ms < 0) {
    return { text: DASHBOARD_COPY.periodFaster(formatDuration(-ms)), className: 'c-ok' }
  }
  return { text: DASHBOARD_COPY.periodDeltaFlat, className: '' }
}

function masteryBarClass(mastery: number): string {
  if (mastery >= LIT_THRESHOLD) return 'ok'
  if (mastery < LOW_THRESHOLD) return 'dash__domain-bar--low'
  return ''
}

function masteryTextClass(mastery: number): string {
  if (mastery >= LIT_THRESHOLD) return 'c-ok'
  if (mastery < LOW_THRESHOLD) return 'c-bad'
  return 'c-gold'
}

export default function DashboardPage() {
  const [range, setRange] = useState<DashboardRange>('7d')
  const { status, data, reload } = useAsyncData(() => fetchDashboard(range), range)

  if (!data) {
    // 首次加载 / 首次加载失败（重新加载时保留旧数据，不闪空）
    return (
      <PhoneShell navTitle={DASHBOARD_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState
            kind='error'
            actionText={ARCHIVE_COMMON.retry}
            onAction={reload}
          />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  if (!data.has_data) {
    return (
      <PhoneShell navTitle={DASHBOARD_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={DASHBOARD_COPY.emptyTitle}
          body={DASHBOARD_COPY.emptyBody}
          actionText={DASHBOARD_COPY.emptyCta}
          onAction={() => goTab('/pages/hall/index')}
        />
      </PhoneShell>
    )
  }

  const maxCount = Math.max(1, ...data.bars.map((bar) => bar.count))
  const lastIndex = data.bars.length - 1
  const barsLine = barsDelta(data.week_delta_percent)
  const accuracyLine = accuracyDelta(data.accuracy_delta)
  const durationLine = durationDelta(data.duration_delta_ms)

  return (
    <PhoneShell navTitle={DASHBOARD_COPY.navTitle}>
      {/* 近 7 天答题量：柱子恒为 7 根，与区间无关 */}
      <View className='card'>
        <View className='between'>
          <Text className='tiny'>{DASHBOARD_COPY.barsTitle}</Text>
          <Text className={`tiny ${barsLine.className}`}>{barsLine.text}</Text>
        </View>

        <View className='dash__gap' />

        <View className='dash__bars'>
          {data.bars.map((bar, index) => {
            const height =
              bar.count > 0
                ? Math.max(BAR_MIN_PERCENT, Math.round((bar.count / maxCount) * BAR_MAX_PERCENT))
                : BAR_ZERO_PERCENT
            const barCls = [
              'dash__bar',
              // 今天那根用主色，其余用浅色 —— 原型把「当前」那一根挑出来
              index === lastIndex ? 'dash__bar--today' : '',
              bar.count === 0 ? 'dash__bar--zero' : ''
            ]
              .filter(Boolean)
              .join(' ')

            return (
              <View className='dash__col' key={bar.date}>
                <View className={barCls} style={styleOf({ height: `${height}%` })} />
                <Text className='tiny dash__bar-label'>{bar.label}</Text>
              </View>
            )
          })}
        </View>
      </View>

      {/* 区间切换：只影响下面两张卡 */}
      <View className='row dash__range'>
        {RANGES.map((item) => (
          <Text
            key={item.value}
            className={`chip dash__range-item${range === item.value ? ' dash__range-item--on' : ''}`}
            onClick={() => setRange(item.value)}
          >
            {item.label}
          </Text>
        ))}
      </View>

      <View className='grid2'>
        <View className='card plain'>
          <View className='tiny'>{DASHBOARD_COPY.accuracyTitle}</View>
          <View className={`stat sm c-ok dash__stat`}>
            {data.range_has_data ? `${data.accuracy}%` : DASHBOARD_COPY.rangeEmptyValue}
          </View>
          <View className='tiny dash__delta'>
            {data.range_has_data ? accuracyLine.text : DASHBOARD_COPY.rangeEmpty}
          </View>
        </View>

        <View className='card plain'>
          <View className='tiny'>{DASHBOARD_COPY.durationTitle}</View>
          <View className='stat sm c-blue dash__stat'>
            {data.range_has_data ? formatDuration(data.avg_duration_ms) : DASHBOARD_COPY.rangeEmptyValue}
          </View>
          <View className='tiny dash__delta'>
            {data.range_has_data ? durationLine.text : DASHBOARD_COPY.rangeEmpty}
          </View>
        </View>
      </View>

      <View className='card plain'>
        <View className='tiny dash__domains-title'>{DASHBOARD_COPY.domainsTitle}</View>

        {data.domains.length === 0 ? (
          <View className='tiny'>{DASHBOARD_COPY.domainsEmpty}</View>
        ) : (
          <View className='stack tight'>
            {data.domains.map((domain) => (
              <View key={domain.name}>
                <View className='between'>
                  <Text className='tiny'>{domain.name}</Text>
                  <Text className={`tiny ${masteryTextClass(domain.mastery)}`}>
                    {domain.mastery}%
                  </Text>
                </View>
                <View className={`bar ${masteryBarClass(domain.mastery)}`}>
                  <View style={styleOf({ width: `${domain.mastery}%` })} />
                </View>
              </View>
            ))}
          </View>
        )}
      </View>
    </PhoneShell>
  )
}
