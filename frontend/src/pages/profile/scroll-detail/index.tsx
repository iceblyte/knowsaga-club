/**
 * 卷轴详情（原型 04·6）。
 *
 * ## 回看的是**当时**的答案
 *
 * 题干 / 选项 / 正确答案 / 讲解全部来自 `questions` —— 那张表本身存的就是
 * 快照（出题落库时把 `stem`/`options`/`answer`/`explanation` 一起写了进去），
 * 所以历史卷轴能无限期回看，不受后续重新出题影响。
 * 「我的答案」读的也是服务端存下来的那一局的作答，不是最新一局 ——
 * 用户重做几轮之后回看，看到的仍是当时选了什么，这正是历史记录的意义。
 *
 * ## 讲解默认收起
 *
 * 原型图注要求「可展开任意一题重看讲解」，但静态版画的三张卡都是收起的。
 * 这一屏的定位是快速回看每一题当时答了什么；5 道题的讲解全铺开会把作答
 * 记录挤散。所以默认收起、逐题展开 —— 与答题页相反，那边刚作答完，
 * 讲解是必须立刻看到的反馈。
 *
 * ## 「不在了」与「加载失败」是两个状态
 *
 * 别人删过这一条、或路由参数没传进来时，`fetchScrollDetail` 回 4005。
 * 那不是网络问题，重新加载一百次也不会变出来 —— 所以要给出口（回列表），
 * 而不是给「重试」。
 *
 * ## 参数缺失时**不能**照常发请求
 *
 * `attempt_id` 为空时如果照常拼路径，`GET /users/me/scrolls/` 会命中**列表**
 * 接口（尾斜杠被规范化掉了），返回的结构完全不同 —— 页面会拿着一个列表
 * 当详情去读 `questions`，然后崩在一个与根因毫无关系的地方。
 * 所以空参数直接短路，不去碰网络。
 */

import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import AccuracyRing from '../../../components/AccuracyRing'
import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import { ARCHIVE_COMMON, SCROLL_DETAIL_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchScrollDetail } from '../../../services/archive'
import { retryAttempt } from '../../../services/attempt'
import { useQuizStore } from '../../../store/useQuizStore'
import type { AttemptOutcome, ScrollQuestionItem } from '../../../types/api'
import { formatDuration } from '../../../utils/datetime'
import { goPage } from '../../../utils/navigation'
import { QUESTION_TYPE_SHORT } from '../../../utils/scoring'

import './index.scss'

/** 「资源不存在或无权访问」—— 后端对「不存在」与「不是你的」刻意回同一个码 */
const CODE_RESOURCE_NOT_FOUND = 4005

/** 正确率环的直径，写原型 px（原型这一屏的环是 58，比结算页略小） */
const RING_SIZE = 58

/**
 * 判定结果对应的三处外观。
 *
 * 卡面底色照原型：答对是普通纸面、部分正确是黄铜纸面。
 * 答错原型没有样例，沿用设计系统里既有的 `card bad`（与答题页一致）。
 */
const OUTCOME_TONE: Record<AttemptOutcome, { label: string; pill: string; card: string }> = {
  correct: { label: SCROLL_DETAIL_COPY.outcomeCorrect, pill: 'pill ok', card: 'card' },
  partial: { label: SCROLL_DETAIL_COPY.outcomePartial, pill: 'pill gold', card: 'card gold' },
  wrong: { label: SCROLL_DETAIL_COPY.outcomeWrong, pill: 'pill bad', card: 'card bad' }
}

/** 选项键 → 「A、C」（原型用顿号连，且前后不加空格） */
function joinKeys(keys: string[]): string {
  return keys.join('、')
}

/**
 * 「我的答案」那一行。
 *
 * 三种情况分开写而不是硬拼：一个都没选就交卷时（多选可以空交），
 * 「我的答案：」后面没有内容可写 —— 拼出来会是「我的答案： · 正确答案 A、C」，
 * 读起来像渲染坏了。
 */
function answerLine(item: ScrollQuestionItem): string {
  const mine = joinKeys(item.selected)
  const answer = joinKeys(item.answer)
  if (item.selected.length === 0) return SCROLL_DETAIL_COPY.answerBlank(answer)
  if (item.outcome === 'correct') return SCROLL_DETAIL_COPY.answerExact(mine)
  return SCROLL_DETAIL_COPY.answerDiff(mine, answer)
}

