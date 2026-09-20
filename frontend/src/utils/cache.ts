/**
 * 本地缓存：占用大小与清理（原型 07·5 的「清理缓存」一行）。
 *
 * ## 只统计与清理**自己写的**键
 *
 * 两端的存储是分开的（小程序 Storage / 浏览器 `localStorage`），但只有
 * 小程序那一侧是「本应用独占」的。H5 的 `localStorage` 是按**源**共享的，
 * 直接 `clear()` 会把同源下别的东西一起删掉。所以这里统一只认
 * `knowsaga.` 前缀 —— 规则一致，两个平台不需要分支。
 *
 * ## 为什么不用 `Taro.getStorageInfoSync().currentSize`
 *
 * 它在 H5 上返回 **`NaN`**（实测 `@tarojs/taro-h5` 的实现里写着
 * `currentSize: NaN`、`limitSize: NaN`）。把它直接显示出来就是
 * 「当前占用 NaN MB」，而这正是本项目反复踩到的**静默失效**类型：
 * 类型是 `number`，编译期一切正常。所以这里只取 `keys`，
 * 大小自己按字节算。
 *
 * ## 为什么不用 `Taro.clearStorageSync()`
 *
 * H5 上它是 `localStorage.clear()`，小程序上是清空整个 Storage ——
 * 两者都会把**登录态**（`knowsaga.session.token`）一起删掉。
 * 用户点一下「清理缓存」就被登出，是明显的越界。所以这里逐个删，
 * 并且显式跳过 `PROTECTED_KEYS`。
 */

import Taro from '@tarojs/taro'

/** 本项目所有本地键的前缀 */
const CACHE_PREFIX = 'knowsaga.'

/**
 * **不属于缓存**的键：登录态与设备标识。
 *
 * 清掉它们不会「省出空间」，只会让用户下次进页面时重新登录
 * （小程序里要重新走一次 `wx.login`，H5 上设备标识丢失还会**换一个新账号**）。
 */
const PROTECTED_KEYS = [
  'knowsaga.session.token',
  'knowsaga.session.user',
  'knowsaga.device.id'
]

/** UTF-8 字节数；不要用 `str.length` —— 一个汉字是 3 字节 */
function utf8Bytes(value: string): number {
  let bytes = 0
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code < 0x80) {
      bytes += 1
    } else if (code < 0x800) {
      bytes += 2
    } else if (code >= 0xd800 && code <= 0xdbff) {
      // 代理对：一个字符占 4 字节，跳过紧随的低位码元
      bytes += 4
      index += 1
    } else {
      bytes += 3
    }
  }
  return bytes
}

/** 列出可清理的键（有前缀、且不在保护名单里） */
export function listCacheKeys(): string[] {
  let keys: string[] = []
  try {
    // 两端都实现了 `keys`（H5 是 `Object.keys(localStorage)`）；
    // 拿不到时按「没有缓存」处理，不去猜。
    keys = Taro.getStorageInfoSync()?.keys ?? []
  } catch {
    return []
  }

  return keys.filter(
    (key) => key.startsWith(CACHE_PREFIX) && !PROTECTED_KEYS.includes(key)
  )
}

/** 缓存占用的字节数 */
export function cacheBytes(): number {
  let total = 0
  for (const key of listCacheKeys()) {
    try {
      // 存的都是字符串；真取到别的东西时按「空」算，不让整个统计崩掉
      const value = Taro.getStorageSync(key)
      if (typeof value === 'string') total += utf8Bytes(value)
    } catch {
      // 单个键读不出来就跳过它，其余照常统计
    }
  }
  return total
}

/**
 * 清空缓存，返回**实际删掉的键数**。
 *
 * 返回数量是为了让调用方说清做了什么：「已清理 3 项」比「清理完成」有用，
 * 而删了 0 项时说「清理完成」会让用户以为刚才那 0.4 KB 是真实占用之外的东西。
 */
export function clearCache(): number {
  const keys = listCacheKeys()
  let removed = 0
  for (const key of keys) {
    try {
      Taro.removeStorageSync(key)
      removed += 1
    } catch {
      // 删不掉的不计入，也不抛 —— 这是个「顺手清理」的动作
    }
  }
  return removed
}

/**
 * 人类可读的占用大小，沿用原型「12.6 MB」的写法（一位小数 + 单位）。
 *
 * 单位只在 KB / MB 之间切：这个应用的全部本地数据不可能到 GB，
 * 而「0.00 GB」比「512 KB」难读得多。
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 KB'
  const kb = bytes / 1024
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}
