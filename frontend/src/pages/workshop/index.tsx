/**
 * 卷轴工坊（占位）。
 *
 * 已确认范围：`05-卷轴工坊` 属于 P1，本期不做。这里保留 tab 并给出空态，
 * 而不是把 tab 删掉 —— 原型的信息架构本身就是 5 个，
 * 砍掉会让产品立刻显得缺胳膊少腿；做成空态则能说明「这里以后会有什么」。
 */

import ComingSoon from '../../components/ComingSoon'

export default function WorkshopPage() {
  return (
    <ComingSoon
      navTitle='卷轴工坊'
      tabKey='workshop'
      headline='这一卷还在撰写中'
      description='卷轴工坊会支持上传文档、粘贴网址、追加背景资料。现在先去社团大厅，用一句话也能召唤副本。'
    />
  )
}
