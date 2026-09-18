/**
 * 接口层常量。
 *
 * ## 关于 `process.env.TARO_APP_API_BASE_URL` 的写法（务必别改）
 *
 * Taro 把 env 文件里的 `TARO_APP_*` 变量交给 webpack 的 `DefinePlugin`，
 * 而 DefinePlugin 做的是**文本替换**：它只替换源码里**字面出现**的成员表达式。
 * 所以下面这行必须一字不改地写成 `process.env.TARO_APP_API_BASE_URL`；
 * 一旦改写成 `const env = process.env; env.TARO_APP_...`，
 * 替换就不会发生，小程序运行时会因为 `process` 不存在而直接崩。
 *
 * 另一条同样重要的约束：**变量必须真的在 `.env.<mode>` 里定义过**。
 * DefinePlugin 只为「出现过的键」生成定义，没定义过的键不会被替换。
 * 因此 `.env.development` / `.env.production` / `.env.test` 里都写了这一项。
 */

/** 后端地址。本地开发默认打到 uvicorn 的 8000 端口。 */
const RAW_BASE_URL = process.env.TARO_APP_API_BASE_URL

/** 规范化：去掉末尾斜杠，避免拼出 `//api/v1` */
export const API_BASE_URL = (RAW_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

/** 接口前缀（后端 `app/api/v1/router.py`） */
export const API_PREFIX = '/api/v1'

/** 常规请求超时。出题不走这条路径（它是异步任务），所以 15s 足够宽裕。 */
export const API_TIMEOUT_MS = 15000

/** 健康检查超时：探测而已，不该让用户等太久 */
export const HEALTH_TIMEOUT_MS = 5000

/**
 * 登录请求超时。
 *
 * 比常规请求短：登录是**在别的请求之前**发生的（请求层要等它拿到令牌），
 * 挂太久会让用户看到的第一个页面一直空着。微信的 code2Session 正常在
 * 几百毫秒内返回，8s 已经是非常宽松的上限。
 */
export const LOGIN_TIMEOUT_MS = 8000

/** 兜底轮询间隔。正常情况下用后端返回的 `poll_interval_ms`。 */
export const FALLBACK_POLL_INTERVAL_MS = 1200

/**
 * 轮询总时长上限。
 *
 * 后端本身有 `QUIZ_GENERATION_BUDGET_SECONDS`（默认 50s）兜底，
 * 这里的上限是**前端自己的保险丝**：后端因为某种原因没能把任务推到终态时，
 * 前端必须自己停下来并给出可重试的失败态，而不是无限转圈。
 * 取 100s，比后端预算宽一倍，正常路径永远不会碰到它。
 */
export const POLL_DEADLINE_MS = 100000

/** 「取消」入口出现的时机（原型：超过 8s 才显示） */
export const CANCEL_APPEAR_MS = 8000

/** 单次出题的题量。原型三处屏都是 5 题。 */
export const QUIZ_QUESTION_COUNT = 5

/** 出题难度偏好。`mixed` 让模型自己分配，与后端 default 一致。 */
export const QUIZ_DIFFICULTY = 'mixed' as const

/** 客户端侧的伪错误码。真实业务错误码一律 ≥ 4000（后端定义）。 */
export const CLIENT_ERROR_CODE = {
  /** 网络不可达 / 请求超时 */
  NETWORK: -1,
  /** 响应体不是 `{code, message, data}` 结构 */
  BAD_RESPONSE: -2,
  /** 轮询超时，任务未在 `POLL_DEADLINE_MS` 内进入终态 */
  POLL_TIMEOUT: -3
} as const

/** 后端业务错误码，仅列出前端需要分支处理的（完整表见 backend/app/core/exceptions.py） */
export const ERROR_CODE = {
  OK: 0,
  INVALID_PARAM: 4000,
  INVALID_INPUT: 4001,
  UPLOAD_INVALID: 4002,
  TASK_NOT_FOUND: 4004,
  /** 「资源不存在**或**无权访问」。越权与不存在共用此码，前端不要试图区分 */
  RESOURCE_NOT_FOUND: 4005,
  TASK_NOT_CANCELLABLE: 4090,
  /** 登录态缺失 / 无效 / 过期 / 已被登出。请求层据此静默重建一次 */
  UNAUTHORIZED: 4010,
  WECHAT_CODE_INVALID: 4011,
  ACCOUNT_BLOCKED: 4030,
  RATE_LIMITED: 4290,
  INTERNAL_ERROR: 5000,
  AI_GENERATION_FAILED: 5001,
  AI_TIMEOUT: 5030,
  AI_QUOTA_EXCEEDED: 5031,
  WECHAT_UPSTREAM_ERROR: 5032
} as const

/**
 * 出题失败时给用户看的替代文案。
 *
 * 为什么不直接用后端的 `error.message`：
 * 后端返回的已经是中文可展示文案（如「出题失败，请重试」），
 * 但少数场景下需要补上下一步动作（例如任务过期要提示重新提交，
 * 因为任务已经不在内存里了，原地重试同一个 task_id 只会再拿到 4004）。
 * 未列出的码一律回退到后端的原文，这样后端新增错误码时前端不必同步改。
 */
export const ERROR_FALLBACK_TEXT: Record<number, string> = {
  [CLIENT_ERROR_CODE.NETWORK]: '连不上服务器，请确认后端已启动，然后重试',
  [CLIENT_ERROR_CODE.BAD_RESPONSE]: '服务返回了无法识别的内容，请稍后重试',
  [CLIENT_ERROR_CODE.POLL_TIMEOUT]: '等待太久了，请重新生成一次',
  [ERROR_CODE.TASK_NOT_FOUND]: '这次召唤已经过期，请重新生成',
  [ERROR_CODE.AI_QUOTA_EXCEEDED]: '当前使用的人有点多，请稍后再试',
  // 登录态重建之后仍然 4010 → 说明不是「过期」而是「登录本身没成功」。
  // 这时候说「登录状态已过期」会误导用户（他可能压根没登录过）。
  [ERROR_CODE.UNAUTHORIZED]: '登录状态已失效，请重新进入小程序',
  [ERROR_CODE.WECHAT_UPSTREAM_ERROR]: '登录服务暂时不可用，请稍后再试',
  [ERROR_CODE.INTERNAL_ERROR]: '服务开小差了，请稍后重试'
}
