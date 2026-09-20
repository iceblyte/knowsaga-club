/**
 * 冒险日志 · 主视图（原型 03 第 1 屏，另含生成中与失败态）。
 *
 * ## 这一页是标签页，所以没有返回键
 *
 * 原型第 1 屏画了 `‹`，但 `pages/report/index` 在 `app.config.ts` 里是
 * tabBar 的第 3 项 —— 标签页没有「上一页」可回。给一个按不动的返回键
 * 比不给更糟，所以 `showBack={false}`，与原型的其它标签页保持一致。
 *
 * ## 统计数字全部来自服务端，前端不重算
 *
 * 「答对 4 / 5」「8.4s」「超过 72%」分别直接读 `correct_count`/`total_count`、
 * `avg_seconds_per_question`、`percentile`。理由：报告页与结算页必须**逐位相同**，
 * 而两处各算一遍迟早会因为一处改了规则而对不上（见 `backend/app/models/report.py`）。
 *
 * ## 报告的三种来源，以及为什么都不隐瞒
 *
 * | 来源 | 界面表现 |
 * |---|---|
 * | 服务端已有报告（复用） | 直接展示 |
 * | 服务端新生成（AI） | 展示 |
 * | 服务端 AI 全失败 → 确定性模板 | 展示，并在下方补一行**诚实说明** |
 *
 * 第三种的说明文案是刻意的：模板报告读起来明显更「制式」，
 * 不说清会让用户以为 AI 就这个水平，进而对产品失去信心。
 *
 * ## 断网与生成失败必须分开
 *
 * 「连不上服务器」与「服务器说这次生成失败了」的下一步动作不同：
 * 前者要检查网络重连，后者要重新生成报告。合成一个「出错了」的提示，
 * 用户就不知道该做什么（而原型的图注明确要求给出具体原因与动作）。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow, useShareAppMessage } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import AccuracyRing from '../../components/AccuracyRing'
import MagicStage from '../../components/MagicStage'
import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { CLIENT_ERROR_CODE } from '../../constants/api'
import { REPORT_COPY, REPORT_ERROR_TEXT } from '../../constants/copy'
import { useTabPage } from '../../hooks/useTabPage'
import { createReportTask } from '../../services/report'
import { pollTask } from '../../services/quiz'
import { ApiError } from '../../services/request'
import { useReportStore } from '../../store/useReportStore'
import { useQuizStore } from '../../store/useQuizStore'
import type { StepStatus, TaskRecord, TaskStep } from '../../types/api'
import { formatDate, formatDuration, formatSeconds } from '../../utils/datetime'
import { goPage, goTab } from '../../utils/navigation'
import { isH5 } from '../../utils/platform'
import { styleOf } from '../../utils/style'

import './index.scss'

/** 后端还没回第一个状态时的本地兜底（名字与 `report_service._initial_steps` 一致） */
const FALLBACK_STEPS: TaskStep[] = [
  { key: 'review', name: '回看这次作答', status: 'pending', detail: '准备中' },
  { key: 'compose', name: '撰写复盘报告', status: 'pending', detail: '等待中' }
]

const STEP_PILL: Record<StepStatus, { text: string; cls: string } | null> = {
  done: { text: '完成', cls: '' },
  running: { text: '进行中', cls: 'blue' },
  failed: { text: '失败', cls: 'bad' },
  pending: null
}

/** 把后端给的错误码翻成报告语境的文案（见 `REPORT_ERROR_TEXT` 的说明） */
function reportFailureText(code: number, fallback: string): string {
  return REPORT_ERROR_TEXT[code] || fallback || REPORT_COPY.failedBody
}

