/**
 * 挑战副本（原型 02 的九屏）。
 *
 * ## 判题在这一页，不在后端
 *
 * 已确认的决策：**本地即时判题**（开发计划 Phase 2 · 2.8）。正确答案随题库
 * 一起下发，所以「点选 → 变绿 → 发 XP」是零延迟的；走一趟网络会让本该
 * 即时的反馈被延迟绑架。后端只在 Phase 3 收**汇总结果**用于生成报告。
 *
 * ## 三种题型的交互差异是刻意的
 *
 * | 题型 | 提交方式 | 依据 |
 * |---|---|---|
 * | 单选 | 选中 → 点「确认作答」 | 原型第 1 屏有（禁用态）主按钮 |
 * | 多选 | 勾选多项 → 点「已选 N 项 · 确认作答」 | 原型第 4 屏 |
 * | 判断 | 点「正确 / 错误」大卡**直接判定** | 原型第 6 屏没有任何按钮 |
 *
 * 判断题「少一次确认」是原型明确的设计意图（批注：「判断题的选项键改用符号
 * 而非字母，减少一次语义转换」）。代价是点错即刻生效 —— 但答错不扣分，
 * 而且讲解会立刻给出正确项，所以这个代价很小。
 *
 * ## 与原型的一处必要差异：讲解卡不占满剩余高度
 *
 * 原型答对后的讲解卡带 `.grow`（吃掉剩余空间），于是它下方没有位置放
 * 「相关知识点」和「下一题」。但原型第 7 屏（讲解折叠态）明确有这两块。
 * 两者只能取一：这里选择**保留「下一题」**，让讲解卡按内容自然撑高。
 * 理由是没有「下一题」用户根本走不下去，而讲解卡撑满只是视觉习惯。
 */

