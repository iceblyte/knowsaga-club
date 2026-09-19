/**
 * 错题本 · 旧识重温（原型 04·7）。
 *
 * ## 列表按「知识点」而不是按题干
 *
 * 原型这一屏的每一行标题是**知识点**（「RAG 与搜索引擎的边界」「分块策略对
 * 效果的影响」），不是完整题干 —— 它是按主题排的复习清单，逐题回看题干是
 * 卷轴详情（04·6）那一屏的事。所以这里照原型走：标题给知识点，
 * 副行给「来自哪份卷轴 · 答错几次 · 什么时候到期」。
 *
 * ## 每行右侧的「重做 / 待复习」是**状态标签，不是按钮**
 *
 * 原型里这两者是 `<span class="pill">`，没有点击行为。这与服务端能力也是一致的：
 * `POST /review/start` 把**所有到期错题**组成一局，没有「只重做这一道」的入口。
 * 把它们做成按钮，点了却整局开始，比不给按钮更让人困惑。
 * 真正的动作只有一个：页面底部的「开始旧识重温关卡」。
 *
 * ## 到期数与列表长度是两个数
 *
 * `due_count` 与 `total_count` 恒按整个队列统计，与筛选无关（服务端口径）。
 * 引言的「这 N 道题今天最适合重做」用的是**到期数** —— 列表里同时列着未到期的题，
 * 它们这次不会被带进关卡。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import { ARCHIVE_COMMON, REVIEW_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchWrongQuestions } from '../../../services/archive'
import { startReview } from '../../../services/review'
import { useQuizStore } from '../../../store/useQuizStore'
import { goPage, goTab } from '../../../utils/navigation'

import './index.scss'

export default function ReviewPage() {
  // 不带 `due`：原型这一屏同时列出到期与未到期的题，只是右侧标签不同
  const { status, data, reload } = useAsyncData(() => fetchWrongQuestions(false))
  const [starting, setStarting] = useState(false)

  const handleStart = async () => {
    if (starting) return
    setStarting(true)
    try {
      const result = await startReview()
      // 与「重做」走同一条路：`start()` 生成新的交卷令牌，
      // 所以复习这一局是一条**独立的挑战记录**，不会覆盖原来的错题来源那一局
      useQuizStore.getState().start(result.quiz)
      goPage('/pages/quiz/index', 'redirect')
    } catch (error) {
      // 没到期与组卷失败是两件事：前者说明「现在没什么可复习的」，后者要重试
      const code = (error as { code?: number } | null)?.code
      Taro.showToast({
        title: code === 4005 ? REVIEW_COPY.startEmpty : REVIEW_COPY.startFailed,
        icon: 'none'
      })
      // 4005 之后队列可能已经变了（比如在别处复习过），刷新一次让页面说实话
      if (code === 4005) reload()
    } finally {
      setStarting(false)
    }
  }

  if (!data) {
    return (
      <PhoneShell navTitle={REVIEW_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  if (data.total_count === 0) {
    return (
      <PhoneShell navTitle={REVIEW_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={REVIEW_COPY.emptyTitle}
          body={REVIEW_COPY.emptyBody}
          actionText={REVIEW_COPY.emptyCta}
          onAction={() => goTab('/pages/hall/index')}
        />
      </PhoneShell>
    )
  }

  const canStart = data.due_count > 0 && !starting

  return (
    <PhoneShell navTitle={REVIEW_COPY.navTitle}>
      <View className='card parch'>
        <View className='review__head'>
          <View className='between'>
            <Text className='tiny'>{REVIEW_COPY.sectionTitle}</Text>
            <Text className='pill bad'>{REVIEW_COPY.duePill(data.due_count)}</Text>
          </View>
          <View className='body sm review__intro'>
            {data.due_count > 0
              ? REVIEW_COPY.intro(data.due_count)
              : REVIEW_COPY.introNoDue}
          </View>
        </View>

        {data.items.map((item) => (
          <View className='li' key={item.question_id}>
            <View className='ico'>{REVIEW_COPY.icon}</View>

            <View className='tx'>
              <View className='n'>{item.knowledge_point || item.stem}</View>
              <View className='d'>
                {item.quiz_title} · {REVIEW_COPY.wrongTimes(item.wrong_count)} ·{' '}
                {item.next_review_label}
              </View>
            </View>

            <Text className='pill'>
              {item.due ? REVIEW_COPY.actionRedo : REVIEW_COPY.actionPending}
            </Text>
          </View>
        ))}
      </View>

      <View className='spacer' />

      <Button
        className={`btn${canStart ? '' : ' dis'}`}
        disabled={!canStart}
        onClick={handleStart}
      >
        {starting ? REVIEW_COPY.starting : REVIEW_COPY.start}
      </Button>
    </PhoneShell>
  )
}
