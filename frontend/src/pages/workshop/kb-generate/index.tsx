/**
 * 从知识库出题（原型 05·8）。
 *
 * ## 这一页只做一件事：把这些选择**写进 store**，然后交给召唤页
 *
 * 它自己**不发** `POST /quiz/generate`。那条链（建任务 → 轮询 → 三步进度 →
 * 失败与取消 → 生成好之后进确认页）已经完整地在召唤页里，包括「重新生成」。
 * 在这一页再写一遍就等于开第二条出题链：两边的轮询上限、降级、进度文案
 * 迟早会不一致，而用户看到的是「从大厅出题」与「从知识库出题」两种脾气。
 *
 * 所以这里只把三件事写进 store，然后 `goPage('/pages/summon/index')`：
 * 学习需求（`userInput`）、出题参数（题量 / 难度 / 知识库）、联网意愿。
 *
 * ## 学习需求是**前端构造**的（design D14）
 *
 * 这一页没有输入框（原型也没有），而后端 `user_input` 有 8 字下限
 * （`MIN_INPUT_LEN`）。所以提交 `学习「{库名}」中的内容`：库名最短 2 个字，
 * 整句最短 10 个字，稳过下限；同时它**兼作知识库检索的查询语义**
 * （后端的 Human 消息把这句话当主题）。
 *
 * **不放宽那条下限** —— 它服务的是所有入口，为一个页面放宽会把校验边界搞模糊。
 *
 * ## 题量与难度的选项比原型少，是有意的
 *
 * 原型给「3 / 5 / 10 题 / 自定义」与「题型（单选 3 / 多选 1 / 判断 1）」。
 * 这一版只有「3 / 5」两档、且**不渲染题型控件**：
 *
 * - 后端 `MAX_QUESTIONS = 5` 是硬上限（用户已明确本期不放宽），
 *   「10 题」与「自定义」点下去必然失败；
 * - 出题链没有题型控制面，加一个控件等于画一个兑不了的按钮。
 *
 * 两条都登记在 `constants/copy.ts` 文件头第 5 条与 design 的偏离表里。
 *
 * ## 未就绪的库**这一页自己拦**，且按钮在进来之前就已经是灰的
 *
 * 原型 05·5 的批注要求「未就绪的库不允许出题」。判据是后端 `GET /kb` 给的
 * `ready_count`，一次查询就能做对 —— 所以详情页与列表页在 `ready_count === 0`
 * 时就不会把用户放进这一页（design D17 把这道闸门放在前端）。
 * 但**从 URL 直接进来**（分享、回退、手改参数）也可能碰到未就绪的库，
 * 所以这一页仍然自己判一次，判到就把按钮置灰并说明原因 ——
 * 不依赖「上游一定已经拦过」。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import { ERROR_CODE } from '../../../constants/api'
import {
  ARCHIVE_COMMON,
  KB_COMMON,
  KB_DETAIL_COPY,
  KB_GENERATE_COPY
} from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchBaseDetail } from '../../../services/kb'
import { useAppStore } from '../../../store/useAppStore'
import type { Difficulty } from '../../../types/api'
import { goPage } from '../../../utils/navigation'

import './index.scss'

type DifficultyKey = Difficulty | 'mixed'

export default function KbGeneratePage() {
  const router = useRouter<{ kb_id: string }>()
  const kbId = (router.params?.kb_id ?? '').trim()

  const setUserInput = useAppStore((s) => s.setUserInput)
  const setQuizOptions = useAppStore((s) => s.setQuizOptions)
  const searchEnabled = useAppStore((s) => s.searchEnabled)
  const useSearch = useAppStore((s) => s.useSearch)
  const setUseSearch = useAppStore((s) => s.setUseSearch)

  const { status, data, error, reload } = useAsyncData(
    () => fetchBaseDetail(kbId),
    kbId || '__missing__'
  )

  /** 题量：默认取原型最常用的 5 题 */
  const [questionCount, setQuestionCount] = useState<number>(5)
  /** 难度：默认「均衡」，与后端 `mixed` 对齐 */
  const [difficulty, setDifficulty] = useState<DifficultyKey>('mixed')

  const notFound =
    !kbId || (error as { code?: number } | null)?.code === ERROR_CODE.RESOURCE_NOT_FOUND

  const toggleSearch = () => {
    if (!searchEnabled) {
      Taro.showToast({ title: KB_GENERATE_COPY.searchToggleUnavailable, icon: 'none' })
      return
    }
    setUseSearch(!useSearch)
  }

  if (notFound) {
    return (
      <PhoneShell navTitle={KB_GENERATE_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={KB_COMMON.notFound}
          body='它可能已经被删除，或者不属于当前账号。'
          actionText='回到知识库'
          onAction={() => goPage('/pages/workshop/kb-list/index', 'redirect')}
        />
      </PhoneShell>
    )
  }

  if (status === 'error') {
    return (
      <PhoneShell navTitle={KB_GENERATE_COPY.navTitle}>
        <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
      </PhoneShell>
    )
  }

  if (!data) {
    return (
      <PhoneShell navTitle={KB_GENERATE_COPY.navTitle}>
        <ArchiveState kind='loading' />
      </PhoneShell>
    )
  }

  const { base, documents } = data
  const chunkTotal = documents.reduce((sum, doc) => sum + doc.chunk_count, 0)
  const canAsk = base.ready_count > 0
  const searchOn = searchEnabled && useSearch

  const handleSubmit = () => {
    if (!canAsk) return
    // 1 · 学习需求（≥10 字，稳过 8 字下限；同时是知识库检索的查询语义）
    setUserInput(KB_GENERATE_COPY.inputOf(base.name))
    // 2 · 出题参数（题量 / 难度 / 取材的库）
    setQuizOptions({ questionCount, difficulty, kbId: base.id })
    // 3 · 联网意愿：沿用这一页上那只 pill 的当前值
    setUseSearch(useSearch)
    // 出题链从召唤页走 —— 这一页的使命到此为止，用 redirect 推进流程
    goPage('/pages/summon/index', 'redirect')
  }

  return (
    <PhoneShell navTitle={KB_GENERATE_COPY.navTitle}>
      {/* ---- 出题来源 ---- */}
      <View className='card'>
        <View className='kb-generate__label'>{KB_GENERATE_COPY.sourceLabel}</View>
        <View className='h kb-generate__source-name'>{base.name}</View>
        <View className='tiny'>
          {KB_GENERATE_COPY.sourceMeta(base.document_count, chunkTotal)}
        </View>
      </View>

      {/* ---- 题量 ---- */}
      <View className='card'>
        <View className='kb-generate__label'>{KB_GENERATE_COPY.countLabel}</View>
        <View className='kb-generate__options'>
          {KB_GENERATE_COPY.countOptions.map((count) => (
            <Text
              className={`chip${questionCount === count ? ' on' : ''}`}
              key={count}
              onClick={() => setQuestionCount(count)}
            >
              {KB_GENERATE_COPY.countLabelOf(count)}
            </Text>
          ))}
        </View>
      </View>

      {/* ---- 难度 ---- */}
      <View className='card'>
        <View className='kb-generate__label'>{KB_GENERATE_COPY.difficultyLabel}</View>
        <View className='kb-generate__options'>
          {KB_GENERATE_COPY.difficultyOptions.map((option) => (
            <Text
              className={`chip${difficulty === option.key ? ' on' : ''}`}
              key={option.key}
              onClick={() => setDifficulty(option.key)}
            >
              {option.label}
            </Text>
          ))}
        </View>
      </View>

      {/* ---- 联网补充 ---- */}
      <View className='card'>
        <View className='between'>
          <View className='kb-generate__label'>{KB_GENERATE_COPY.searchLabel}</View>
          <Text
            className={`pill${searchOn ? ' blue' : ''}`}
            onClick={toggleSearch}
          >
            {searchOn ? KB_GENERATE_COPY.searchOn : KB_GENERATE_COPY.searchOff}
          </Text>
        </View>
      </View>

      <View className='spacer' />

      <Button
        className={`btn${canAsk ? '' : ' dis'}`}
        disabled={!canAsk}
        onClick={handleSubmit}
      >
        {KB_GENERATE_COPY.submit}
      </Button>
      {/* 见文件头：上游已经拦过一道，但直接进 URL 的路径也得有自己的判据 */}
      {!canAsk ? (
        <View className='tiny kb-generate__hint'>{KB_DETAIL_COPY.askBlockedHint}</View>
      ) : null}
    </PhoneShell>
  )
}
