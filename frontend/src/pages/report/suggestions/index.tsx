/**
 * 冒险日志 · 复习建议（原型 03 第 3 屏）。
 *
 * ## 动作是**事实**，不是文案
 *
 * 每条建议的按钮由后端的 `action.kind` 决定（见 `backend/app/services/report_service.py`
 * 的 `build_actions`）：有错题才有「立即重做」，而且指向**真正答错的那道题**；
 * 「已加入复习计划」只在确实有错题入队时才出现。
 *
 * 让模型来决定「建议重做第 3 题」而第 3 题其实答对了，就是一份假报告 ——
 * 所以模型只写文案，动作一律由服务端按事实挂。
 *
 * ## 三种动作渲染成三种控件（这不是实现细节，是语义差别）
 *
 * | kind | 控件 | 为什么 |
 * |---|---|---|
 * | `retry_question` | 按钮「立即重做」 | 需要用户动作 |
 * | `review_plan` | **胶囊**（不可点） | 表达「系统已经替你排好了」这个既成事实，做成按钮会让人以为还要自己点一次 |
 * | `new_scroll` | 按钮「召唤新副本」 | 需要用户动作 |
 *
 * `action` 为 `null` 的建议**只渲染文案、不给控件** —— 一个点了没反应的按钮
 * 比没有按钮更糟。
 *
 * ## 「立即重做」怎么落到那道题上（一个不能偷懒的地方）
 *
 * 卡片标题写的是「重做第 N 题」，所以按钮必须让用户**第一眼就看到那道题**。
 * 但 `POST /attempts/{id}/retry` 返回的是**整卷**（见用户系统方案设计文档 §6.3），
 * 而答题页是纯线性的：只有「下一题」，没有回退、也不能跳题。
 *
 * 于是一个很自然但错误的做法是 `start()` 之后 `setCurrentIndex(target)` ——
 * 跳到第 N 题 ⇒ 前面 N-1 题在交卷时变成「未作答」⇒ 按 0 分计。
 * **用户听从了我们自己的建议，分数反而被扣掉。** 这是最不能接受的一种 bug：
 * 界面在惩罚用户服从它。
 *
 * 采用的做法是**把目标题换到第一位**：5 道题一道不少、顺序不影响判分
 * （`POST /attempts` 按 `question_id` 判定，结算页只渲染汇总数字），
 * 而用户点进去看到的第一题确实是建议里点名的那一道。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import PhoneShell from '../../../components/PhoneShell'
import ReportMissing from '../../../components/ReportMissing'
import { REPORT_COPY } from '../../../constants/copy'
import { retryAttempt } from '../../../services/attempt'
import { useQuizStore } from '../../../store/useQuizStore'
import { useReportStore } from '../../../store/useReportStore'
import type { Quiz, ReportAction } from '../../../types/api'
import { goPage, goTab } from '../../../utils/navigation'

import './index.scss'

/**
 * 把 `questionId` 指向的题换到卷轴第一位；指不到就原样返回。
 *
 * 只挪这一道：其余题的相对顺序保持不变，用户对「其余四道题的顺序」不应该
 * 因为点了一次重做而改变。
 */
function prioritizeQuestion(quiz: Quiz, questionId: string | null | undefined): Quiz {
  if (!questionId) return quiz
  const index = quiz.questions.findIndex((item) => String(item.id) === String(questionId))
  // 已经是第一题（或找不到）时不做无意义的拷贝
  if (index <= 0) return quiz
  return {
    ...quiz,
    questions: [
      quiz.questions[index],
      ...quiz.questions.slice(0, index),
      ...quiz.questions.slice(index + 1)
    ]
  }
}

export default function ReportSuggestionsPage() {
  const report = useReportStore((s) => s.report)
  /** 重做请求进行中：防止连点两次发出两次重做 */
  const [busy, setBusy] = useState(false)

  if (!report) {
    return <ReportMissing navTitle={REPORT_COPY.suggestionsNavTitle} />
  }

  const attemptId = report.attempt_id

  /**
   * 「立即重做」：取回这一局的题库快照，把建议点名的那道题换到第一位，
   * 开局并进入答题页。为什么是「换位」而不是「跳题」见文件头说明。
   */
  const handleRetryQuestion = async (action: ReportAction) => {
    if (busy) return
    setBusy(true)
    try {
      const retry = await retryAttempt(attemptId)
      // 复用确认页那条路径：`start()` 会生成新的交卷令牌，
      // 所以重做是一次**独立的挑战记录**，不会覆盖原来那一局
      useQuizStore.getState().start(prioritizeQuestion(retry.quiz, action.question_id))
      goPage('/pages/quiz/index', 'redirect')
    } catch (error) {
      // 题库只存在于服务端；取不回来时给可操作的提示，而不是静默无反应
      Taro.showToast({ title: '这份卷轴暂时取不回来了，稍后再试', icon: 'none' })
      console.warn('[report/suggestions] 重做失败', error)
    } finally {
      setBusy(false)
    }
  }

  const handleNewScroll = () => {
    // 召唤新副本需要一个主题，而这里没有 —— 交给召唤页自己去取
    // （它没有主题时会退回大厅并说明原因，见 pages/summon）
    goPage('/pages/summon/index', 'redirect')
  }

  const renderAction = (action: ReportAction | null) => {
    if (!action) return null

    if (action.kind === 'review_plan') {
      return <Text className='pill gold'>{action.label}</Text>
    }

    if (action.kind === 'retry_question') {
      return (
        <Button
          className='btn sm ghost'
          disabled={busy}
          onClick={() => handleRetryQuestion(action)}
        >
          {action.label}
        </Button>
      )
    }

    return (
      <Button className='btn sm' onClick={handleNewScroll}>
        {action.label}
      </Button>
    )
  }

  return (
    <PhoneShell navTitle={REPORT_COPY.suggestionsNavTitle} screenClassName='report-suggestions'>
      {report.advice.map((item, index) => (
        <View key={`${index}-${item.title}`} className='card'>
          <View className='row report-suggestions__item'>
            <View className='badge report-suggestions__badge'>{index + 1}</View>
            <View className='report-suggestions__body'>
              <View className='h sm'>{item.title}</View>
              <View className='body sm report-suggestions__text'>{item.body}</View>
              {item.action && (
                <>
                  <View className='report-suggestions__gap' />
                  {renderAction(item.action)}
                </>
              )}
            </View>
          </View>
        </View>
      ))}

      <View className='spacer' />

      <Button className='btn ghost' onClick={() => goTab('/pages/report/index')}>
        {REPORT_COPY.backToReport}
      </Button>
    </PhoneShell>
  )
}
