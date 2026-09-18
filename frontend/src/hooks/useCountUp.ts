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

import { useEffect, useRef, useState } from 'react'

const FRAME_MS = 16

export interface CountUpOptions {
  /** 动画时长（ms） */
  duration?: number
  /** 延迟开始（ms）。结算页用它错开 XP 与金币的动画，**只在首次生效** */
  delay?: number
}

/**
 * 从 0 滚到 `target`；`target` 中途变化时**从当前显示值接着滚**。
 *
 * ## 为什么「从当前值接着滚」是必需的，而不是锦上添花
 *
 * 结算页先按本地计算渲染出数字（保证即时），随后服务端结算结果到达，
 * 数字以服务端为准。两者按共享用例（`shared/scoring-cases.json`）应当完全一致，
 * 但**万一不一致就必须改成服务端的值** —— 那时如果动画从头再来一遍，
 * 用户看到的是「+200 滚到一半突然从 0 重滚」，会读成「出错了」。
 *
 * 目标值没变时直接返回、不重启动画，这也让「服务端与本地一致」的常态
 * 真正实现**零视觉变化**（而不是「重滚但终点一样」）。
 */
export function useCountUp(target: number, { duration = 800, delay = 0 }: CountUpOptions = {}): number {
  const [value, setValue] = useState(0)

  /** 当前显示值。用 ref 保存是为了不把它放进 effect 依赖里造成自我循环 */
  const shownRef = useRef(0)
  /** `delay` 只服务于首次入场，后续纠偏不该再等 */
  const enteredRef = useRef(false)

  useEffect(() => {
    const from = shownRef.current
    // 目标没变 → 什么都不做。这条是「零视觉变化」的实现方式。
    if (from === target) return

    let disposed = false
    let timer: ReturnType<typeof setTimeout> | null = null
    let startedAt = 0

    const wait = enteredRef.current ? 0 : delay
    enteredRef.current = true

    const tick = () => {
      if (disposed) return
      const elapsed = Date.now() - startedAt
      const progress = duration <= 0 ? 1 : Math.min(1, elapsed / duration)
      const eased = 1 - Math.pow(1 - progress, 3)

      const next = Math.round(from + (target - from) * eased)
      shownRef.current = next
      setValue(next)

      if (progress < 1) {
        timer = setTimeout(tick, FRAME_MS)
      }
    }

    timer = setTimeout(() => {
      startedAt = Date.now()
      tick()
    }, wait)

    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
    }
  }, [target, duration, delay])

  return value
}

export default useCountUp
