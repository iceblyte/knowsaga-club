/**
 * 请求层：`Taro.request` 的薄封装。
 *
 * 只做四件事，绝不多做：
 *
 * 1. **带上登录态** —— 需要鉴权的接口自动注入 `Authorization: Bearer <token>`，
 *    并在没有登录态时先静默登录（`ensureSession`）。
 * 2. **统一解包 `{code, message, data}`** —— 后端所有接口（含错误）都是这个形状，
 *    所以调用方只拿 `data`，不必每处都写 `if (res.code === 0)`。
 * 3. **把失败归一成 `ApiError`** —— 网络失败、HTTP 4xx/5xx、业务码非 0
 *    三种情况对调用方是同一种东西：一次「没能拿到数据」。但**保留 code**，
 *    因为调用方需要区分「任务过期（4004，要重新提交）」和「出题失败（5001，可原地重试）」。
 * 4. **4010 时静默重建登录态并重试一次** —— 见下。
 *    重试、刷新之外的事（缓存、轮询、防抖）一律不做，那些是业务策略。
 *
 * ## 一个容易踩的点：Taro.request 对 4xx/5xx 不抛异常
 *
 * 只有网络层失败（连不上、超时）才 reject；HTTP 状态码是 500 也照样走 success 回调。
 * 因此**不能靠 try/catch 判断业务失败**，必须解析响应体里的 `code`。
 * 这也正好和后端的约定吻合：错误响应体的形状与成功时完全一致。
 *
 * ## 4010 的处理为什么是「重建一次」而不是「直接报错」
 *
 * 登录态有效期 7 天，过期是**必然会发生的正常事件**；用户点了登出、
 * 或者服务端换了密钥，也会让令牌立刻失效。这几种情况下让用户看到
 * 「登录已过期，请重新进入」都是多余的 —— 小程序有静默登录能力，
 * 重建一次就完事了，用户全程无感（方案 §4.4）。
 *
 * 重试**只做一次**：如果拿着新令牌立刻又是 4010，说明问题不在令牌
 * （比如调试通道被关掉了、AppID 配错了），再重试只会把失败拖长。
 */

import Taro from '@tarojs/taro'

import {
  API_BASE_URL,
  API_PREFIX,
  API_TIMEOUT_MS,
  CLIENT_ERROR_CODE,
  ERROR_CODE,
  ERROR_FALLBACK_TEXT
} from '../constants/api'
import type { ApiEnvelope } from '../types/api'
import { ensureSession } from './auth'
import { getToken } from './session'

/** 请求失败。`code` 为后端业务码，或 `CLIENT_ERROR_CODE` 里的客户端伪码。 */
export class ApiError extends Error {
  /** 业务错误码（0 表示成功，不会出现在 ApiError 里） */
  readonly code: number
  /** HTTP 状态码；网络失败时为 0 */
  readonly httpStatus: number

  constructor(code: number, message: string, httpStatus = 0) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.httpStatus = httpStatus
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

/**
 * `Taro.request` 的原始返回。
 *
 * 不直接写 `SuccessCallbackResult<unknown>`：那个泛型被约束为
 * `string | ArrayBuffer | IAnyObject`，`unknown` 不满足，会报 TS2344。
 * 这里用「函数返回类型」反推，既绕开约束，又保证跟 Taro 自身的定义同步。
 */
type RawRequestResult = Awaited<ReturnType<typeof Taro.request>>

export interface RequestOptions {
  /** 相对 `API_PREFIX` 的路径，如 `/quiz/generate` */
  path: string
  method?: HttpMethod
  data?: Record<string, unknown>
  timeoutMs?: number
  /**
   * 是否需要登录态，默认 `true`。
   *
   * 只有登录接口与健康探测需要显式传 `false`：前者一旦要求登录态就会
   * 递归等自己，后者是「后端还没起来也要能探测」的公共端点。
   */
  auth?: boolean
}

function isEnvelope(value: unknown): value is ApiEnvelope<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { code?: unknown }).code === 'number'
  )
}

/**
 * 发起一次请求并返回解包后的 `data`。
 *
 * @throws {ApiError} 网络失败（code = -1）、响应结构异常（code = -2）、业务失败（code ≥ 4000）
 */
export async function request<T>(options: RequestOptions): Promise<T> {
  return send<T>(options, true)
}

async function send<T>(options: RequestOptions, allowRelogin: boolean): Promise<T> {
  const { path, method = 'GET', data, timeoutMs = API_TIMEOUT_MS, auth = true } = options

  const header: Record<string, string> = { 'Content-Type': 'application/json' }

  /**
   * 本次实际使用的令牌。留着它是为了判 4010 时区分两种情况：
   * 令牌真的失效了（要重建），还是已经被别的并发请求换掉了（直接重试）。
   */
  let usedToken: string | null = null

  if (auth) {
    // 没有登录态时先把登录做完再发 —— 顺序反了就会稳定拿到 4010，
    // 然后再靠重建重试补救，白白多一个来回
    await ensureSession()
    usedToken = getToken()
    if (usedToken) header.Authorization = `Bearer ${usedToken}`
  }

  let res: RawRequestResult

  try {
    res = await Taro.request({
      url: `${API_BASE_URL}${API_PREFIX}${path}`,
      method,
      data,
      timeout: timeoutMs,
      header
    })
  } catch {
    // 这里**不要**把原始错误往上抛：小程序里它可能是个不带 message 的普通对象，
    // 上层拿它拼提示会拼出 `[object Object]`。
    throw new ApiError(
      CLIENT_ERROR_CODE.NETWORK,
      ERROR_FALLBACK_TEXT[CLIENT_ERROR_CODE.NETWORK]
    )
  }

  const body = res.data

  if (!isEnvelope(body)) {
    throw new ApiError(
      CLIENT_ERROR_CODE.BAD_RESPONSE,
      ERROR_FALLBACK_TEXT[CLIENT_ERROR_CODE.BAD_RESPONSE],
      res.statusCode
    )
  }

  if (body.code === ERROR_CODE.UNAUTHORIZED && auth && allowRelogin) {
    // 令牌仍是当初那一个 → 它确实失效了，清掉重建。
    // 已经不同 → 有别的请求替我们重建过了，直接拿新的重试，
    // 不能再去 clearSession()，否则会把刚拿到的好令牌擦掉（并发下的真实现象）。
    if (getToken() === usedToken) {
      await ensureSession({ force: true })
    }
    return send<T>(options, false)
  }

  if (body.code !== 0) {
    throw new ApiError(body.code, body.message || '请求失败', res.statusCode)
  }

  return body.data as T
}

/**
 * 把任意异常转成可直接展示的中文文案。
 *
 * 优先用 `ERROR_FALLBACK_TEXT` 里更具体的说法（它带了「下一步该做什么」），
 * 没有登记的码回退到后端给的 `message` —— 这样后端新增错误码时前端不必同步改。
 */
export function toDisplayMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return ERROR_FALLBACK_TEXT[error.code] || error.message || '出了点意外，请稍后重试'
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return '出了点意外，请稍后重试'
}
