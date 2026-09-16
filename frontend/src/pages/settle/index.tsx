/**
 * 通关结算（占位 —— Phase 2 实现原型 01 第 6 屏）。
 *
 * Phase 2 会替换为：XP / 金币 0.8s 递增动画 + 正确率环（0.3s 延后绘制，用 Canvas 2D）。
 */

import ComingSoon from '../../components/ComingSoon'

export default function SettlePage() {
  return (
    <ComingSoon
      navTitle='通关结算'
      headline='还没到结算的时候'
      description='通关后会在这里看到本局拿到的经验值、金币与正确率。'
      showHomeButton={false}
    />
  )
}
