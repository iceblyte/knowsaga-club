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
 * ## 口径：本地先算，服务端说了算
 *
 * 数字有**两个来源**，这不是冗余，而是各自承担不同职责：
 *
 * | 来源 | 作用 |
 * |---|---|
 * | `summarizeQuiz`（本地） | **即时**。进页面就有数，动画立刻开始，不被网络延迟绑架 |
 * | `POST /attempts`（服务端） | **权威**。档案里的 XP / 等级 / 连续天数以它为准（§6.5） |
 *
 * 两者的规则由 `shared/scoring-cases.json` 逐用例锁死（pytest 与
 * `npm run check:scoring` 双向校验），所以**正常路径下两边的数字逐位相同** ——
 * 页面因此不会出现「先显示 200、随后跳成别的」这种抖动。
 * 万一不同（题库快照变了、客户端被改过），显示切到服务端值，
 * 由 `useCountUp` 从当前值接着滚，不会出现重头再滚一次的视觉故障。
 *
 * ## 提交失败不打扰用户
 *
 * 交卷失败时**什么都不提示**，页面继续用本地数字。理由：
 *  - 用户此刻看到的是自己刚答完的分数，弹一个「提交失败」只会制造焦虑，
 *    而他能做的动作（重试）我们也已经做了；
 *  - 请求层在 4010 时会静默重建登录态并重试一次；
 *  - 真丢失的只是档案侧的累计值，本局体验不受影响。
 *  这个取舍写在 `docs/用户系统方案设计文档.md` 的结算一节。
 *
 * ## 幂等是这一页能安全重试的前提
 *
 * `clientToken` 在 `start()` 时就生成了（见 `store/useQuizStore`），
 * 所以本页重挂载、React 严格模式的双次 effect、用户手动重试，
 * 全都复用同一个令牌 —— 服务端只会落一条挑战记录。
 */

import { Button, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useMemo } from 'react'

import AccuracyRing from '../../components/AccuracyRing'
import MagicStage from '../../components/MagicStage'
import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { SETTLE_COPY } from '../../constants/copy'
import { useCountUp } from '../../hooks/useCountUp'
import { submitAttempt } from '../../services/attempt'
import { useQuizStore } from '../../store/useQuizStore'
import { useReportStore } from '../../store/useReportStore'
import { goPage, goTab } from '../../utils/navigation'
import { summarizeQuiz } from '../../utils/scoring'

import './index.scss'

export default function SettlePage() {
  const quiz = useQuizStore((s) => s.quiz)
  const results = useQuizStore((s) => s.results)
  const startedAt = useQuizStore((s) => s.startedAt)
  const finishedAt = useQuizStore((s) => s.finishedAt)
  const clientToken = useQuizStore((s) => s.clientToken)
  const attempt = useQuizStore((s) => s.attempt)
  const setAttempt = useQuizStore((s) => s.setAttempt)
  const reset = useQuizStore((s) => s.reset)

  /**
   * 本地口径。**必须 memo**：`summarizeQuiz` 每次都返回新对象，
   * 直接当成依赖会让提交 effect 在每次渲染（数字动画每 16ms 一次）
   * 都重跑一遍 —— 那就是几十次重复交卷。
   */
  const local = useMemo(
    () => (quiz ? summarizeQuiz(quiz, results, startedAt, finishedAt) : null),
    [quiz, results, startedAt, finishedAt]
  )

  /** 展示口径：服务端有结果就用它，否则先用本地值 */
  const view = useMemo(() => {
    if (!local || !quiz) return null
    const server = attempt?.summary
    return {
      title: quiz.title,
      totalCount: server?.total_count ?? local.totalCount,
      correctCount: server?.correct_count ?? local.correctCount,
      accuracy: server?.accuracy ?? local.accuracy,
      totalXp: server?.xp_gained ?? local.totalXp,
      coins: server?.coins_gained ?? local.coins,
      percentile: server?.percentile ?? local.percentile
    }
  }, [local, quiz, attempt])

  /**
   * 交卷。只发一次 —— 令牌与 `attempt` 一起构成闸门：
   * 已经有服务端结果就不再发，重挂载也拿得到同一个结果。
   */
  useEffect(() => {
    if (!quiz || !local || attempt || !clientToken) return

    let alive = true

    submitAttempt({
      quiz_id: quiz.quiz_id,
      client_token: clientToken,
      started_at: startedAt,
      // `finish()` 一定在跳转前调用过；兜底取当前时间只是为了不把 0 发给服务端
      finished_at: finishedAt || Date.now(),
      // 只报作答过的题。未作答的题不传，服务端按「未作答」计 0 分 ——
      // 与本地 `summarizeQuiz` 的补位口径一致。
      // `time_spent_ms` 本轮不采集（答题页没有逐题计时），服务端默认为 0。
      answers: local.results
        .filter((item) => item.selected.length > 0)
        .map((item) => ({ question_id: item.questionId, selected: item.selected }))
    })
      .then((response) => {
        if (alive) setAttempt(response)
      })
      .catch(() => {
        // 静默降级：本地数字已是同一套规则算出来的，页面继续可用。
        // 见文件头「提交失败不打扰用户」。
      })

    return () => {
      alive = false
    }
  }, [quiz, local, attempt, clientToken, startedAt, finishedAt, setAttempt])

  // 数字递增：XP 先滚，金币延后 120ms —— 错开就出现了「层次」
  const animatedXp = useCountUp(view?.totalXp ?? 0, { delay: 0 })
  const animatedCoins = useCountUp(view?.coins ?? 0, { delay: 120 })

  if (!quiz || !view) {
    return (
      <PhoneShell scroll={false} showNav={false} screenClassName='settle settle--empty'>
        <View className='settle__nav-gap' />
        <View className='spacer' />
        <View className='sub settle__empty-text'>还没有可以结算的副本</View>
        <View className='spacer' />
        <Button className='btn ghost' onClick={() => goTab('/pages/hall/index')}>
          回到社团大厅
        </Button>
      </PhoneShell>
    )
  }

  const handleViewReport = () => {
    const id = attempt?.attempt_id
    if (!id) {
      // 交卷没送到服务端 → 服务端没有这一局，报告无从生成。
      // 跳到日志页只会看到一个空态，用户会以为报告功能坏了 ——
      // 留在原地说明原因更好，本页的数字本来就是对的。
      Taro.showToast({ title: SETTLE_COPY.reportUnavailable, icon: 'none' })
      return
    }
    // 把「要给哪一局出报告」交给日志页。放在这里而不是让它去猜，
    // 是因为日志页是标签页，可能在任何时刻被点开 —— 它需要一个明确的目标。
    useReportStore.getState().begin(id)
    goTab('/pages/report/index')
  }

  const handlePlayAgain = () => {
    // 清空这一局再回召唤页，否则上一局的判定结果会残留到新的一局
    reset()
    goPage('/pages/summon/index', 'redirect')
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
            {view.title} · {view.totalCount} 题全部完成
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
          <AccuracyRing percent={view.accuracy} size={64} />
          <View>
            <View className='settle__accuracy-title'>
              正确率 {view.correctCount} / {view.totalCount}
            </View>
            <View className='tiny settle__accuracy-note'>
              {SETTLE_COPY.percentilePrefix} {view.percentile}% {SETTLE_COPY.percentileSuffix}
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