export default function ScrollDetailPage() {
  const router = useRouter<{ attempt_id: string }>()
  const attemptId = router.params?.attempt_id ?? ''

  // 空参数短路：不发请求，直接落到下面的「不在了」分支。
  // 把 `null` 当正常结果返回（而不是 reject）—— 它不是一个错误，
  // 只是一个我们不打算去取的状态，用 reject 会把它混进「加载失败」里。
  const { status, data, error, reload } = useAsyncData(
    () => (attemptId ? fetchScrollDetail(attemptId) : Promise.resolve(null)),
    attemptId
  )

  /** 已展开讲解的题号集合（多题可以同时展开） */
  const [openSeqs, setOpenSeqs] = useState<Record<number, boolean>>({})
  const [retrying, setRetrying] = useState(false)

  const toggleExplain = (seq: number) => {
    setOpenSeqs((prev) => ({ ...prev, [seq]: !prev[seq] }))
  }

  /** 回列表。详情页总是从列表下钻进来的，所以优先走返回 */
  const backToScrolls = () => {
    Taro.navigateBack({ delta: 1 }).catch(() => {
      goPage('/pages/profile/scrolls/index', 'redirect')
    })
  }

  const handleRetry = async () => {
    if (retrying || !attemptId) return
    setRetrying(true)
    try {
      const result = await retryAttempt(attemptId)
      // 与「复习关卡」走同一条路：`start()` 生成新的交卷令牌，
      // 所以重做这一局是一条**独立的挑战记录**，不会覆盖原来那一局
      useQuizStore.getState().start(result.quiz)
      goPage('/pages/quiz/index', 'redirect')
    } catch {
      Taro.showToast({ title: SCROLL_DETAIL_COPY.retryFailed, icon: 'none' })
    } finally {
      setRetrying(false)
    }
  }

  const gone = !attemptId || (error as { code?: number } | null)?.code === CODE_RESOURCE_NOT_FOUND

  if (gone) {
    return (
      <PhoneShell navTitle={SCROLL_DETAIL_COPY.navTitle}>
        <ArchiveState
          kind='error'
          title={SCROLL_DETAIL_COPY.goneTitle}
          body={SCROLL_DETAIL_COPY.goneBody}
          actionText={SCROLL_DETAIL_COPY.goneCta}
          onAction={backToScrolls}
        />
      </PhoneShell>
    )
  }

  if (!data) {
    return (
      <PhoneShell navTitle={SCROLL_DETAIL_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  return (
    <PhoneShell navTitle={SCROLL_DETAIL_COPY.navTitle}>
      {/* ---- 汇总 ---- */}
      <View className='card'>
        <View className='between'>
          <View className='detail__head'>
            <View className='h sm'>{data.title}</View>
            <View className='tiny detail__meta'>
              {SCROLL_DETAIL_COPY.meta(data.finished_label, formatDuration(data.duration_ms))}
            </View>
          </View>

          <AccuracyRing percent={data.accuracy} size={RING_SIZE} />
        </View>
      </View>

      {/* ---- 逐题回看 ---- */}
      {data.questions.map((item) => {
        const tone = OUTCOME_TONE[item.outcome]
        const expanded = Boolean(openSeqs[item.seq])

        return (
          <View className={tone.card} key={item.seq}>
            <View className='between'>
              <Text className='tiny'>
                {SCROLL_DETAIL_COPY.questionLabel(item.seq, QUESTION_TYPE_SHORT[item.type])}
              </Text>
              <Text className={tone.pill}>{tone.label}</Text>
            </View>

            {/* 当年那一局的配图（`add-question-image-generation`）。
                与答题页同一版位（题干上方），也同一条规矩：没有图就什么都不画 ——
                `image_url` 为 `null` 是常态，留空框等于承诺一张不会来的图。
                这里是**回看**，图与题干一样来自 `questions` 的快照，
                所以看到的正是当时那张。 */}
            {item.image_url ? (
              <Image className='detail__figure' src={item.image_url} mode='widthFix' />
            ) : null}

            <View className='body sm detail__stem'>{item.stem}</View>

            <View className='tiny detail__answer'>{answerLine(item)}</View>

            {/* 讲解开关：收起时是一句提示，展开后变成「收起讲解」 */}
            <View className='tiny detail__toggle' onClick={() => toggleExplain(item.seq)}>
              {expanded ? SCROLL_DETAIL_COPY.collapse : SCROLL_DETAIL_COPY.explainHint}
            </View>

            {expanded ? <View className='body sm detail__explain'>{item.explanation}</View> : null}
          </View>
        )
      })}

      <View className='spacer' />

      <Button
        className={`btn ghost${retrying ? ' dis' : ''}`}
        disabled={retrying}
        onClick={handleRetry}
      >
        {retrying ? SCROLL_DETAIL_COPY.retryStarting : SCROLL_DETAIL_COPY.retry}
      </Button>
    </PhoneShell>
  )
}
