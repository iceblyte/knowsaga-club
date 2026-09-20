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
 * ## 「查看历史日志」已经能真的跳过去
 *
 * 这个按钮原来只弹一句「历史日志还没开放」——那是 `docs/MVP开发计划.md §1`
 * 第 8 行「历史冒险日志不做」时期的说法。该决策已在
 * `docs/用户系统需求分析文档.md` §8 第 8 行**修订为「做」**，并随 Phase E
 * 落地成「历史卷轴」（04·5 列表 / 04·6 详情）。所以这里改成真跳转。
 *
 * ⚠️ 它是 `navigate` 而不是 `redirect`：断网时用户点进来多半只是想确认
 * 「我的记录还在不在」，看完要能退回来重连。而真正的降级也在对面那一页：
 * 断网仍在时，历史卷轴会显示自己的失败态与「重新加载」，
 * 不在这里假装能离线读（本实现没有离线缓存）。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import PhoneShell from '../../components/PhoneShell'
import Sprite from '../../components/Sprite'
import { REPORT_COPY } from '../../constants/copy'
import { fetchHealth } from '../../services/quiz'
import { goPage, goTab } from '../../utils/navigation'

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
    goPage('/pages/profile/scrolls/index', 'navigate')
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
