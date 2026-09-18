/**
 * 登录态的**本地存放**：令牌、用户快照、设备标识。
 *
 * ## 为什么单独一个模块，而不是塞进 `services/auth.ts`
 *
 * `request.ts` 需要读令牌，`auth.ts` 需要写令牌。如果两者互相 import，
 * 就出现一个「谁先初始化」的问题。这个文件是**叶子模块** ——
 * 它只依赖 Taro 和类型，不依赖任何业务模块，所以谁都可以安全地引用它。
 *
 * ## 为什么不放在 zustand store 里
 *
 * store 是「渲染要用的状态」。令牌只被请求层读取，界面从不直接渲染它；
 * 放进 store 会让每个用到别的字段的组件都跟着 store 一起初始化。
 * 界面需要的那部分（user）在 store 里也有一份镜像，由调用方在写入时同步。
 *
 * ## 持久化策略
 *
 * 令牌写进小程序 Storage：重进小程序时先复用旧令牌，**不主动校验**。
 * 过期或被登出（`token_version` 变了）时服务端会返回 4010，
 * 请求层据此静默重建登录态 —— 这正是方案里「失效后客户端静默重建、
 * 用户无感」那条（见 `.env.example` 的 `JWT_EXPIRE_HOURS` 注释）。
 * 启动时多发一次校验请求换不来任何用户可见的收益，纯属浪费。
 */

import Taro from '@tarojs/taro'

import type { UserPublic } from '../types/api'
import { uuidV4 } from '../utils/id'

const TOKEN_KEY = 'knowsaga.session.token'
const USER_KEY = 'knowsaga.session.user'
const DEVICE_KEY = 'knowsaga.device.id'

/** 内存镜像：请求热路径上每次读 Storage 是同步 IO，没必要 */
let token: string | null = null
let user: UserPublic | null = null
let restored = false

/** Storage 在少数环境（如被裁剪的 webview）会直接抛异常，读写一律兜住 */
function readStorage(key: string): string {
  try {
    const value = Taro.getStorageSync(key)
    return typeof value === 'string' ? value : ''
  } catch {
    return ''
  }
}

function writeStorage(key: string, value: string): void {
  try {
    Taro.setStorageSync(key, value)
  } catch {
    // 写不进去不影响本次会话（内存里有），只是下次进来要重新登录。
    // 不值得为此打断用户正在做的事。
  }
}

function dropStorage(key: string): void {
  try {
    Taro.removeStorageSync(key)
  } catch {
    // 同上
  }
}

/** 当前令牌；无登录态时为 `null`。 */
export function getToken(): string | null {
  return token
}

/** 当前用户快照；未登录或尚未拿到时为 `null`。 */
export function getUser(): UserPublic | null {
  return user
}

/** 是否已有可用（未必未过期）的登录态。 */
export function hasSession(): boolean {
  return Boolean(token)
}

/**
 * 从 Storage 恢复登录态。**幂等**，只真正执行一次。
 *
 * 调用点有两个：应用启动时（尽量早），以及 `ensureSession` 内的兜底 ——
 * 后者保证「不管谁先发起请求，登录态都已经就绪」，不依赖启动钩子的执行时机。
 */
export function restoreSession(): void {
  if (restored) return
  restored = true

  const storedToken = readStorage(TOKEN_KEY)
  if (!storedToken) return

  token = storedToken
  const rawUser = readStorage(USER_KEY)
  if (rawUser) {
    try {
      user = JSON.parse(rawUser) as UserPublic
    } catch {
      // 结构变了或者写坏了：丢掉用户快照但**保留令牌** ——
      // 令牌能让「谁是我」在下次 `GET /users/me` 或结算响应里重新拿回来。
      user = null
      dropStorage(USER_KEY)
    }
  }
}

/** 登录成功后写入令牌与用户快照。 */
export function saveSession(next: { token: string; user: UserPublic }): void {
  token = next.token
  user = next.user
  restored = true
  writeStorage(TOKEN_KEY, next.token)
  writeStorage(USER_KEY, JSON.stringify(next.user))
}

/** 只更新用户快照（结算响应里带了最新的 XP / 等级 / 连续天数）。 */
export function updateUser(next: UserPublic): void {
  user = next
  writeStorage(USER_KEY, JSON.stringify(next))
}

/** 清空登录态。用于登出，以及收到 4010 后重建之前的那一次清理。 */
export function clearSession(): void {
  token = null
  user = null
  restored = true
  dropStorage(TOKEN_KEY)
  dropStorage(USER_KEY)
}

/**
 * 设备标识，首次使用时生成并落盘。
 *
 * 只被调试登录通道（`POST /auth/dev`）使用：没有正式 AppID 时靠它派生一个
 * 稳定身份。**必须落盘**，否则每次冷启动都会建档出一个新用户，
 * 本机联调时会看到「我的经验值每次进来都归零」。
 *
 * 服务端限制 1–128 字符，UUID 的 36 字符在范围内。
 */
export function deviceId(): string {
  const existing = readStorage(DEVICE_KEY)
  if (existing) return existing
  const created = `dev-${uuidV4()}`
  writeStorage(DEVICE_KEY, created)
  return created
}
