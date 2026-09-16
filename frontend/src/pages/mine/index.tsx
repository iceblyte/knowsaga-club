/**
 * 我的（占位）。
 *
 * 已确认范围：`07-会员与设置` 属于 P2/P3，本期只做原型 01 大厅底部那张
 * 「冒险者档案卡」（等级 / 经验 / 连击天数，全部是演示数据）。
 * 本页保留 tab，给出空态说明后续会有什么。
 */

import ComingSoon from '../../components/ComingSoon'

export default function MinePage() {
  return (
    <ComingSoon
      navTitle='我的'
      tabKey='mine'
      headline='冒险者档案还在装订'
      description='这里会展示你的等级、经验值、连击天数与勋章墙。你每闯过一次副本，都在为它积累素材。'
    />
  )
}
