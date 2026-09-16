/**
 * 挑战副本（占位 —— Phase 2 实现原型 02 的九屏）。
 *
 * Phase 2 会替换为：三种题型渲染 + 选项四态（默认/已选/答对/答错）
 * + 本地即时判题 + 讲解卡（默认展开、可折叠）+ 顶部进度条与 `+N XP`
 * + 退出确认弹层 + 最后一题提交中。
 */

import ComingSoon from '../../components/ComingSoon'

export default function QuizPage() {
  return (
    <ComingSoon
      navTitle='挑战副本'
      headline='副本入口还没开'
      description='这里会逐题挑战，答完立刻看到讲解，答错不会扣分。'
      showHomeButton={false}
    />
  )
}
