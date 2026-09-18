/**
 * 登录态的获取与重建。
 *
 * ## 两条通道，按平台选首选
 *
 * | 平台 | 首选 | 备用 |
 * |---|---|---|
 * | 微信小程序 | `wx.login()` → `POST /auth/wechat` | `POST /auth/dev` |
 * | H5 / 浏览器 | `POST /auth/dev` | `POST /auth/wechat`（浏览器里拿不到 code，基本必失败） |
 *
 * 为什么要「互备一次」：正式 AppID 与密钥没配好时，小程序里除登录外的
 * **全部链路**都无法验证（方案 §12 风险表第 1 行）。后端为此提供了调试通道，
 * 而它只在 `APP_ENV=dev` 且 `DEV_LOGIN_ENABLED=true` 时被挂载 ——
 * **生产环境该路径根本不存在（404）**，所以这条备用通道自动失效，
 * 不可能成为生产环境的免密入口。
 *
 * ## 两条都失败时报**首选**通道的原因
 *
 * 备用的调试通道在它不可用时的表现是 404（响应体甚至不是我们的信封结构），
 * 报出来是「服务返回了无法识别的内容」。把这种噪音盖在真正的原因
 * （「微信凭证无效」/「登录服务暂时不可用」）上面，会让排查方向完全跑偏。
 *
 * ## 与 `services/request.ts` 的循环依赖
 *
 * `request` 要在 4010 时重建登录态，所以 import 了本模块的 `ensureSession`；
 * 本模块要用 `request` 发请求，所以 import 了它。这个环是**有意为之**：
 * 两处调用都发生在函数体内（请求时才执行），此时两个模块都已初始化完毕，
 * 不存在「拿到 undefined」的窗口。想「修掉」这个环，只会把逻辑搬到更难找的地方。
 */

import Taro from '@tarojs/taro'

import { ERROR_CODE, LOGIN_TIMEOUT_MS } from '../constants/api'
import type { LoginResponse } from '../types/api'
import { isH5 } from '../utils/platform'
import { ApiError, request } from './request'
import { clearSession, deviceId, hasSession, restoreSession, saveSession } from './session'

/** 微信静默登录：拿一次性 `code` 换登录态。 */
async function loginWithWechat(): Promise<LoginResponse> {
  let code = ''
  try {
    const result = await Taro.login()
    code = (result as { code?: string } | undefined)?.code ?? ''
  } catch {
    // `wx.login` 自身失败（基础库异常等）——后面统一按「凭证无效」处理
    code = ''
  }
  if (!code) {
    throw new ApiError(ERROR_CODE.WECHAT_CODE_INVALID, '未能获取微信登录凭证')
  }

  return request<LoginResponse>({
    path: '/auth/wechat',
    method: 'POST',
    data: { code },
    // 登录接口本身不能等登录态，否则就是递归等自己
    auth: false,
    timeoutMs: LOGIN_TIMEOUT_MS
  })
}

/** 调试通道：由设备标识派生一个稳定身份。仅开发环境存在。 */
function loginWithDevice(): Promise<LoginResponse> {
  return request<LoginResponse>({
    path: '/auth/dev',
    method: 'POST',
    data: { device_id: deviceId() },
    auth: false,
    timeoutMs: LOGIN_TIMEOUT_MS
  })
}

/** 走首选通道登录，失败后换另一条再试一次；两条都失败则抛首选通道的错误。 */
export async function login(): Promise<LoginResponse> {
  const [primary, fallback] = isH5()
    ? [loginWithDevice, loginWithWechat]
    : [loginWithWechat, loginWithDevice]

  try {
    const result = await primary()
    saveSession(result)
    return result
  } catch (primaryError) {
    try {
      const result = await fallback()
      saveSession(result)
      return result
    } catch {
      throw primaryError
    }
  }
}

/**
 * 并发登录去重。
 *
 * 首屏可能同时发出好几个需要登录态的请求（健康探测、个人中心、结算提交），
 * 没有这道闸门就会并发打 N 次登录 —— 微信的 `code2Session` 有分钟级配额，
 * 而且每次都会新建/查一次用户，纯属浪费。
 */
let pendingLogin: Promise<LoginResponse> | null = null

export interface EnsureSessionOptions {
  /**
   * 强制重建：清掉现有令牌再登录。
   *
   * 只在**确认当前令牌已失效**时使用（收到 4010 且令牌没被别的请求换掉）。
   * 否则会把一个刚拿到的好令牌白白丢掉。
   */
  force?: boolean
}

/**
 * 确保拿到可用登录态。已有令牌时直接返回（**不校验**，见 `services/session`）。
 *
 * @throws {ApiError} 两条通道都失败时，抛首选通道的原因
 */
export async function ensureSession(options: EnsureSessionOptions = {}): Promise<void> {
  // 兜底恢复：不依赖启动钩子的执行时机，谁先要登录态谁保证已就绪
  restoreSession()

  const { force = false } = options
  if (!force && hasSession()) return

  if (!pendingLogin) {
    if (force) clearSession()
    pendingLogin = login().finally(() => {
      pendingLogin = null
    })
  }
  await pendingLogin
}

/**
 * 登出：让服务端把该用户**全部已签发的登录态**立即失效（递增 `token_version`）。
 *
 * 本地清理放在 `finally`：即使网络失败也必须清掉，否则用户点了登出、
 * 界面回到了未登录态，可令牌还留在本地 —— 下次进来又是「已登录」。
 */
export async function logout(): Promise<void> {
  try {
    await request({ path: '/auth/logout', method: 'POST' })
  } finally {
    clearSession()
  }
}