import { Button, Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'

import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { QUIZ_COPY } from '../../constants/copy'
import { useQuizStore } from '../../store/useQuizStore'
import type { QuizQuestion, QuizOption } from '../../types/api'
import { goPage, goTab } from '../../utils/navigation'
import { gradeQuestion, maxXpOf, QUESTION_TYPE_LABEL, type QuestionResult } from '../../utils/scoring'
import { styleOf } from '../../utils/style'

import './index.scss'

/** 判断题的符号键（原型：「减少一次语义转换」） */
const JUDGE_SYMBOL: Record<string, string> = { T: '✓', F: '✗' }

/**
 * 一个选项的视觉状态。
 *
 * 顺序很重要：**正确项优先于用户的选择**。多选「部分正确」时，
 * 用户选错的项要标红、没选到的正确项也要标绿 —— 两者同时成立时，
 * 「这是正确答案」比「你选了这个」更该被表达出来。
 */
function optionClass(
  key: string,
  answered: boolean,
  picked: string[],
  answer: string[]
): string {
  if (!answered) {
    return picked.includes(key) ? 'opt sel' : 'opt'
  }
  if (answer.includes(key)) return 'opt ok'
  if (picked.includes(key)) return 'opt bad'
  return 'opt'
}

/** 判断题大卡的状态色（与选项同一套语义） */
function judgeCardClass(key: string, answered: boolean, picked: string[], answer: string[]): string {
  if (!answered) return 'card plain'
  if (answer.includes(key)) return 'card ok'
  if (picked.includes(key)) return 'card bad'
  return 'card plain'
}

function explanationTone(result: QuestionResult): { card: string; stamp: string; label: string } {
  if (result.outcome === 'correct') {
    return { card: 'card ok', stamp: 'stamp ok', label: '答对' }
  }
  if (result.outcome === 'partial') {
    return { card: 'card gold', stamp: 'stamp gold', label: '部分正确' }
  }
  return {
    card: 'card bad',
    // 原型：错误态的印章不带修饰类（朱砂色），文案用「正确答案是 C」
    // 而不是「你答错了」—— 措辞上不指责用户
    stamp: 'stamp',
    label: `正确答案 ${result.answer.join('、')}`
  }
}

/**
 * 多选得分的补充说明。
 *
 * 多选是三种题型里唯一「部分对也有分」的，规则不写明的话，
 * 「选了 2 项拿到 30 XP」会读起来像 bug。
 */
function multiNote(result: QuestionResult): string {
  if (result.type !== 'multiple') return ''
  if (result.outcome === 'partial') {
    return `多选题部分正确得一半经验值，本题得 ${result.earnedXp} XP。`
  }
  if (result.outcome === 'wrong' && result.selected.length > 0) {
    return '多选题选了错误选项就不计分，本题得 0 XP。'
  }
  if (result.outcome === 'wrong') {
    return '多选题没有作答，本题得 0 XP。'
  }
  return ''
}

export default function QuizPage() {
  const quiz = useQuizStore((s) => s.quiz)
  const currentIndex = useQuizStore((s) => s.currentIndex)
  const results = useQuizStore((s) => s.results)
  const recordResult = useQuizStore((s) => s.recordResult)
  const setCurrentIndex = useQuizStore((s) => s.setCurrentIndex)
  const finish = useQuizStore((s) => s.finish)
  const reset = useQuizStore((s) => s.reset)

  /** 当前题的勾选（未提交）。切题时清空 —— 折叠状态同理，题间不共享 */
  const [picked, setPicked] = useState<string[]>([])
  const [collapsed, setCollapsed] = useState(false)
  const [askExit, setAskExit] = useState(false)

  const question: QuizQuestion | undefined = quiz?.questions[currentIndex]

  // 换题就把本地交互状态归零：勾选、讲解折叠。
  // 放在 effect 里而不是各个 setState 处，是为了让「下一题」只有一个入口。
  useEffect(() => {
    setPicked([])
    setCollapsed(false)
  }, [currentIndex])

  const total = quiz?.questions.length ?? 0

  if (!quiz || !question) {
    return (
      <PhoneShell navTitle={QUIZ_COPY.navTitle} scroll={false} screenClassName='quiz quiz--empty'>
        <View className='spacer' />
        <View className='sub quiz__empty-text'>这一局已经结束了，请重新召唤副本</View>
        <View className='spacer' />
        <Button className='btn ghost' onClick={() => goTab('/pages/hall/index')}>
          回到社团大厅
        </Button>
      </PhoneShell>
    )
  }

  const result: QuestionResult | undefined = results[question.id]
  const answered = Boolean(result)
  const shownPicked = result ? result.selected : picked
  const isLast = currentIndex === total - 1
  const isMultiple = question.type === 'multiple'
  const maxXp = maxXpOf(question.type)

  const handleSelect = (key: string) => {
    if (answered) return

    // 判断题：大卡即提交（见文件头说明）
    if (question.type === 'judge') {
      recordResult(gradeQuestion(question, [key]))
      return
    }

    if (isMultiple) {
      setPicked((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]))
      return
    }

    setPicked([key])
  }

  const handleSubmit = () => {
    if (answered || picked.length === 0) return
    recordResult(gradeQuestion(question, picked))
  }

  const handleNext = () => {
    if (!isLast) {
      setCurrentIndex(currentIndex + 1)
      return
    }
    finish()
    goPage('/pages/settle/index', 'redirect')
  }

  const handleExit = () => {
    setAskExit(false)
    // 文案承诺了「离开后本局作答记录不会保留」，所以这里必须真的清空
    reset()
    goTab('/pages/hall/index')
  }

  const tone = result ? explanationTone(result) : null
  const note = result ? multiNote(result) : ''

  return (
    <PhoneShell
      navTitle={QUIZ_COPY.navTitle}
      onBack={() => setAskExit(true)}
      screenClassName='quiz'
    >
      {/* 顶部：题号 + 本题经验值 + 进度条 */}
      <View className='quiz__head'>
        <View className='between quiz__head-row'>
          <Text className='quiz__index'>
            第 {currentIndex + 1} / {total} 题
          </Text>
          <Text className='tiny c-gold'>+{result ? result.earnedXp : maxXp} XP</Text>
        </View>
        <View className='bar'>
          <View style={styleOf({ width: `${((currentIndex + 1) / total) * 100}%` })} />
        </View>
      </View>

      {/* 题干 */}
      <View className='card parch'>
        <Text className='pill'>{QUESTION_TYPE_LABEL[question.type]}</Text>
        <View className='quiz__stem'>{question.stem}</View>
      </View>

      {/* 选项 */}
      {question.type === 'judge' ? (
        <View className='grid2 quiz__judge'>
          {question.options.map((option: QuizOption) => (
            <View
              key={option.key}
              className={judgeCardClass(option.key, answered, shownPicked, question.answer)}
              onClick={() => handleSelect(option.key)}
            >
              <View className='quiz__judge-inner'>
                {/* ✓ / ✗ 是**语义图标**（「我认为这句话是对的」），不表示状态色，
                    所以不随判定结果变色 —— 判定结果由卡面底色表达 */}
                <Text
                  className={`quiz__judge-symbol ${option.key === 'T' ? 'c-ok' : 'c-bad'}`}
                >
                  {JUDGE_SYMBOL[option.key] ?? option.key}
                </Text>
                <Text className='quiz__judge-label'>{option.key === 'T' ? '正确' : '错误'}</Text>
              </View>
            </View>
          ))}
        </View>
      ) : (
        question.options.map((option: QuizOption) => (
          <View
            key={option.key}
            className={optionClass(option.key, answered, shownPicked, question.answer)}
            onClick={() => handleSelect(option.key)}
          >
            <Text className='k'>{option.key}</Text>
            <Text className='x'>{option.text}</Text>
          </View>
        ))
      )}

      {/* 讲解：答完立刻出现，默认展开 */}
      {result && tone && (
        <View className={tone.card}>
          <View className='row quiz__explain-head'>
            <Sprite name='momo' size={50} />
            <View className='quiz__explain-body'>
              <View className='between'>
                <Text className={tone.stamp}>{tone.label}</Text>
                <Text className='tiny' onClick={() => setCollapsed((value) => !value)}>
                  {collapsed ? QUIZ_COPY.expand : QUIZ_COPY.collapse}
                </Text>
              </View>
              {collapsed ? (
                <View className='tiny quiz__explain-hint'>{QUIZ_COPY.collapseHint}</View>
              ) : (
                <>
                  <View className='body sm quiz__explain-text'>{question.explanation}</View>
                  {note && <View className='tiny quiz__explain-note'>{note}</View>}
                </>
              )}
            </View>
          </View>
        </View>
      )}

      {/* 相关知识点 */}
      {result && (
        <View className='card plain'>
          <View className='tiny quiz__related-label'>{QUIZ_COPY.relatedLabel}</View>
          <View className='row quiz__related'>
            <Text className='chip'>{question.knowledge_point}</Text>
          </View>
        </View>
      )}

      <View className='spacer' />

      {/* 底部动作：未作答时是提交，已作答时是下一题 */}
      {!answered ? (
        <>
          {isLast && <View className='tiny quiz__last-hint'>{QUIZ_COPY.lastQuestionHint}</View>}
          <Button
            className={`btn${picked.length === 0 ? ' dis' : ''}`}
            disabled={picked.length === 0}
            onClick={handleSubmit}
          >
            {isMultiple && picked.length > 0
              ? QUIZ_COPY.submitMultiple(picked.length)
              : QUIZ_COPY.submit}
          </Button>
        </>
      ) : (
        <Button className='btn' onClick={handleNext}>
          {isLast ? QUIZ_COPY.last : QUIZ_COPY.next}
        </Button>
      )}

      {/* 退出确认 */}
      {askExit && (
        <View className='mask'>
          <View className='card plain quiz__dialog'>
            <Sprite name='shishi' size={76} />
            <View className='h quiz__dialog-title'>{QUIZ_COPY.exitTitle}</View>
            <View className='body sm quiz__dialog-body'>{QUIZ_COPY.exitBody}</View>
            <Button className='btn' onClick={() => setAskExit(false)}>
              {QUIZ_COPY.exitPrimary}
            </Button>
            <Button className='btn ghost quiz__dialog-secondary' onClick={handleExit}>
              {QUIZ_COPY.exitSecondary}
            </Button>
          </View>
        </View>
      )}
    </PhoneShell>
  )
}
