/**
 * 网络异常（原型 03 第 7 屏）—— 全局断网降级态。
 *
 * ## 这一页与「报告生成失败」是两件事，所以不在同一个地方
 *
 * - **报告生成失败**：服务器答复了「这次生成失败」。原型的第 6 屏
 *   导览栏标题就是「冒险日志」，说明它是报告页自己的一个状态 →
 *   实现放在 `pages/report/index.tsx`。
 * - **网络异常**：连服务器都没连上。原型第 7 屏的导览栏写的是「社团大厅」，
 *   图注也点明这是「全局断网态，任何页面都要能优雅降级」→ 因此单独一页，
 *   任何需要联网的流程都可以把它当作最后的出口。
 *
 * 两者的下一步动作本来就不同（一个该重新生成报告，一个该检查网络），
 * 合并成一个「出错了」会让用户不知道该做什么 —— 而原型的图注明确要求
 * 「失败文案给出具体原因与重试动作」。
 *
 * ## 「查看历史日志」为什么只给提示
 *
 * 历史冒险日志是**已确认不做**的 MVP 之外功能（见 `docs/MVP开发计划.md` §3）。
 * 按钮位置与样式按原型保留，点击时明确说明 —— 与大厅页处理 P1 能力的方式一致：
 * 明说比静默失败好，比假装能用更好。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { REPORT_COPY } from '../../constants/copy'
import { fetchHealth } from '../../services/quiz'
import { goTab } from '../../utils/navigation'

import './index.scss'

export default function ExceptionPage() {
  /** 正在重连：防止连点发出多次探测 */
  const [busy, setBusy] = useState(false)

  const handleReconnect = async () => {
    if (busy) return
    setBusy(true)
    try {
      // 探测**真的通了**才走人。只弹一句「已重连」而不验证，
      // 会把用户丢回一个同样连不上的页面 —— 那比留在这里更让人困惑。
      await fetchHealth()
      goTab('/pages/hall/index')
    } catch {
      Taro.showToast({ title: '还是连不上，请检查网络后重试', icon: 'none' })
    } finally {
      setBusy(false)
    }
  }

  const handleHistory = () => {
    Taro.showToast({ title: REPORT_COPY.historyUnavailable, icon: 'none' })
  }

  return (
    <PhoneShell navTitle={REPORT_COPY.offlineNavTitle} screenClassName='exception exception--center'>
      <View className='spacer' />
      <View className='exception__main'>
        <Sprite name='shishi' size={96} />
        <View className='exception__text'>
          <Text className='h'>{REPORT_COPY.offlineTitle}</Text>
          <Text className='body sm exception__desc'>{REPORT_COPY.offlineBody}</Text>
        </View>
      </View>
      <View className='spacer' />
      <Button className='btn' disabled={busy} onClick={handleReconnect}>
        {REPORT_COPY.reconnect}
      </Button>
      <Button className='btn ghost exception__secondary' onClick={handleHistory}>
        {REPORT_COPY.viewHistory}
      </Button>
    </PhoneShell>
  )
}
