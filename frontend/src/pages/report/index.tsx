/**
 * 冒险日志 · 标签页（原型 03）。
 *
 * ## 这一页是「列表 + 详情」两态（2026-09-26 人工上报的 Bug 修复）
 *
 * 原来进这一页直接看到**某一局的报告**（顶上一排日志 chip 供切换）。
 * 用户反馈「下滑时那个显示百分比的圆环固定不动，不跟着滚」——
 * 那个圆环是 `canvas` 画的，而 `canvas` 在小程序端是**原生组件**：
 * 官方文档明确说它不能嵌套在 `scroll-view` 这类可滚动容器里，实际表现就是
 * 滚动时「悬浮」在屏幕上不动（`position: sticky` / `z-index` / `transform`
 * 都改不动它 —— 它在 WebView 渲染层之外，不参与文档流）。
 * 详见 `components/AccuracyRing` 的文件头。
 *
 * 于是这一页的组织方式改成：**标签页先给日志列表，点某一条才展开那一局的报告**。
 * 列表里没有任何 canvas；报告也只在你主动点开时才占满屏幕。
 *
 * 列表与「历史卷轴」（04·5）用**同一个接口**（`GET /users/me/scrolls`）和
 * 同一套行文案（`SCROLLS_COPY.rowMeta` / `questionPill`），所以两处的
 * 「今天 14:20 · 正确率 80%」逐字一致，不会各说一套。那边多出来的是
 * 筛选 / 翻页 / 长按删除，这一栏只给最近 20 条 + 一个「查看全部」的入口。
 *
 * ## 进入详情只有一条路：store 里出现一个**新目标**
 *
 * `useDidShow` 里读 `useReportStore`，按 `status` 分三种：
 *
 * | status | 含义 | 这一页怎么做 |
 * |---|---|---|
 * | `idle` | 刚被 `begin()` 设过目标（结算页 / 点列表项），还没生成 | 打开详情 |
 * | `generating` | 上次离开时轮询随页面卸载停了 → 必须重开，否则永远停在「生成中」 | 重开并回详情 |
 * | `ready` / `failed` / `offline` | 都是**上一轮的残留** | 回列表，并清空 store |
 *
 * 第三行就是「切回标签页永远先看到列表」的实现：旧的报告不该在用户没点
 * 任何东西的时候自己占满屏幕。代价是从「知识总结」返回时也走这一支、
 * 落回列表 —— 那个按钮本来就写着「回到冒险日志」，落到列表是字面成立的。
 *
 * ## 统计数字全部来自服务端，前端不重算
 *
 * 「答对 4 / 5」「8.4s」分别直接读 `correct_count` / `total_count`、
 * `avg_seconds_per_question`。理由：报告页与结算页必须**逐位相同**，
 * 而两处各算一遍迟早会因为一处改了规则而对不上（见 `backend/app/models/report.py`）。
 *
 * 「比过去的自己怎么样」那一格同理：状态与差值都由服务端给（`report.progress`），
 * 前端只查文案表（`progressTextOf`），一条比较逻辑都不写。
 * ⚠️ 原型第 1 屏那句「本局超过社团里 72% 的冒险者」已于 2026-09-23 撤回 ——
 * 理由见 `constants/copy.ts` 文件头第 4 条，**不要**把它加回来。
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
 *
 * ## 列表取不到时**不能**说「日志本还是空的」
 *
 * 那是在冤枉用户 —— 他的记录可能好好地躺在服务端。所以取不到给的是
 * 「重新加载」，真的没有才给「去召唤一张卷轴」。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow, useShareAppMessage } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import AccuracyRing, { colorOf } from '../../components/AccuracyRing'
import ArchiveState from '../../components/ArchiveState'
import MagicStage from '../../components/MagicStage'
import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { CLIENT_ERROR_CODE } from '../../constants/api'
import {
  ARCHIVE_COMMON,
  REPORT_COPY,
  REPORT_ERROR_TEXT,
  SCROLLS_COPY,
  progressTextOf
} from '../../constants/copy'
import type { AsyncStatus } from '../../hooks/useAsyncData'
import { useTabPage } from '../../hooks/useTabPage'
import { fetchScrolls } from '../../services/archive'
import { createReportTask } from '../../services/report'
import { pollTask } from '../../services/quiz'
import { ApiError } from '../../services/request'
import { useReportStore } from '../../store/useReportStore'
import { useQuizStore } from '../../store/useQuizStore'
import type { ScrollItem, StepStatus, TaskRecord, TaskStep } from '../../types/api'
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

/**
 * 列表取几条。
 *
 * 取 20（服务端一页的默认值）而不是「全部」：这一栏是**入口**，不是完整的
 * 历史管理页。超出的部分由「查看全部日志」指过去（04·5 有筛选、翻页、
 * 长按删除），而不是在这里无限拉。
 */
