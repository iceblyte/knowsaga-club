/**
 * 副本召唤中（原型 01 第 4 屏）—— 真实出题流程的等待页。
 *
 * ## 这一页做三件事
 *
 * 1. `POST /quiz/generate` 建任务（只入队，立刻返回 `task_id`）
 * 2. 按后端给的 `poll_interval_ms` 轮询 `GET /tasks/{id}`
 * 3. 成功 → 把题库交给确认页；失败 → 给出**可操作**的失败态
 *
 * ## 进度与文案全部来自后端
 *
 * 三步状态卡的名字、详情、状态、整体进度都取自任务的 `steps` / `progress`，
 * 前端**一个都不自己编**。原因很实际：假进度在失败时会显得格外不可信 ——
 * 进度条走到 90% 然后告诉你出题失败，用户只会觉得整个功能都在骗他。
 *
 * ## 但「还要多久」必须由前端铺平到每一秒（本轮修复第 5 条）
 *
 * 后端只在两个时刻更新「生成闯关题目」这一步：开始（`正在生成第 1 / 5 题`）
 * 与结束（`已生成 5 道题`）—— 5 道题是**一次** LLM 调用出来的，服务端不存在
 * 「第 2 题开始了」这种时刻。于是那二三十秒里界面一动不动，用户以为卡死了。
 *
 * 所以这一页有一秒一次的时钟：把服务端给的 `estimated_seconds` 走成倒计时、
 * 把题号按时间比例推进。**它不是另编一套进度**：措辞仍然逐字来自服务端
 * （`advanceQuestionDetail` 只替换一个数字），边界写在 `utils/task-progress.ts`
 * 的文件头里 —— 只增不减、题号停在 `N-1`、超时后换一句话、进度条不到 100%。
 *
 * ## 用户看不到「内部机制」
 *
 * 这一页只出现了三类文案：正在做什么（来自后端）、大概还要多久、
 * 失败时怎么办。**没有任何一句在描述「这一步会调用什么、校验什么」** ——
 * 那是给开发者看的，不是给用户看的。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import MagicStage from '../../components/MagicStage'
import PhoneShell from '../../components/PhoneShell'
import {
  CANCEL_APPEAR_MS,
  CLIENT_ERROR_CODE,
  QUIZ_DIFFICULTY,
  QUIZ_QUESTION_COUNT
} from '../../constants/api'
import { COMMON_COPY, SUMMON_COPY, SUMMON_STEPS } from '../../constants/copy'
import { INPUT_MIN_LEN } from '../../constants/mock'
import { ApiError, toDisplayMessage } from '../../services/request'
import { cancelTask, createQuizTask, pollTask } from '../../services/quiz'
import { useAppStore } from '../../store/useAppStore'
import { useQuizStore } from '../../store/useQuizStore'
import type { StepStatus, TaskRecord, TaskStep } from '../../types/api'
import { hasUrl } from '../../utils/links'
import { goPage, goTab } from '../../utils/navigation'
import type { RetrievalMode } from '../../utils/retrieval'
import { resolveRetrievalMode } from '../../utils/retrieval'
import { styleOf } from '../../utils/style'
import {
  advanceQuestionDetail,
  remainingSeconds,
  smoothProgress,
  smoothQuestionIndex
} from '../../utils/task-progress'

import './index.scss'

/** 取材路径 → 第一步的名字。与后端 `_initial_steps` / `build_initial_step` 同一套判据 */
const FIRST_STEP_NAME: Record<RetrievalMode, string> = {
  unavailable: SUMMON_STEPS.retrieveNoop,
  online: SUMMON_STEPS.retrieveOnline,
  'online-with-link': SUMMON_STEPS.retrieveLink,
  'link-only': SUMMON_STEPS.retrieveLink,
  offline: SUMMON_STEPS.retrieveNoop
}

/** 后端还没回第一个状态时的本地兜底（名字与后端 `_initial_steps` 保持一致） */
function fallbackSteps(firstStepName: string, questionCount: number): TaskStep[] {
  return [
    {
      key: 'retrieve',
      name: firstStepName,
      status: 'pending',
      detail: '准备中'
    },
    {
      key: 'generate',
      name: SUMMON_STEPS.generate,
      status: 'pending',
      detail: `将生成 ${questionCount} 道题`
    },
    { key: 'validate', name: SUMMON_STEPS.validate, status: 'pending', detail: '等待中' }
  ]
}