export default function ReportPage() {
  useTabPage('report')

  const attemptId = useReportStore((s) => s.attemptId)
  const report = useReportStore((s) => s.report)
  const status = useReportStore((s) => s.status)
  const message = useReportStore((s) => s.message)
  const begin = useReportStore((s) => s.begin)

  const [task, setTask] = useState<TaskRecord | null>(null)
  /** 递增即「再跑一轮」。重试与被中断后恢复都靠它 */
  const [runToken, setRunToken] = useState(0)

  /** 本轮是否要求强制重新生成（点「重新生成报告」时为 true） */
  const forceRef = useRef(false)
  /** 页面是否还活着 */
  const aliveRef = useRef(true)

  /**
   * 每次页面显示时决定「要不要开跑」。
   *
   * 三件事都在这里定：目标那一局是谁、旧报告要不要丢、以及是否需要重新发起生成。
   * 放在 `useDidShow` 而不是 `useEffect` 里，是因为**从总结页返回时也走这里** ——
   * 用 `useEffect([])` 只能覆盖首次挂载，返回时不会再跑。
   */
  useDidShow(() => {
    const store = useReportStore.getState()
    // 结算页会把这一局的 id 写进 store；直接进标签页时退回「本局」——它们通常是同一局
    const target = store.attemptId || useQuizStore.getState().attempt?.attempt_id || ''
    if (!target) return

    if (target !== store.attemptId) {
      // 目标换了（打了新的一局）→ 丢掉旧报告，否则会出现
      // 「标题是新卷轴、数字是旧一局」这种最难被发现的错配
      store.begin(target)
    } else if (store.status === 'generating') {
      // 上次离开时轮询随页面卸载停止了 → 必须重开，
      // 否则永远停在「生成中」：一个不会自己结束的等待页
      store.begin(target)
    }

    if (useReportStore.getState().status === 'idle') {
      setRunToken((value) => value + 1)
    }
  })

  useEffect(() => {
    aliveRef.current = true

    const store = useReportStore.getState()
    if (!store.attemptId || store.status !== 'idle') {
      return () => {
        aliveRef.current = false
      }
    }

    const target = store.attemptId
    const force = forceRef.current
    forceRef.current = false

    store.startGenerating()

    const run = async () => {
      try {
        const created = await createReportTask({ attempt_id: target, force })
        if (!aliveRef.current) return

        const final = await pollTask({
          taskId: created.task_id,
          intervalMs: created.poll_interval_ms,
          onUpdate: (next) => {
            if (aliveRef.current) setTask(next)
          },
          shouldContinue: () => aliveRef.current
        })
        if (!aliveRef.current) return

        if (final.status === 'succeeded' && final.report) {
          useReportStore.getState().succeed(final.report)
          return
        }
        if (final.status === 'failed') {
          useReportStore
            .getState()
            .fail(
              reportFailureText(
                final.error?.code ?? CLIENT_ERROR_CODE.BAD_RESPONSE,
                final.error?.message ?? ''
              )
            )
          return
        }
        // cancelled：本页没有取消入口，这里按「没拿到」处理，让用户能重试
        useReportStore.getState().fail(REPORT_COPY.failedBody)
      } catch (error) {
        if (!aliveRef.current) return
        // 连不上服务器 ≠ 服务器说生成失败。两者的下一步动作不同，
        // 所以这里分成两种界面状态，而不是合成一句「出错了」
        if (error instanceof ApiError && error.code === CLIENT_ERROR_CODE.NETWORK) {
          useReportStore.getState().goOffline(error.message)
          return
        }
        if (error instanceof ApiError) {
          useReportStore.getState().fail(reportFailureText(error.code, error.message))
          return
        }
        useReportStore.getState().fail(REPORT_COPY.failedBody)
      }
    }

    run()

    return () => {
      aliveRef.current = false
    }
  }, [runToken])

  /** 微信原生转发（MVP 不做 Canvas 海报，见开发计划 §3.7） */
  useShareAppMessage(() => ({
    title: REPORT_COPY.shareTitle,
    path: '/pages/hall/index'
  }))

  const topic = report?.quiz_title || ''

  // ---------------------------------------------------------------------------
  // 交互
  // ---------------------------------------------------------------------------
  const handleShare = () => {
    if (isH5()) {
      // H5 没有原生转发能力。给一个点了没反应的按钮比直说更糟
      Taro.showToast({ title: REPORT_COPY.shareH5Hint, icon: 'none' })
      return
    }
    // 转发入口只在微信右上角，页面里点不出来 —— 所以按钮的职责是
    // 「打开分享菜单 + 告诉用户去哪点」，而不是假装自己能转发
    Taro.showShareMenu({ withShareTicket: true })
      .then(() => Taro.showToast({ title: REPORT_COPY.shareGuide, icon: 'none' }))
      .catch(() => Taro.showToast({ title: REPORT_COPY.shareGuide, icon: 'none' }))
  }

  const handleRetry = () => {
    // 「重新生成报告」字面就是「重写一份」，所以带上 force：
    // 否则一旦库里还留着一份可用的旧报告，用户点了重试却看到同一份，
    // 会以为按钮坏了
    forceRef.current = true
    begin(attemptId)
    setRunToken((value) => value + 1)
  }

  const handleReconnect = () => {
    begin(attemptId)
    setRunToken((value) => value + 1)
  }

  // ---------------------------------------------------------------------------
  // 空态：本地没有可复盘的一局
  // ---------------------------------------------------------------------------
  if (!attemptId) {
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report report--center'
      >
        <View className='spacer' />
        <View className='report__center'>
          <MagicStage size={150} spriteSize={64} sprite='momo' spriteMotion='floaty' />
          <View className='report__center-text'>
            <Text className='h'>{REPORT_COPY.emptyTitle}</Text>
            <Text className='sub report__center-desc'>{REPORT_COPY.emptyBody}</Text>
          </View>
        </View>
        <View className='spacer' />
        <Button className='btn ghost' onClick={() => goTab('/pages/hall/index')}>
          {REPORT_COPY.backToHall}
        </Button>
      </PhoneShell>
    )
  }

  // ---------------------------------------------------------------------------
  // 生成中
  // ---------------------------------------------------------------------------
  if (status === 'generating' || status === 'idle') {
    const steps = task?.steps?.length ? task.steps : FALLBACK_STEPS
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report report--center'
      >
        <View className='spacer' />
        <View className='report__center'>
          <MagicStage size={150} spriteSize={64} sprite='momo' spriteMotion='floaty' />
          <View className='report__center-text'>
            <Text className='h'>{REPORT_COPY.generatingTitle}</Text>
            <Text className='sub report__center-desc'>{REPORT_COPY.generatingHint}</Text>
          </View>
          <View className='bar blue report__bar'>
            <View style={styleOf({ width: `${task?.progress ?? 0}%` })} />
          </View>
        </View>
        <View className='spacer' />

        {/* 步骤的名字 / 详情 / 状态全部来自后端，前端一个都不自己编 */}
        <View className='card plain'>
          {steps.map((step, index) => {
            const pill = STEP_PILL[step.status]
            return (
              <View key={step.key}>
                {index > 0 && <View className='report__step-gap' />}
                <View className='li'>
                  <View className='ico'>{index + 1}</View>
                  <View className='tx'>
                    <View className='n'>{step.name}</View>
                    <View className='d'>{step.detail}</View>
                  </View>
                  {pill && (
                    <Text className={`pill${pill.cls ? ` ${pill.cls}` : ''}`}>{pill.text}</Text>
                  )}
                </View>
              </View>
            )
          })}
        </View>
      </PhoneShell>
    )
  }

  // ---------------------------------------------------------------------------
  // 断网（原型 03 第 7 屏）
  // ---------------------------------------------------------------------------
  if (status === 'offline') {
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report report--center'
      >
        <View className='spacer' />
        <View className='report__center'>
          <Sprite name='shishi' size={96} />
          <View className='report__center-text'>
            <Text className='h'>{REPORT_COPY.offlineTitle}</Text>
            <Text className='body sm report__center-desc'>{message || REPORT_COPY.offlineBody}</Text>
          </View>
        </View>
        <View className='spacer' />
        <Button className='btn' onClick={handleReconnect}>
          {REPORT_COPY.reconnect}
        </Button>
        {/* 「查看历史日志」按其字面跳**历史卷轴**（04·5），与全局断网页
            `pages/exception/index` 的同名按钮一致。
            原来这里跳的是大厅 —— 文案与动作对不上（按钮名实不符）。
            用 `navigate` 保留本页：断网时用户多半只是想确认「记录还在不在」，
            看完要能退回来重连；历史卷轴在断网时显示自己的失败态与「重新加载」。 */}
        <Button
          className='btn ghost report__secondary'
          onClick={() => goPage('/pages/profile/scrolls/index', 'navigate')}
        >
          {REPORT_COPY.viewHistory}
        </Button>
      </PhoneShell>
    )
  }

  // ---------------------------------------------------------------------------
  // 生成失败（原型 03 第 6 屏）
  // ---------------------------------------------------------------------------
  if (status === 'failed' || !report) {
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report report--center'
      >
        <View className='spacer' />
        <View className='report__center'>
          <Sprite name='shishi' size={96} />
          <View className='report__center-text'>
            <Text className='h'>{REPORT_COPY.failedTitle}</Text>
            <Text className='body sm report__center-desc'>{message || REPORT_COPY.failedBody}</Text>
          </View>
        </View>
        <View className='spacer' />
        <Button className='btn' onClick={handleRetry}>
          {REPORT_COPY.regenerate}
        </Button>
        {/* 「先看看答题详情」= 去这一局的卷轴详情（04·6）。
            报告失败**不影响**这一局的作答记录：交卷那一刻记录就已经落库，
            报告只是它上面的一层解读。所以这里的出口必须是真的能走的 ——
            原先只弹一句「答题详情还没开放」是 Phase D 交付 04·6 之前的事。
            用 `navigate` 而不是 `redirect`：用户看完详情还能返回这里重试生成。 */}
        <Button
          className='btn ghost report__secondary'
          onClick={() =>
            goPage(`/pages/profile/scroll-detail/index?attempt_id=${attemptId}`, 'navigate')
          }
        >
          {REPORT_COPY.viewDetails}
        </Button>
      </PhoneShell>
    )
  }

  // ---------------------------------------------------------------------------
  // 主视图（原型 03 第 1 屏）
  // ---------------------------------------------------------------------------
  const finishedLabel = formatDate(report.finished_at)

  return (
    <PhoneShell
      navTitle={REPORT_COPY.navTitle}
      showBack={false}
      reserveTabBar
      screenClassName='report'
    >
      <View className='card'>
        <View className='row report__hero'>
          <AccuracyRing percent={report.accuracy} size={88} labelLarge />
          <View className='report__hero-text'>
            <View className='h'>{topic}</View>
            <View className='tiny report__hero-meta'>
              {/* 日期解析不出来时只显示用时 —— 宁可少一段，也不摆一个 Invalid Date */}
              {finishedLabel ? `${finishedLabel} · ` : ''}用时 {formatDuration(report.duration_ms)}
            </View>
            <View className='row report__hero-pills'>
              <Text className='pill gold'>
                +{report.xp_gained} {REPORT_COPY.xpLabel}
              </Text>
              <Text className='pill'>
                +{report.coins_gained} {REPORT_COPY.coinsLabel}
              </Text>
            </View>
          </View>
        </View>
      </View>

      <View className='grid3'>
        <View className='card plain'>
          <View className='stat sm c-ok'>
            {report.correct_count}/{report.total_count}
          </View>
          <View className='statlab'>{REPORT_COPY.statCorrect}</View>
        </View>
        <View className='card plain'>
          <View className='stat sm c-bad'>{report.wrong_count}</View>
          <View className='statlab'>{REPORT_COPY.statWrong}</View>
        </View>
        <View className='card plain'>
          <View className='stat sm c-blue'>{formatSeconds(report.avg_seconds_per_question)}</View>
          <View className='statlab'>{REPORT_COPY.statAvgTime}</View>
        </View>
      </View>

      <View className='card plain'>
        <View className='row report__percentile'>
          <Sprite name='momo' size={52} />
          <View className='report__percentile-body'>
            <View className='between'>
              <Text className='report__percentile-title'>
                {REPORT_COPY.percentilePrefix} {report.percentile}% {REPORT_COPY.percentileSuffix}
              </Text>
              <Text className='pill ok'>{report.percentile_label}</Text>
            </View>
            <View className='report__percentile-gap' />
            <View className='bar ok'>
              <View style={styleOf({ width: `${report.percentile}%` })} />
            </View>
            <View className='tiny report__percentile-note'>{REPORT_COPY.percentileNote}</View>
          </View>
        </View>
      </View>

      {/* 模板兜底要如实告知：不说清会让用户以为 AI 就这个水平 */}
      {report.degraded && <View className='tiny report__note'>{REPORT_COPY.degradedNote}</View>}

      {/* 进入下一段的入口。
          原型的「知识总结」「复习建议」是两张独立的样机屏，没有画出它们
          从主视图怎么进 —— 这里用一颗次级按钮补上，文案直接取第 2 屏的卡片标题。 */}
      <Button
        className='btn ghost report__next'
        onClick={() => goPage('/pages/report/summary/index')}
      >
        {REPORT_COPY.summaryLabel}
      </Button>

      <View className='spacer' />

      <Button className='btn' onClick={handleShare}>
        {REPORT_COPY.share}
      </Button>
      <Button className='btn ghost report__secondary' onClick={() => goTab('/pages/hall/index')}>
        {REPORT_COPY.backToHall}
      </Button>
    </PhoneShell>
  )
}
