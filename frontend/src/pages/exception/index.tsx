/**
 * 异常页（占位 —— Phase 3 实现原型 03 的两个异常屏）。
 *
 * Phase 3 会替换为：报告生成失败 / 网络异常两种形态，各自给出明确文案与重试动作。
 */

import ComingSoon from '../../components/ComingSoon'

export default function ExceptionPage() {
  return (
    <ComingSoon
      navTitle='出了点小状况'
      headline='一切正常'
      description='这一页会在出题失败或网络不通时出现，并给出明确的重试入口。'
    />
  )
}