const STEP_PILL: Record<StepStatus, { text: string; cls: string } | null> = {
  done: { text: '完成', cls: '' },
  running: { text: '进行中', cls: 'blue' },
  failed: { text: '失败', cls: 'bad' },
  pending: null
}

/** 副标题里的主题标签：太长会把「预计 N 秒」挤掉 */
function shortenTopic(text: string, limit = 12): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat
}

export default function SummonPage() {
  const setPendingQuiz = useQuizStore((s) => s.setPendingQuiz)
  const searchEnabled = useAppStore((s) => s.searchEnabled)
  /** 本次意愿。只用于渲染兜底步骤名；建任务时从 `getState()` 取同一份值 */
  const useSearchWanted = useAppStore((s) => s.useSearch)

  const [task, setTask] = useState<TaskRecord | null>(null)
  const [failure, setFailure] = useState('')
  /** 题库已拿到、正在（或已经尝试）跳转确认页 */
  const [ready, setReady] = useState(false)
  const [estimatedSeconds, setEstimatedSeconds] = useState(0)
  const [showCancelEntry, setShowCancelEntry] = useState(false)
  const [askAbandon, setAskAbandon] = useState(false)
  /** 递增即重开一轮（「重新生成」按钮） */
  const [attempt, setAttempt] = useState(0)

  /**
   * 每秒走一次的时钟（本轮修复第 5 条）。
   *
   * 它只做一件事：让「还要多久」与题号真的在变化。取值用 `Date.now()`
   * 而不是累加，是为了让标签页被切到后台再回来时**一次对齐**，
   * 而不是先补上错过的那些秒。
   */
  const [clock, setClock] = useState(() => Date.now())

  /** 页面是否还活着。轮询与状态更新都以它为准，避免已离开的页面继续写入 */
  const aliveRef = useRef(true)
  /** 用户是否已经主动放弃本次召唤 */
  const abandonedRef = useRef(false)
  const taskIdRef = useRef('')
  /** 拿到 `estimated_seconds` 的时刻：倒计时与进度条的起点 */
  const startedAtRef = useRef(0)
  /** 「生成闯关题目」这一步**开始跑**的时刻（不是整个任务的起点） */
  const generateStartedAtRef = useRef(0)

  // 「取消」按原型是 8 秒后才出现的：一开始就摆一个取消按钮，
  // 会让用户以为「这东西很慢」，实际大多数召唤十几秒就完事。
  useEffect(() => {
    setShowCancelEntry(false)
    const timer = setTimeout(() => setShowCancelEntry(true), CANCEL_APPEAR_MS)
    return () => clearTimeout(timer)
  }, [attempt])

  // 秒表：只在**等待期间**跑。拿到结果或失败之后立刻停 ——
  // 一个已经结束的页面不该继续每秒 setState。
  useEffect(() => {
    if (failure || ready) return
    const timer = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [failure, ready, attempt])

  useEffect(() => {
    aliveRef.current = true
    abandonedRef.current = false

    const topic = useAppStore.getState().userInput.trim()
    // 意愿在这一刻一次性定下（与 topic 同一时点）：把它放进 effect 依赖会让
    // 用户切一次开关就重跑整个出题任务 —— 而那只 pill 在另一个页面上，
    // 中途根本切不到，多那个依赖只会引入「重新生成时用旧意愿」这类歧义。
    const wantSearch = useAppStore.getState().useSearch
    if (topic.length < INPUT_MIN_LEN) {
      // 直接进入本页（比如从历史记录跳回来）而没有主题时，退回到大厅而不是白屏
      Taro.showToast({ title: COMMON_COPY.inputTooShort, icon: 'none' })
      setTimeout(() => {
        goTab('/pages/hall/index')
      }, 800)
      return () => {
        aliveRef.current = false
      }
    }

    setTask(null)
    setFailure('')
    setReady(false)
    // 重开一轮（「重新生成」）时，上一轮的起点必须清掉 ——
    // 留着它会让新任务的倒计时一开局就显示「已超出预计时间」
    startedAtRef.current = 0
    generateStartedAtRef.current = 0

    const run = async () => {
      try {
        const submission = await createQuizTask({
          user_input: topic,
          question_count: QUIZ_QUESTION_COUNT,
          difficulty: QUIZ_DIFFICULTY,
          use_search: wantSearch
        })
        if (!aliveRef.current) return

        taskIdRef.current = submission.task_id
        setEstimatedSeconds(submission.estimated_seconds)
        // 秒表从这一刻起算，并立刻对齐一次 —— 等下一次 tick 才走
        // 会让第一秒显示成「还没开始」
        startedAtRef.current = Date.now()
        setClock(Date.now())

        const final = await pollTask({
          taskId: submission.task_id,
          intervalMs: submission.poll_interval_ms,
          onUpdate: (next) => {
            if (!aliveRef.current) return
            // 记下「生成」这一步**真正开始跑**的时刻：题号按它之后的耗时推进，
            // 用整个任务的起点算会让题号在检索阶段就冲到第 2 题
            if (!generateStartedAtRef.current) {
              const step = next.steps?.find((item) => item.key === 'generate')
              if (step?.status === 'running') generateStartedAtRef.current = Date.now()
            }
            setTask(next)
          },
          shouldContinue: () => aliveRef.current && !abandonedRef.current
        })

        if (!aliveRef.current || abandonedRef.current) return

        if (final.status === 'succeeded' && final.quiz) {
          setPendingQuiz(final.quiz)
          // 题库已经在 store 里了，先让页面进入「可进入」状态 ——
          // 万一跳转没成功，用户还有一个能点的按钮，而不是停在一个
          // 进度已经 100% 却什么都不发生的等待页。
          setReady(true)
          // 用 redirectTo 推进流程：召唤页的使命已经结束，返回键不该把用户
          // 送回一个已经跑完的等待页 —— 那样会立刻又发一次出题请求。
          goPage('/pages/confirm/index', 'redirect')
          return
        }

        if (final.status === 'failed') {
          setFailure(
            toDisplayMessage(
              new ApiError(final.error?.code ?? 5000, final.error?.message ?? '')
            )
          )
          return
        }

        // cancelled：用户自己放弃的，跳转已经在 handleAbandon 里做过
      } catch (error) {
        if (!aliveRef.current || abandonedRef.current) return
        // 轮询被主动中断不是错误，不该弹失败态
        if (error instanceof ApiError && error.code === CLIENT_ERROR_CODE.POLL_TIMEOUT) {
          if (error.message === '已停止等待') return
        }
        setFailure(toDisplayMessage(error))
      }
    }

    run()

    return () => {
      aliveRef.current = false
    }
  }, [attempt, setPendingQuiz])

  /** 放弃本次召唤：先让后端别白跑，再离开 */
  const handleAbandon = async () => {
    setAskAbandon(false)
    abandonedRef.current = true
    aliveRef.current = false

    const taskId = taskIdRef.current
    if (taskId) {
      try {
        await cancelTask(taskId)
      } catch {
        // 任务可能恰好已经结束（4090）或已过期（4004），这两种情况都无需处理
      }
    }

    Taro.showToast({ title: SUMMON_COPY.cancelled, icon: 'none', duration: 1200 })
    setTimeout(() => {
      Taro.navigateBack({ delta: 1 }).catch(() => {
        goTab('/pages/hall/index')
      })
    }, 400)
  }

  const handleBack = () => {
    // 已经有结果（成功或失败）时返回键直接走人；还在生成中才需要确认放弃
    if (failure || ready) {
      Taro.navigateBack({ delta: 1 }).catch(() => {
        goTab('/pages/hall/index')
      })
      return
    }
    setAskAbandon(true)
  }

  const topic = useAppStore((s) => s.userInput).trim()
  /**
   * 首次轮询回来之前的兜底步骤。
   *
   * 名字必须与后端**同一套判据**（能力 × 意愿 × 有无链接），否则贴了链接的用户会先看到
   * 「联网检索知识」、再被后端改成「读取你给的网页」—— 一次一闪而过的自相矛盾。
   * 判据共用 `utils/retrieval`，那里也是大厅 pill 用的那一份。
   */
  const fallbackFirstStep = FIRST_STEP_NAME[
    resolveRetrievalMode(searchEnabled, useSearchWanted, hasUrl(topic))
  ]
  const steps = task?.steps?.length
    ? task.steps
    : fallbackSteps(fallbackFirstStep, QUIZ_QUESTION_COUNT)

  // ---------------------------------------------------------------------------
  // 平滑进度（见文件头与 `utils/task-progress`）
  // ---------------------------------------------------------------------------
  const waiting = !failure && !ready
  const elapsed = startedAtRef.current > 0 ? (clock - startedAtRef.current) / 1000 : 0
  const remaining = remainingSeconds(estimatedSeconds, elapsed)
  const progress = smoothProgress(
    task?.progress ?? 0,
    elapsed,
    estimatedSeconds,
    !waiting
  )

  /**
   * 副标题里「还要多久」那一句。
   *
   * 三态必须分开，因为它们的含义完全不同：还没拿到服务端的预计时长（`0`）
   * 时不能显示「已超出预计时间」—— 那是冤枉它。
   */
  const waitingLabel =
    estimatedSeconds <= 0
      ? SUMMON_COPY.preparing
      : remaining > 0
        ? SUMMON_COPY.estimatedRemaining(remaining)
        : SUMMON_COPY.overEstimate

  /** 进入「生成」这一步之后的秒数；这一步还没开始时为 `null`（不插值） */
  const elapsedInGenerate =
    generateStartedAtRef.current > 0
      ? (clock - generateStartedAtRef.current) / 1000
      : null

  return (
    <PhoneShell
      navTitle={SUMMON_COPY.navTitle}
      onBack={handleBack}
      scroll={false}
      screenClassName='summon'
    >
      <View className='summon__spacer' />

      <View className='summon__hero'>
        <MagicStage
          size={176}
          spriteSize={80}
          sprite='shishi'
          spriteMotion={failure ? 'none' : 'floaty'}
          still={Boolean(failure)}
        />

        <View className='summon__caption'>
          <View className='h'>
            {failure
              ? SUMMON_COPY.failedTitle
              : ready
                ? SUMMON_COPY.readyTitle
                : SUMMON_COPY.title}
          </View>
          <View className='sub summon__caption-sub'>
            {failure
              ? failure
              : ready
                ? `${shortenTopic(topic)} · 副本已就绪`
                : `${shortenTopic(topic)} · ${waitingLabel}`}
          </View>
        </View>

        {!failure && (
          <View className='bar blue summon__bar'>
            <View style={styleOf({ width: `${progress}%` })} />
          </View>
        )}
      </View>

      <View className='summon__spacer' />

      {/* 三步状态卡：名字 / 详情 / 状态全部来自后端，前端只负责排版。
          ⚠️ 唯一的例外是「生成」这一步的**题号**：后端只报「开始生成」
          与「已生成 N 道题」两个端点，中间没有事件可报，所以由
          `smoothQuestionIndex` 按时间比例推进 —— 措辞仍逐字来自服务端，
          只替换第一个数字，边界见 `utils/task-progress`。 */}
      <View className='card plain'>
        {steps.map((step, index) => {
          const pill = STEP_PILL[step.status]
          const shown = smoothQuestionIndex(
            step.detail,
            step.status,
            elapsedInGenerate,
            estimatedSeconds
          )
          return (
            <View key={step.key}>
              {index > 0 && <View className='summon__step-gap' />}
              <View className='li'>
                <View className='ico'>{index + 1}</View>
                <View className='tx'>
                  <View className='n'>{step.name}</View>
                  <View className='d'>
                    {shown === null ? step.detail : advanceQuestionDetail(step.detail, shown)}
                  </View>
                </View>
                {pill && <Text className={`pill${pill.cls ? ` ${pill.cls}` : ''}`}>{pill.text}</Text>}
              </View>
            </View>
          )
        })}
      </View>

      {/* 生成完毕：正常情况下已经自动跳走了；这个按钮只在跳转没成功时被看到，
          作用是保证用户永远不会停在一个「进度 100% 却无路可走」的等待页上 */}
      {ready && !failure && (
        <View className='summon__actions'>
          <Button className='btn' onClick={() => goPage('/pages/confirm/index', 'redirect')}>
            {SUMMON_COPY.enter}
          </Button>
        </View>
      )}

      {failure && (
        <View className='summon__actions'>
          <Button className='btn' onClick={() => setAttempt((value) => value + 1)}>
            {SUMMON_COPY.retry}
          </Button>
        </View>
      )}

      {!failure && !ready && !showCancelEntry && (
        <View className='tiny summon__hint'>{SUMMON_COPY.waitingHint}</View>
      )}

      {/* 放弃确认 */}
      {askAbandon && (
        <View className='mask'>
          <View className='card plain summon__dialog'>
            <View className='h'>{SUMMON_COPY.cancelConfirmTitle}</View>
            <View className='body sm summon__dialog-body'>{SUMMON_COPY.cancelConfirmBody}</View>
            <Button className='btn' onClick={() => setAskAbandon(false)}>
              {SUMMON_COPY.cancelConfirmPrimary}
            </Button>
            <Button className='btn ghost summon__dialog-secondary' onClick={handleAbandon}>
              {SUMMON_COPY.cancelConfirmSecondary}
            </Button>
          </View>
        </View>
      )}
    </PhoneShell>
  )
}
