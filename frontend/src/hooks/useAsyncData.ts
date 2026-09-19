/**
 * 只读数据的加载状态机。档案四页（看板 / 知识树 / 错题本 / 勋章墙）共用。
 *
 * ## 为什么不让每页自己写 `useState` + `useEffect`
 *
 * 四个页面都会遇到同样三件事，而每一件都容易写错：
 *
 * 1. **竞态**：用户在「近 7 天 / 近 30 天」之间快速点两下，第一个请求
 *    可能后回来，把新数据覆盖成旧的。这里用自增序号只认最后一次请求。
 * 2. **卸载后写 state**：页面已经退出、请求才回来。
 * 3. **重试**：失败后要能原地再来一次，而不是让用户退出去重进。
 *
 * ## `key` 而不是依赖数组
 *
 * 调用方传一个 `key`（如当前区间 `'7d'`），它变了就重新加载。
 * 不暴露依赖数组是因为**加载函数每次渲染都是新的引用**（内联箭头函数），
 * 把它放进依赖数组会每渲染一次就请求一次；而要求调用方 `useCallback`
 * 包一层，是让每个使用点都去记一件与业务无关的事。
 * 内部用 ref 拿最新的函数，所以不会有闭包过期的问题。
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type AsyncStatus = 'loading' | 'ready' | 'error'

export interface AsyncData<T> {
  status: AsyncStatus
  /** 只在 `ready` 时有值；重新加载期间**保留上一次的数据**，避免页面闪空 */
  data: T | null
  error: unknown
  /** 重新加载（失败重试、下拉刷新都用它） */
  reload: () => void
}

export function useAsyncData<T>(load: () => Promise<T>, key?: string | number): AsyncData<T> {
  const [status, setStatus] = useState<AsyncStatus>('loading')
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)

  /** 最新一次传进来的加载函数（每渲染都同步，避免闭包读到旧的 `key`） */
  const loadRef = useRef(load)
  loadRef.current = load

  /** 请求序号：只有序号等于当前值的响应才允许写入 state */
  const seqRef = useRef(0)
  /** 组件是否还挂在页面上 */
  const aliveRef = useRef(true)

  const run = useCallback(() => {
    const seq = (seqRef.current += 1)
    setStatus('loading')
    setError(null)

    loadRef.current().then(
      (result) => {
        if (!aliveRef.current || seq !== seqRef.current) return
        setData(result)
        setStatus('ready')
      },
      (reason: unknown) => {
        if (!aliveRef.current || seq !== seqRef.current) return
        setError(reason)
        setStatus('error')
      }
    )
  }, [])

  useEffect(() => {
    aliveRef.current = true
    run()
    return () => {
      aliveRef.current = false
    }
    // `run` 是稳定的（useCallback 空依赖），真正决定要不要重载的是 `key`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return { status, data, error, reload: run }
}

export default useAsyncData
