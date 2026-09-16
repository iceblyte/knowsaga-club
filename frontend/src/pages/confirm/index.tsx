/**
 * 副本确认页（原型 01 第 5 屏）。
 *
 * 出题完成后先给一次确认机会，而不是直接把用户推进题目 ——
 * 这一段的设计意图写在原型批注里：「避免直接进入不想要的题目」。
 * 所以这一页的信息排序是「值不值得进去」，而不是「题目长什么样」：
 *
 *   1. 这是什么（标题 + 摘要）
 *   2. 要花多久（题型构成 + 预计时长）
 *   3. 会考到什么（知识点 chip）
 *   4. 才轮到「开始」
 *
 * ## 题型构成与知识点标签都是后端算好的
 *
 * `question_stats` 与 `knowledge_points` 是 `Quiz` 的派生字段（见
 * backend/app/models/quiz.py），前端**不做二次统计** —— 那样两边一旦口径不同，
 * 确认页说「3 单选」而实际发下来 2 道，是最难查的一类问题。
 *
 * ## 只给真的有题量的题型出卡片
 *
 * 原型固定画了「单选 / 多选 / 判断」三张。但题量本来就可能是 0（例如全是单选题），
 * 摆一张「0 多选题」的卡片除了占位没有任何信息量，所以这里按实际题量过滤。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect } from 'react'

import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { CONFIRM_COPY } from '../../constants/copy'
import { useQuizStore } from '../../store/useQuizStore'
import { estimateMinutes, QUESTION_TYPE_LABEL, questionStatEntries } from '../../utils/scoring'

import './index.scss'

export default function ConfirmPage() {
  const pendingQuiz = useQuizStore((s) => s.pendingQuiz)
  const start = useQuizStore((s) => s.start)

  // 没有题库就说明这一页是被错误地直接进入的（或小程序被重启过，
  // 内存里的题库没了）。与其渲染一个空壳，不如把用户送回大厅重新开始。
  useEffect(() => {
    if (pendingQuiz) return
    Taro.showToast({ title: '这份副本已经不在了，请重新召唤', icon: 'none' })
    const timer = setTimeout(() => {
      Taro.switchTab({ url: '/pages/hall/index' })
    }, 900)
    return () => clearTimeout(timer)
  }, [pendingQuiz])

  if (!pendingQuiz) {
    return (
      <PhoneShell
        navTitle={CONFIRM_COPY.navTitle}
        scroll={false}
        screenClassName='confirm confirm--empty'
      >
        <View className='spacer' />
        <View className='sub confirm__empty-text'>正在返回社团大厅…</View>
        <View className='spacer' />
      </PhoneShell>
    )
  }

  const stats = questionStatEntries(pendingQuiz.question_stats)
  // 3 种题型齐全时用三栏（与原型一致）；不足三种时用两栏，免得留一个刺眼的空位
  const gridClass = stats.length >= 3 ? 'grid3' : 'grid2'
  const minutes = estimateMinutes(pendingQuiz.questions.length)

  const handleStart = () => {
    start(pendingQuiz)
    // redirectTo：确认页的使命到此为止。若用 navigateTo，
    // 用户从答题页返回会撞回确认页，再点一次「开始」就会重启一局。
    Taro.redirectTo({ url: '/pages/quiz/index' })
  }

  const handleRegenerate = () => {
    // 同一条输入重出一份题。走 redirectTo 而不是 navigateTo：
    // 召唤页跑完还会 redirectTo 回本页，用 navigateTo 会让页面栈越堆越深。
    Taro.redirectTo({ url: '/pages/summon/index' })
  }

  return (
    <PhoneShell
      navTitle={CONFIRM_COPY.navTitle}
      navRight={CONFIRM_COPY.regenerate}
      onNavRightTap={handleRegenerate}
      screenClassName='confirm'
    >
      {/* 1 · 这是什么 */}
      <View className='card'>
        <View className='row confirm__head'>
          <Sprite name='shishi' size={56} />
          <View className='confirm__head-body'>
            <View className='between'>
              <Text className='pill blue'>知识副本</Text>
              <Text className='tiny'>约 {minutes} 分钟</Text>
            </View>
            <View className='h confirm__title'>{pendingQuiz.title}</View>
            <View className='body sm confirm__summary'>{pendingQuiz.summary}</View>
          </View>
        </View>
      </View>

      {/* 2 · 要花多久 */}
      <View className={gridClass}>
        {stats.map((entry) => (
          <View key={entry.type} className='card plain'>
            <View className='stat sm c-blue'>{entry.count}</View>
            <View className='statlab'>{QUESTION_TYPE_LABEL[entry.type]}</View>
          </View>
        ))}
      </View>

      {/* 3 · 会考到什么 */}
      {pendingQuiz.knowledge_points.length > 0 && (
        <View className='card'>
          <View className='tiny confirm__points-label'>{CONFIRM_COPY.knowledgeLabel}</View>
          <View className='row confirm__points'>
            {pendingQuiz.knowledge_points.map((point) => (
              <Text key={point} className='chip'>
                {point}
              </Text>
            ))}
          </View>
        </View>
      )}

      <View className='spacer' />

      {/* 4 · 开始 */}
      <Button className='btn confirm__start' onClick={handleStart}>
        {CONFIRM_COPY.start}
      </Button>
      <View className='tiny confirm__hint'>{CONFIRM_COPY.noPenaltyHint}</View>
    </PhoneShell>
  )
}
