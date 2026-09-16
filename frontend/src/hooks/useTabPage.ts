/**
 * 标签页专用 hook：在页面每次显示时，把当前 tab 序号写入全局 store。
 *
 * 自定义 tabBar 的组件实例由小程序运行时管理，跨平台行为不一致，
 * 因此选中态不放在组件里，而是由页面主动上报（见 useTabStore 的说明）。
 *
 * **非标签页请不要调用它**，或者传 `undefined`。早期版本无条件写入，
 * 于是任何拿到 `undefined` 的页面都会把高亮误设到第 0 个 tab（社团大厅）——
 * 这类「看起来只是高亮位置错了」的问题很难被当成 bug 报上来。
 */

import { useDidShow } from '@tarojs/taro'

import { useTabStore, type TabKey } from '../store/useTabStore'

export function useTabPage(key: TabKey | undefined | null): void {
  useDidShow(() => {
    if (!key) return
    useTabStore.getState().setCurrentByKey(key)
  })
}

export default useTabPage
