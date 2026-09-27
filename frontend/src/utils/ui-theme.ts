/**
 * 界面主题的**本地镜像**与**窗口背景**。
 *
 * ## ⚠️ 本文件不 import store —— 这是有意的
 *
 * store 需要**同步**读一次镜像来定初值（规格要求冷启动第一帧就是对的主题，
 * 不能等 `/users/me/settings` 回来）。如果这里反过来 import store 去写状态，
 * 就形成 `store → utils/ui-theme → store` 的循环 import；而 store 是在模块
 * **顶层** `create(...)` 的，循环下模块求值顺序不受控，`readUiThemeMirror`
 * 有可能还在 TDZ 里 —— 表现是启动直接报错或主题静默回默认，两种都很难查。
 *
 * 所以职责这样切：
 *   · 本文件 —— 纯存储 / 纯平台调用，不碰 store；
 *   · `store/useAppStore.ts` 的 `setUiTheme` —— 唯一写入点，串起「改状态 + 写镜像 +
 *     改窗口背景」三件事（依赖方向只有 store → 本文件这一条）。
 */

import Taro from '@tarojs/taro'

import {
  DEFAULT_UI_THEME,
  normalizeUiTheme,
  uiThemeColorsOf,
  type UiThemeId
} from '../constants/ui-theme'

/**
 * 主题镜像的存储键。
 *
 * 与 `utils/cache.ts` 的 `PROTECTED_KEYS` 共用这一个常量 —— 主题是**用户偏好**，
 * 不是可丢弃的缓存：「清理缓存」把它删掉就等于「清一次缓存主题就回默认」，
 * 而规格明确要求清理缓存**不得**重置主题。两处各写一遍字符串迟早会漂。
 */
export const UI_THEME_STORAGE_KEY = 'knowsaga.uiTheme'

/**
 * 读本地镜像。
 *
 * `Taro.getStorageSync` 是**同步**的，这正是它被选来做镜像的原因（初值同步可得）。
 * 读不到 / 读到不认识的值一律回默认主题，并把异常吞掉 —— 主题读不出来不该
 * 让启动失败，最坏也只是先按默认主题渲染，随后服务端对账会纠正它。
 */
export function readUiThemeMirror(): UiThemeId {
  try {
    return normalizeUiTheme(Taro.getStorageSync(UI_THEME_STORAGE_KEY))
  } catch {
    return DEFAULT_UI_THEME
  }
}

/**
 * 写本地镜像。
 *
 * 写失败**静默**：本次会话的界面已经是新主题了（状态与类名都改过了），
 * 只是下次冷启动会退回默认、再由服务端对账纠回来。为一次镜像写失败弹提示
 * 反而会让用户以为「换主题失败了」。
 */
export function writeUiThemeMirror(id: UiThemeId): void {
  try {
    Taro.setStorageSync(UI_THEME_STORAGE_KEY, id)
  } catch {
    // 见上：镜像只是「首帧不闪」的加速器，不是权威值
  }
}

/**
 * 把 app 级窗口背景改成当前主题的板色。
 *
 * 为什么需要它：`app.config.ts` 的 `window.backgroundColor` 是**编译期常量**，
 * 而它管的是 `.page` 之外的那一圈（下拉回弹、安全区、超出视口的区域）。
 * 不改的话，切到暗色主题后**下拉会露出一块浅米色** —— 属于「暗色主题漏白」
 * 这一类问题（design.md D9 登记的风险）。
 *
 * 它的签名在两端不一致（小程序是原生 API，H5 侧没有这个概念），所以：
 * 同步抛错吞掉，返回 Promise 也吞掉。**换肤的主流程不依赖它是否成功。**
 */
export function applyWindowBackground(id: UiThemeId): void {
  try {
    void Promise.resolve(
      Taro.setBackgroundColor({ backgroundColor: uiThemeColorsOf(id).board })
    ).catch(() => undefined)
  } catch {
    // H5 / 老版本基础库没有这个能力：忽略。页内的 `.page` 自己画了板色背景。
  }
}
