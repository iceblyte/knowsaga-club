/**
 * 数字递增动画。
 *
 * 用途单一：通关结算页的 `+180 XP` 与 `+32 金币` 要「滚」上去。
 * 原型批注明确要求这一点（0.8s 递增），它承担的是奖励释放的情绪，
 * 不是装饰 —— 直接甩出一个终值，那一瞬间的爽感会少很多。
 *
 * ## 为什么不用 requestAnimationFrame
 *
 * `requestAnimationFrame` 在小程序里**不是全局函数**（只有 Canvas 节点上才有）。
 * 直接在页面里调它会报 undefined。这里退回到 `setTimeout` 以 16ms 为步长，
 * 视觉上等价，而且不依赖任何平台特有 API。
 *
 * 缓动用 easeOutCubic：结尾变慢，读起来像「停下来了」而不是「被掐断」。
 */

import { useEffect, useState } from 'react'

const FRAME_MS = 16

export interface CountUpOptions {
  /** 动画时长（ms） */
  duration?: number
  /** 延迟开始（ms）。结算页用它错开 XP 与金币的动画 */
  delay?: number
}

export function useCountUp(target: number, { duration = 800, delay = 0 }: CountUpOptions = {}): number {
  const [value, setValue] = useState(0)

  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout> | null = null
    let startedAt = 0

    const tick = () => {
      if (disposed) return
      const elapsed = Date.now() - startedAt
      const progress = duration <= 0 ? 1 : Math.min(1, elapsed / duration)
      const eased = 1 - Math.pow(1 - progress, 3)

      setValue(Math.round(target * eased))

      if (progress < 1) {
        timer = setTimeout(tick, FRAME_MS)
      }
    }

    timer = setTimeout(() => {
      startedAt = Date.now()
      tick()
    }, delay)

    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
    }
  }, [target, duration, delay])

  return value
}

export default useCountUp
