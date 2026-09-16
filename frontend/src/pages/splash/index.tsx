/**
 * 启动页 · 卷轴展开（原型 01 第 1 屏）。
 *
 * 目的：用「展开的魔法阵」替代冷启动白屏，并用分阶段文案避免用户误判卡死。
 *
 * 与原型的两处实现说明：
 * 1. 启动页没有导览栏（原型在 `.screen` 前留了 48px 空白占位），
 *    所以这里 `showNav={false}`。
 * 2. 原型的进度条停在 45%、文案是「正在展开冒险卷轴…」—— 那是一个**快照**。
 *    真机上进度条从 0 走到 100，文案按阶段切换。
 */

import { Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'

import MagicStage from '../../components/MagicStage'
import PhoneShell from '../../components/PhoneShell'
import { goTab } from '../../utils/navigation'
import { styleOf } from '../../utils/style'

import './index.scss'

/** 分阶段文案：让用户知道「还在动」，而不是卡住了 */
const STAGES = [
  { at: 0, text: '正在展开冒险卷轴…' },
  { at: 700, text: '正在唤醒知识精灵…' },
  { at: 1400, text: '正在布置副本入口…' }
]

/** 总时长；原型里法阵以 1.8s 为节奏匀速旋转，这里取 2.0s 走完整段过渡 */
const TOTAL_MS = 2000
const TICK_MS = 60

export default function SplashPage() {
  const [progress, setProgress] = useState(0)
  const [stageText, setStageText] = useState(STAGES[0].text)
  const navigated = useRef(false)

  useEffect(() => {
    const startedAt = Date.now()

    const timer = setInterval(() => {
      const elapsed = Date.now() - startedAt
      setProgress(Math.min(100, Math.round((elapsed / TOTAL_MS) * 100)))

      // 取当前已到达的最后一个阶段文案
      let text = STAGES[0].text
      for (const stage of STAGES) {
        if (elapsed >= stage.at) text = stage.text
      }
      setStageText(text)

      if (elapsed >= TOTAL_MS && !navigated.current) {
        navigated.current = true
        clearInterval(timer)
        // 大厅是标签页，必须走 switchTab；失败时由 goTab 兜底
        goTab('/pages/hall/index')
      }
    }, TICK_MS)

    return () => clearInterval(timer)
  }, [])

  return (
    <PhoneShell showNav={false} scroll={false} screenClassName='splash__screen'>
      <View className='spacer' />

      <MagicStage size={176} spriteSize={80} sprite='shishi' spriteMotion='floaty' />

      <View className='splash__title-wrap'>
        <Text className='splash__title'>知拾冒险社</Text>
        <Text className='sub splash__slogan'>拾万千知识，闯无尽关卡</Text>
      </View>

      <View className='bar blue splash__bar'>
        <View style={styleOf({ width: `${progress}%` })} />
      </View>

      <Text className='tiny'>{stageText}</Text>

      <View className='spacer' />
    </PhoneShell>
  )
}
