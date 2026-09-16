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
 *
 * ## 没有题库时**不自动跳走**
 *
 * 题库只存在于内存里，页面被重新加载（例如小程序被重启）后就会丢。这时不能
 * 悄悄把用户弹回大厅 —— 那会让用户看到「点进来又被打回去」，还以为是自己点错了。
 * 正确做法是留在原地说明原因，并给一个明确的出口。
 */

import { Button, Text, View } from '@tarojs/components'
import { useEffect } from 'react'

import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { CONFIRM_COPY } from '../../constants/copy'
import { useQuizStore } from '../../store/useQuizStore'
import { goPage, goTab } from '../../utils/navigation'
import { estimateMinutes, QUESTION_TYPE_LABEL, questionStatEntries } from '../../utils/scoring'

import './index.scss'

export default function ConfirmPage() {
  const pendingQuiz = useQuizStore((s) => s.pendingQuiz)
  const start = useQuizStore((s) => s.start)

  // 本页只读 store，不需要副作用；保留 effect 是为了在题库意外消失时
  // 至少让开发者能在控制台看到一次线索
  useEffect(() => {
    if (pendingQuiz) return
    console.warn('[confirm] pendingQuiz 为空，无法进入副本')
  }, [pendingQuiz])

  if (!pendingQuiz) {
    return (
      <PhoneShell
        navTitle={CONFIRM_COPY.navTitle}
        scroll={false}
        screenClassName='confirm confirm--empty'
      >
        <View className='spacer' />
        <View className='h confirm__empty-text'>{CONFIRM_COPY.emptyTitle}</View>
        <View className='sub confirm__empty-text'>{CONFIRM_COPY.emptyHint}</View>
        <View className='spacer' />
        <Button className='btn' onClick={() => goTab('/pages/hall/index')}>
          {CONFIRM_COPY.backHome}
        </Button>
      </PhoneShell>
    )
  }

  const stats = questionStatEntries(pendingQuiz.question_stats)
  // 3 种题型齐全时用三栏（与原型一致）；不足三种时用两栏，免得留一个刺眼的空位
  const gridClass = stats.length >= 3 ? 'grid3' : 'grid2'
  const minutes = estimateMinutes(pendingQuiz.questions.length)

  const handleStart = () => {
    start(pendingQuiz)
    // 用 redirectTo 推进流程：确认页的使命到此为止。若用 navigateTo，
    // 用户从答题页返回会撞回确认页，再点一次「开始」就会重启一局。
    goPage('/pages/quiz/index', 'redirect')
  }

  const handleRegenerate = () => {
    // 同一条输入重出一份题。同样用 redirectTo 推进：
    // 召唤页跑完还会回到本页，用 navigateTo 会让页面栈越堆越深。
    goPage('/pages/summon/index', 'redirect')
  }

  return (
    <PhoneShell navTitle={CONFIRM_COPY.navTitle} screenClassName='confirm'>
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

      {/* 4 · 开始（次要动作放在主按钮下方，而不是导览栏右上角） */}
      <Button className='btn confirm__start' onClick={handleStart}>
        {CONFIRM_COPY.start}
      </Button>
      <Button className='btn ghost confirm__regenerate' onClick={handleRegenerate}>
        {CONFIRM_COPY.regenerate}
      </Button>
      <View className='tiny confirm__hint'>{CONFIRM_COPY.noPenaltyHint}</View>
    </PhoneShell>
  )
}