const LOG_PICKER_SIZE = 20

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

/** 页面的两种形态：先看列表，点开才看报告 */
type ReportView = 'list' | 'detail'

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

  /**
   * 当前形态。**默认列表** —— 这是「进这一页先看到什么」的答案，
   * 详情只在 `useDidShow` 判定出「有个新目标」或用户点了某一条时才进入。
   */
  const [view, setView] = useState<ReportView>('list')

  /** 本轮是否要求强制重新生成（点「重新生成报告」时为 true） */
  const forceRef = useRef(false)
  /** 页面是否还活着 */
  const aliveRef = useRef(true)

  // ---------------------------------------------------------------------------
  // 日志列表
  // ---------------------------------------------------------------------------
  const [logs, setLogs] = useState<ScrollItem[]>([])
  const [logsTotal, setLogsTotal] = useState(0)
  const [logsStatus, setLogsStatus] = useState<AsyncStatus>('loading')
  /** 请求序号：连续切换时旧响应不许覆盖新的 */
  const logsSeqRef = useRef(0)
  /** 列表请求自己的存活标记（与轮询那个 `aliveRef` 分开，两件事的生命周期不同） */
  const logsAliveRef = useRef(true)

  useEffect(() => {
    logsAliveRef.current = true
    return () => {
      logsAliveRef.current = false
    }
  }, [])

  const loadLogs = useCallback(() => {
    const seq = (logsSeqRef.current += 1)
    // 已经有数据时**不**回到 loading 态：切回来刷新一下列表，不该整屏闪一次转圈。
    // 用函数式更新读上一次的状态 —— 这个回调的依赖是空的（它得能被 useDidShow
    // 直接调用），闭包里读 `logs.length` 只会永远读到挂载时的那个空数组。
    setLogsStatus((prev) => (prev === 'ready' ? prev : 'loading'))

    fetchScrolls('', 1, LOG_PICKER_SIZE).then(
      (result) => {
        if (!logsAliveRef.current || seq !== logsSeqRef.current) return
        setLogs(result.items)
        setLogsTotal(result.total)
        setLogsStatus('ready')
      },
      () => {
        if (!logsAliveRef.current || seq !== logsSeqRef.current) return
        setLogsStatus('error')
      }
    )
  }, [])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  /**
   * 打开某一条日志的报告。
   *
   * `begin()` 会把 store 的 `status` 打回 `idle`、并清掉上一份报告 ——
   * 所以紧接着的生成 effect 一定会为**这一条**重新跑一轮，绝不会把
   * 上一局的上屏数字留在屏幕上。
   */
  const openDetail = useCallback((id: string) => {
    useReportStore.getState().begin(id)
    // 清掉上一条的步骤卡：否则会先闪一帧「上一次生成到哪一步了」
    setTask(null)
    setView('detail')
    setRunToken((value) => value + 1)
  }, [])

  /** 从详情退回列表。清空 store —— 列表态下不该留着任何一局的报告 */
  const backToList = useCallback(() => {
    useReportStore.getState().reset()
    setTask(null)
    setView('list')
  }, [])

  /**
   * 每次页面显示时决定「进列表还是进详情」。
   *
   * 放在 `useDidShow` 而不是 `useEffect` 里，是因为**切走再切回来**也要走
   * 这一支 —— 用 `useEffect([])` 只能覆盖首次挂载。判定规则见文件头。
   */
  /** 首次显示跳过列表刷新 —— 挂载时那次已经由 `loadLogs` 的 effect 发起了 */
  const firstShowRef = useRef(true)

  useDidShow(() => {
    // 列表每次重新显示都重取：刚打完一局回来，那一局必须出现在列表里
    if (firstShowRef.current) {
      firstShowRef.current = false
    } else {
      loadLogs()
    }

    const store = useReportStore.getState()
    // 结算页会把这一局的 id 写进 store；直接进标签页时退回「本局」——它们通常是同一局
    const target = store.attemptId || useQuizStore.getState().attempt?.attempt_id || ''

    if (!target) {
      setView('list')
      return
    }

    if (store.status === 'idle') {
      // 刚设过目标（结算页 / 点列表项），还没生成 → 直接打开这一局
      if (target !== store.attemptId) store.begin(target)
      setView('detail')
      setRunToken((value) => value + 1)
      return
    }

    if (store.status === 'generating') {
      // 上次离开时轮询随页面卸载停止了 → 必须重开，
      // 否则永远停在「生成中」：一个不会自己结束的等待页
      store.begin(target)
      setView('detail')
      setRunToken((value) => value + 1)
      return
    }

    // 其它状态都是上一轮的残留（ready / failed / offline）→ 回列表并清干净。
    // 这一支就是「切回标签页永远先看到列表」的实现，见文件头。
    store.reset()
    setTask(null)
    setView('list')
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
  // 列表态（标签页的默认形态）
  // ---------------------------------------------------------------------------
  if (view === 'list') {
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report'
      >
        {logs.length === 0 ? (
          logsStatus === 'error' ? (
            // 取不到 ≠ 没有。直说「取不到」并给一个能重试的按钮，
            // 摆「日志本还是空的」是在冤枉用户
            <ArchiveState
              kind='error'
              title={REPORT_COPY.logsFailed}
              actionText={ARCHIVE_COMMON.retry}
              onAction={loadLogs}
            />
          ) : logsStatus === 'ready' ? (
            // 真的没有 → 说清「做完什么它就有了」，并给一个能带用户离开这里的动作
            <ArchiveState
              kind='empty'
              title={REPORT_COPY.emptyTitle}
              body={REPORT_COPY.emptyBody}
              actionText={REPORT_COPY.emptyCta}
              onAction={() => goTab('/pages/hall/index')}
            />
          ) : (
            <ArchiveState kind='loading' />
          )
        ) : (
          <>
            <View className='tiny report__logs-label'>{REPORT_COPY.listTitle(logsTotal)}</View>

            {/* 每一行都是 `.screen` 的直接子元素：这样才吃到它的 `gap:10px`
                （与 04·5 同一个结构）。外面套一层容器会把那 10px 吞掉。 */}
            {logs.map((item) => (
              <View className='li' key={item.attempt_id} onClick={() => openDetail(item.attempt_id)}>
                <View className='ico'>{SCROLLS_COPY.icon}</View>

                <View className='tx'>
                  <View className='n'>{item.title}</View>
                  <View className='d'>
                    {SCROLLS_COPY.rowMeta(item.finished_label, item.accuracy)}
                  </View>
                </View>

                <Text className='pill'>{SCROLLS_COPY.questionPill(item.total_count)}</Text>
              </View>
            ))}

            {/* 一页只有 20 条。还有更多时把用户交给完整的历史卷轴（04·5）——
                筛选、翻页、长按删除都在那边，这一栏不重复实现一遍 */}
            {logsTotal > logs.length ? (
              <View
                className='tiny report__logs-more'
                onClick={() => goPage('/pages/profile/scrolls/index', 'navigate')}
              >
                {REPORT_COPY.listMore}
              </View>
            ) : null}

            <View className='spacer' />
          </>
        )}
      </PhoneShell>
    )
  }

  // ---------------------------------------------------------------------------
  // 详情态 · 空态：`begin()` 之后 attemptId 又空了（正常路径到不了，留作防御）
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
        <Button className='btn ghost' onClick={backToList}>
          {REPORT_COPY.backToList}
        </Button>
      </PhoneShell>
    )
  }

  /** 详情态各分支共用的顶部返回入口 —— 用户必须能退出去看别的日志 */
  const backBar = (
    <View className='report__back' onClick={backToList}>
      <Text className='tiny'>{REPORT_COPY.backToList}</Text>
    </View>
  )

  // ---------------------------------------------------------------------------
  // 详情态 · 生成中
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
        {backBar}
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
  // 详情态 · 断网（原型 03 第 7 屏）
  // ---------------------------------------------------------------------------
  if (status === 'offline') {
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report report--center'
      >
        {backBar}
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
  // 详情态 · 生成失败（原型 03 第 6 屏）
  // ---------------------------------------------------------------------------
  if (status === 'failed' || !report) {
    return (
      <PhoneShell
        navTitle={REPORT_COPY.navTitle}
        showBack={false}
        reserveTabBar
        screenClassName='report report--center'
      >
        {backBar}
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
  // 详情态 · 主视图（原型 03 第 1 屏）
  // ---------------------------------------------------------------------------
  const finishedLabel = formatDate(report.finished_at)
  /** 与结算页共用同一个「状态 → 文案」映射（见 `constants/copy.ts`） */
  const progressText = progressTextOf(report.progress)

  return (
    <PhoneShell
      navTitle={REPORT_COPY.navTitle}
      showBack={false}
      reserveTabBar
      screenClassName='report'
    >
      {backBar}

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

      {/* 「比过去的自己怎么样」（2026-09-23 起替换掉「本局超过社团里 N% 的冒险者」）。
          这一格**不重复本局数字** —— 上面的环形图与「答对 4/5」已经报过一遍了，
          它只回答一个问题：跟自己的历史比，这一局站在哪儿。
          文案全部来自 `progressTextOf`（与结算页共用），这里一条比较逻辑都没有。 */}
      <View className='card plain'>
        <View className='row report__progress'>
          <Sprite name='momo' size={52} />
          <View className='report__progress-body'>
            <View className='between'>
              <Text className='report__progress-title'>{progressText.title}</Text>
              {/* 胶囊只在破纪录时出现 —— 这一格从此只在状态好时才挂东西。
                  它是被删掉的档位胶囊留下的那个位置与样式（`.pill ok`）。 */}
              {progressText.badge !== null && (
                <Text className='pill ok'>{progressText.badge}</Text>
              )}
            </View>
            <View className='report__progress-gap' />
            {/* 进度条画的是**本局正确率**，与上方环形图同一个数、同一个色阶
                （`colorOf` 是两侧共用的唯一一份阈值表）。
                它原来画的是「超过别人多少」—— 那正是本次要撤掉的东西。 */}
            <View className='bar'>
              <View
                style={styleOf({
                  width: `${report.accuracy}%`,
                  // ⚠️ 必须写 kebab-case 的 `background-color`：style 属性是 CSS 文本，
                  // 不是 React 的 style 对象 —— camelCase 会被浏览器当未知属性静默丢掉，
                  // 而同串里的 width 照常生效，于是这条只留默认色、极难发现
                  // （2026-09-23 实测：写 camelCase 时条形一直是 base 的 $gold，
                  //  与环形图的色阶对不上）。`styleOf` 现在会归一，这里也写明以示意。
                  'background-color': colorOf(report.accuracy)
                })}
              />
            </View>
            <View className='tiny report__progress-note'>{progressText.note}</View>
          </View>
        </View>
      </View>

      {/* 模板兜底要如实告知：不说清会让用户以为 AI 就这个水平 */}
      {report.degraded && <View className='tiny report__note'>{REPORT_COPY.degradedNote}</View>}

      {/* 进入下一段的入口。
          原型的「知识总结」「复习建议」是两张独立的样机屏，没有画出它们
          从主视图怎么进 —— 这里用一颗次级按钮补上，文案直接取第 2 屏的卡片标题。
          用 `navigate`：这是**下钻**（总结页有「回到冒险日志」），默认的
          `redirect` 会把本页从栈里换掉，返回键就没有上一页可回。 */}
      <Button
        className='btn ghost report__next'
        onClick={() => goPage('/pages/report/summary/index', 'navigate')}
      >
        {REPORT_COPY.summaryLabel}
      </Button>

      <View className='spacer' />

      <Button className='btn' onClick={handleShare}>
        {REPORT_COPY.share}
      </Button>
      {/* 返回大厅（原设计保留）。回列表的入口在页面顶部那条 `backBar` 上 ——
          两个方向都留着：看完这一局的人多半想去大厅打下一局，
          而想换一份日志看的人会用顶部那条。 */}
      <Button className='btn ghost report__secondary' onClick={() => goTab('/pages/hall/index')}>
        {REPORT_COPY.backToHall}
      </Button>
    </PhoneShell>
  )
}
