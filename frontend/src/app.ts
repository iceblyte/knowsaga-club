import { PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'

import { ensureSession } from './services/auth'
import { fetchHealth } from './services/quiz'
import { useAppStore } from './store/useAppStore'

import './app.scss'

function App({ children }: PropsWithChildren<any>) {
  useLaunch(() => {
    // 静默登录：**不阻塞启动、失败也不提示**。理由有两条：
    //   1. 首屏（启动页 → 大厅）不需要登录态，用户不该为一个后台请求等；
    //   2. 真正需要登录态的请求（出题、交卷）自己在请求层等 `ensureSession`，
    //      所以这里只是把登录提前做完，不是唯一的发起入口。
    // 失败时的提示交给那些真正需要登录态的页面 —— 它们能给出「该做什么」。
    ensureSession().catch(() => undefined)

    // 启动时探测一次后端能力。目的有三个：
    //   1. 大厅页那个「AI 将联网补充 / 基于已有知识出题」的小胶囊要按真实配置
    //      说真话，而不是照抄原型写死联网；
    //   2. 私有知识库那几处入口（工坊两行 / 我的 / 大厅 chip）按
    //      `knowledge_base_enabled` 显隐 —— 值由后端给，前端不另配一份；
    //   3. 题目配图那两处入口（生成设置页的卡 / 大厅的 pill）按
    //      `image_generation_enabled` 显隐。后端下发的是**派生能力**
    //      （开关 && dashscope key && COS 凭据），所以前端不必自己拼判据。
    //
    // 失败时**不弹提示、不阻塞启动** —— 后端没起来是开发期的常态，
    // 让启动页因为一个探测请求而报错反而更糟。真正发起请求的页面
    // （副本召唤中）会给出可操作的错误提示。
    fetchHealth()
      .then((info) => {
        const store = useAppStore.getState()
        store.setBackendReachable(true)
        store.setSearchEnabled(info.search_enabled)
        store.setKnowledgeBaseEnabled(info.knowledge_base_enabled)
        store.setImageGenerationEnabled(info.image_generation_enabled)
      })
      .catch(() => {
        useAppStore.getState().setBackendReachable(false)
      })
  })

  // children 是将要会渲染的页面
  return children
}

export default App
