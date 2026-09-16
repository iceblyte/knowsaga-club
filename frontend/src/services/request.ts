/**
 * 请求层：`Taro.request` 的薄封装。
 *
 * 只做三件事，绝不多做：
 *
 * 1. **统一解包 `{code, message, data}`** —— 后端所有接口（含错误）都是这个形状，
 *    所以调用方只拿 `data`，不必每处都写 `if (res.code === 0)`。
 * 2. **把失败归一成 `ApiError`** —— 网络失败、HTTP 4xx/5xx、业务码非 0
 *    三种情况对调用方是同一种东西：一次「没能拿到数据」。但**保留 code**，
 *    因为调用方需要区分「任务过期（4004，要重新提交）」和「出题失败（5001，可原地重试）」。
 * 3. **不做重试、不做缓存、不做轮询** —— 这些是业务策略，属于调用方。
 *
 * ## 一个容易踩的点：Taro.request 对 4xx/5xx 不抛异常
 *
 * 只有网络层失败（连不上、超时）才 reject；HTTP 状态码是 500 也照样走 success 回调。
 * 因此**不能靠 try/catch 判断业务失败**，必须解析响应体里的 `code`。
 * 这也正好和后端的约定吻合：错误响应体的形状与成功时完全一致。
 */

import Taro from '@tarojs/taro'

import {
  API_BASE_URL,
  API_PREFIX,
  API_TIMEOUT_MS,
  CLIENT_ERROR_CODE,
  ERROR_FALLBACK_TEXT
} from '../constants/api'
import type { ApiEnvelope } from '../types/api'

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

export interface RequestOptions {
  /** 相对 `API_PREFIX` 的路径，如 `/quiz/generate` */
  path: string
  method?: HttpMethod
  data?: Record<string, unknown>
  timeoutMs?: number
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
export async function request<T>({
  path,
  method = 'GET',
  data,
  timeoutMs = API_TIMEOUT_MS
}: RequestOptions): Promise<T> {
  let res: Taro.request.SuccessCallbackResult<unknown>

  try {
    res = await Taro.request({
      url: `${API_BASE_URL}${API_PREFIX}${path}`,
      method,
      data,
      timeout: timeoutMs,
      header: { 'Content-Type': 'application/json' }
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
