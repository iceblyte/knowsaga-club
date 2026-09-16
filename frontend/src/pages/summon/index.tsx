/**
 * 副本召唤中（占位 —— Phase 2 实现原型 01 第 4 屏）。
 *
 * Phase 2 会替换为：三步状态卡（名字与详情全部来自后端 `GET /tasks/{id}` 的 `steps`）
 * + 进度条 + 轮询 + 8s 后出现的「取消」+ 失败重试。
 *
 * 当前占位是为了让 `app.config.ts` 声明的路由全部可解析 ——
 * 只声明不存在的路由会让 `build:weapp` 直接失败。
 */

import ComingSoon from '../../components/ComingSoon'

export default function SummonPage() {
  return (
    <ComingSoon
      navTitle='副本召唤中'
      headline='这里马上会有动静'
      description='这一步会实时显示 AI 理解需求、生成题目、校验结构的进度。'
      showHomeButton={false}
    />
  )
}
