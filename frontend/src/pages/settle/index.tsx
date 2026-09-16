/**
 * 通关结算（原型 01 第 6 屏）。
 *
 * ## 这一页没有导览栏，也没有返回键 —— 这是原型的决定
 *
 * 原型这一屏只有状态栏 + 48px 空档 + 内容区，没有 `.nav`。理由说得通：
 * 结算之后回到答题页没有任何意义（题目已经全部作答），而唯一合理的两个
 * 出口就在页面上（查看冒险日志 / 再来一局）。所以这里 `showNav={false}`，
 * 并自己补一段与原型的 `height:48px` 等高的空档维持版式节奏。
 *
 * ## 数字与规则
 *
 * XP、金币、正确率全部由 `summarizeQuiz` 真实算出（§9）。
 * 唯独「超过社团里 N% 的冒险者」没有真实用户池，是正确率的确定性派生值 ——
 * 所以它**必须标注为演示数据**，而不是伪装成统计结果。
 */

import { Button, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import AccuracyRing from '../../components/AccuracyRing'
import MagicStage from '../../components/MagicStage'
import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { SETTLE_COPY } from '../../constants/copy'
import { useCountUp } from '../../hooks/useCountUp'
import { useQuizStore } from '../../store/useQuizStore'
import { summarizeQuiz } from '../../utils/scoring'

import './index.scss'

export default function SettlePage() {
  const quiz = useQuizStore((s) => s.quiz)
  const results = useQuizStore((s) => s.results)
  const startedAt = useQuizStore((s) => s.startedAt)
  const finishedAt = useQuizStore((s) => s.finishedAt)
  const reset = useQuizStore((s) => s.reset)

  const summary = quiz ? summarizeQuiz(quiz, results, startedAt, finishedAt) : null

  // 数字递增：XP 先滚，金币延后 120ms —— 错开就出现了「层次」
  const animatedXp = useCountUp(summary?.totalXp ?? 0, { delay: 0 })
  const animatedCoins = useCountUp(summary?.coins ?? 0, { delay: 120 })

  if (!quiz || !summary) {
    return (
      <PhoneShell scroll={false} showNav={false} screenClassName='settle settle--empty'>
        <View className='settle__nav-gap' />
        <View className='spacer' />
        <View className='sub settle__empty-text'>还没有可以结算的副本</View>
        <View className='spacer' />
        <Button className='btn ghost' onClick={() => Taro.switchTab({ url: '/pages/hall/index' })}>
          回到社团大厅
        </Button>
      </PhoneShell>
    )
  }

  const handleViewReport = () => {
    // 冒险日志是 Phase 3 的范围。这里保留原型的主 CTA，先切到日志标签页。
    Taro.switchTab({ url: '/pages/report/index' })
  }

  const handlePlayAgain = () => {
    // 清空这一局再回召唤页，否则上一局的判定结果会残留到新的一局
    reset()
    Taro.redirectTo({ url: '/pages/summon/index' })
  }

  return (
    <PhoneShell showNav={false} screenClassName='settle'>
      <View className='settle__nav-gap' />
      <View className='spacer' />

      <View className='settle__hero'>
        <MagicStage size={150} spriteSize={69} sprite='shishi' spriteMotion='floaty' />

        <View className='settle__caption'>
          <View className='settle__title'>{SETTLE_COPY.title}</View>
          <View className='sub settle__subtitle'>
            {quiz.title} · {summary.totalCount} 题全部完成
          </View>
          <View className='settle__stamp-slot'>
            <View className='stamp gold'>{SETTLE_COPY.badge}</View>
          </View>
        </View>
      </View>

      {/* 奖励两块 */}
      <View className='grid2 settle__rewards'>
        <View className='card gold'>
          <View className='stat c-gold'>+{animatedXp}</View>
          <View className='statlab'>{SETTLE_COPY.xpLabel}</View>
        </View>
        <View className='card gold'>
          <View className='row settle__coins'>
            <Sprite name='tongbao' size={42} />
            <View>
              <View className='stat sm c-gold'>+{animatedCoins}</View>
              <View className='statlab'>{SETTLE_COPY.coinsLabel}</View>
            </View>
          </View>
        </View>
      </View>

      {/* 正确率 */}
      <View className='card'>
        <View className='row settle__accuracy'>
          <AccuracyRing percent={summary.accuracy} size={64} />
          <View>
            <View className='settle__accuracy-title'>
              正确率 {summary.correctCount} / {summary.totalCount}
            </View>
            <View className='tiny settle__accuracy-note'>
              {SETTLE_COPY.percentilePrefix} {summary.percentile}% {SETTLE_COPY.percentileSuffix}
              {SETTLE_COPY.percentileNote}
            </View>
          </View>
        </View>
      </View>

      <View className='spacer' />

      <Button className='btn settle__action' onClick={handleViewReport}>
        {SETTLE_COPY.viewReport}
      </Button>
      <Button className='btn ghost settle__action-secondary' onClick={handlePlayAgain}>
        {SETTLE_COPY.playAgain}
      </Button>
    </PhoneShell>
  )
}
