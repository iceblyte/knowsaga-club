/**
 * 「本地没有可展示的报告」空态。
 *
 * ## 为什么需要它
 *
 * 总结页与建议页的数据来自 `useReportStore`（报告是**上一段流程**的产物），
 * 所以有两种进不来数据的正常情况，都不是 bug：
 *
 * 1. **深链 / 重新进入**：小程序重启后 store 回到初始态，而这两页
 *    仍可能被路由直接打开（开发者工具、分享链接、返回栈）。
 * 2. **报告还没生成**：用户从主视图跳过来时报告恰好还没好。
 *
 * 这两种情况都必须给出**能走的路**，而不是渲染一片空白 —— 空白会被读成
 * 「页面坏了」，而真实原因只是「你得先有一份报告」。
 *
 * ## 为什么不说「加载中」
 *
 * 本地没有就是本地没有，重新请求也不会变出来（这两页不发请求）。
 * 说「加载中」等于给用户一个永远不会结束的等待，比直说更糟。
 */

import { Button, Text, View } from '@tarojs/components'

import { REPORT_COPY } from '../../constants/copy'
import { goTab } from '../../utils/navigation'
import MagicStage from '../MagicStage'
import PhoneShell from '../PhoneShell'

import './index.scss'

export interface ReportMissingProps {
  /** 导览栏标题（两页各自不同） */
  navTitle: string
}

export default function ReportMissing({ navTitle }: ReportMissingProps) {
  return (
    <PhoneShell navTitle={navTitle} screenClassName='report-missing report-missing--center'>
      <View className='spacer' />
      <View className='report-missing__main'>
        <MagicStage size={150} spriteSize={64} sprite='momo' spriteMotion='floaty' />
        <View className='report-missing__text'>
          <Text className='h'>{REPORT_COPY.emptyTitle}</Text>
          <Text className='sub report-missing__desc'>{REPORT_COPY.emptyBody}</Text>
        </View>
      </View>
      <View className='spacer' />
      <Button className='btn ghost' onClick={() => goTab('/pages/report/index')}>
        {REPORT_COPY.navTitle}
      </Button>
    </PhoneShell>
  )
}
