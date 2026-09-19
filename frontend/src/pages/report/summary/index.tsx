/**
 * 冒险日志 · 三句话总结（原型 03 第 2 屏）。
 *
 * ## 为什么是独立一页而不是主视图的一段
 *
 * 原型的第 1 / 2 / 3 屏各自有独立的导览栏标题（冒险日志 / 知识总结 /
 * 下一步建议），是三个样机屏；`docs/用户系统方案设计文档.md` §7.3 的页面清单
 * 也把它们列为 `pages/report`、`pages/report/summary`、`pages/report/suggestions`。
 * 拆开还有一个实际好处：三句话 + 两组知识点在手机上已经接近一屏，
 * 塞进主视图会让「正确率是唯一的大数字」这条设计意图消失。
 *
 * ## 数据只读
 *
 * 这一页**不发任何请求**，只读 `useReportStore` 里主视图已经拿到的报告 ——
 * 再请求一次既不必要（报告是同一份），也会让「返回主视图再进来」多一个转圈。
 *
 * ## 两个刻意的取舍
 *
 * 1. **知识点胶囊不可点**。原型图注说「点击可跳到对应题目的讲解」，
 *    但那需要「按知识点检索题目」的接口（属 Phase D 的错题本/复习范围）。
 *    本期渲染为静态胶囊 —— 看起来不能点，就没有「点了没反应」的困惑。
 * 2. **「复习薄弱知识点」按钮会提示「还没开放」**。它指向「旧识重温」复习流程
 *    （`pages/profile/review`，Phase D）。按钮位置与样式按原型保留，
 *    但点击时明确说明，而不是静默失败。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import PhoneShell from '../../../components/PhoneShell'
import ReportMissing from '../../../components/ReportMissing'
import Sprite from '../../../components/Sprite'
import { REPORT_COPY } from '../../../constants/copy'
import { useReportStore } from '../../../store/useReportStore'
import { goPage, goTab } from '../../../utils/navigation'

import './index.scss'

export default function ReportSummaryPage() {
  const report = useReportStore((s) => s.report)

  if (!report) {
    return <ReportMissing navTitle={REPORT_COPY.summaryNavTitle} />
  }

  return (
    <PhoneShell navTitle={REPORT_COPY.summaryNavTitle} screenClassName='report-summary'>
      <View className='card parch'>
        <View className='row report-summary__head'>
          <Text className='tiny'>{REPORT_COPY.summaryLabel}</Text>
          <Sprite name='momo' size={46} />
        </View>

        <View className='stack report-summary__lines'>
          {report.three_line_summary.map((line, index) => (
            <View key={`${index}-${line}`} className='row report-summary__line'>
              {/* 并列项的标记是方块而不是编号 —— 编号只用于真正的序列 */}
              <View className='dotmark report-summary__dot' />
              <Text className='body sm'>{line}</Text>
            </View>
          ))}
        </View>
      </View>

      <KnowledgeCard
        tone='ok'
        label={REPORT_COPY.masteredLabel}
        points={report.mastered_points}
      />
      <KnowledgeCard tone='bad' label={REPORT_COPY.weakLabel} points={report.weak_points} />

      <View className='spacer' />

      {/* 位置与样式按原型保留；能力属 Phase D，所以点了要说明白 */}
      <Button
        className='btn gold'
        onClick={() => Taro.showToast({ title: REPORT_COPY.reviewUnavailable, icon: 'none' })}
      >
        {REPORT_COPY.reviewWeak}
      </Button>
      <Button
        className='btn ghost report-summary__secondary'
        onClick={() => goPage('/pages/report/suggestions/index')}
      >
        {REPORT_COPY.suggestionsNavTitle}
      </Button>
      <Button
        className='btn ghost report-summary__secondary'
        onClick={() => goTab('/pages/report/index')}
      >
        {REPORT_COPY.backToReport}
      </Button>
    </PhoneShell>
  )
}

/**
 * 一组知识点胶囊。
 *
 * 某一组为空时**必须换一种说法**，不能只画一个空的标签区：
 * 全对的一局里「需要再巩固的知识点」本来就该是空的，
 * 留一个空标题会让用户以为这一项没加载出来。
 */
function KnowledgeCard({
  tone,
  label,
  points
}: {
  tone: 'ok' | 'bad'
  label: string
  points: string[]
}) {
  const emptyText = tone === 'ok' ? REPORT_COPY.noMastered : REPORT_COPY.noWeak

  return (
    <View className={`card ${tone}`}>
      <View className='tiny report-summary__label'>{label}</View>
      {points.length > 0 ? (
        <View className='row report-summary__pills'>
          {points.map((point) => (
            <Text key={point} className={`pill ${tone}`}>
              {point}
            </Text>
          ))}
        </View>
      ) : (
        <Text className='tiny'>{emptyText}</Text>
      )}
    </View>
  )
}
