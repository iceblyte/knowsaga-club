/**
 * 副本确认页（占位 —— Phase 2 实现原型 01 第 5 屏）。
 *
 * Phase 2 会替换为：题库标题 / 摘要 / 题型构成（3 单选 · 1 多选 · 1 判断）
 * + 知识点 chip。数据全部来自真实题库的派生字段，前端不做二次计算。
 */

import ComingSoon from '../../components/ComingSoon'

export default function ConfirmPage() {
  return (
    <ComingSoon
      navTitle='副本确认'
      headline='题目还在路上'
      description='这里会列出本次副本的题型构成与知识点，确认后就可以开始挑战。'
      showHomeButton={false}
    />
  )
}
