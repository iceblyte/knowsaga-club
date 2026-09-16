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
import { goPage, goTab } from '../../utils/navigation'
import { styleOf } from '../../utils/style'

import './index.scss'

/** 后端还没回第一个状态时的本地兜底（名字与后端 `_initial_steps` 保持一致） */
function fallbackSteps(searchEnabled: boolean, questionCount: number): TaskStep[] {
  return [
    {
      key: 'retrieve',
      name: searchEnabled ? SUMMON_STEPS.retrieveOnline : SUMMON_STEPS.retrieveNoop,
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

  const [task, setTask] = useState<TaskRecord | null>(null)
  const [failure, setFailure] = useState('')
  /** 题库已拿到、正在（或已经尝试）跳转确认页 */
  const [ready, setReady] = useState(false)
  const [estimatedSeconds, setEstimatedSeconds] = useState(0)
  const [showCancelEntry, setShowCancelEntry] = useState(false)
  const [askAbandon, setAskAbandon] = useState(false)
  /** 递增即重开一轮（「重新生成」按钮） */
  const [attempt, setAttempt] = useState(0)

  /** 页面是否还活着。轮询与状态更新都以它为准，避免已离开的页面继续写入 */
  const aliveRef = useRef(true)
  /** 用户是否已经主动放弃本次召唤 */
  const abandonedRef = useRef(false)
  const taskIdRef = useRef('')

  // 「取消」按原型是 8 秒后才出现的：一开始就摆一个取消按钮，
  // 会让用户以为「这东西很慢」，实际大多数召唤十几秒就完事。
  useEffect(() => {
    setShowCancelEntry(false)
    const timer = setTimeout(() => setShowCancelEntry(true), CANCEL_APPEAR_MS)
    return () => clearTimeout(timer)
  }, [attempt])

  useEffect(() => {
    aliveRef.current = true
    abandonedRef.current = false

    const topic = useAppStore.getState().userInput.trim()
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

    const run = async () => {
      try {
        const submission = await createQuizTask({
          user_input: topic,
          question_count: QUIZ_QUESTION_COUNT,
          difficulty: QUIZ_DIFFICULTY
        })
        if (!aliveRef.current) return

        taskIdRef.current = submission.task_id
        setEstimatedSeconds(submission.estimated_seconds)

        const final = await pollTask({
          taskId: submission.task_id,
          intervalMs: submission.poll_interval_ms,
          onUpdate: (next) => {
            if (aliveRef.current) setTask(next)
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
  const steps = task?.steps?.length ? task.steps : fallbackSteps(searchEnabled, QUIZ_QUESTION_COUNT)
  const progress = task?.progress ?? 0

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
                : `${shortenTopic(topic)} · 预计 ${estimatedSeconds || 10} 秒`}
          </View>
        </View>

        {!failure && (
          <View className='bar blue summon__bar'>
            <View style={styleOf({ width: `${progress}%` })} />
          </View>
        )}
      </View>

      <View className='summon__spacer' />

      {/* 三步状态卡：名字 / 详情 / 状态全部来自后端，前端只负责排版 */}
      <View className='card plain'>
        {steps.map((step, index) => {
          const pill = STEP_PILL[step.status]
          return (
            <View key={step.key}>
              {index > 0 && <View className='summon__step-gap' />}
              <View className='li'>
                <View className='ico'>{index + 1}</View>
                <View className='tx'>
                  <View className='n'>{step.name}</View>
                  <View className='d'>{step.detail}</View>
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
