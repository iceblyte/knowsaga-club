/**
 * 隐私协议授权状态（方案 §7.4）。
 *
 * ## 为什么必须有这一层
 *
 * 微信从 2022 年起把「头像昵称填写能力」与《小程序用户隐私保护指引》绑定：
 * **只有在小程序后台声明过的信息才能调用对应组件**。未声明或用户未同意时，
 * `<input type="nickname">` **不会报错**，而是**降级成普通文本输入框**
 * —— 界面上看不出任何区别，用户以为自己在填微信昵称，实际上微信侧的
 * 校验已经不在了。这正是本项目最需要防的「静默失效」。
 *
 * ## 所以进来先问一句「用户同意了吗」
 *
 * `getPrivacySetting` 是**查询**接口（微信 2.32.3 起），不弹任何东西。
 * `needAuthorization` 为 `true` 时，页面必须先让用户同意，再渲染
 * 头像 / 昵称的编辑控件。
 *
 * ## 能力缺失不拦截
 *
 * 三种情况都返回 `supported: false`：
 *
 * 1. **H5** —— 浏览器里没有「小程序隐私协议」这个概念。实测
 *    `@tarojs/taro-h5` 把它实现成 `temporarilyNotSupport('getPrivacySetting')`，
 *    调了只会打一条 console 错误。
 * 2. **基础库 < 2.32.3** —— 接口不存在。方案明确要求「低于该版本不拦截，
 *    代码对能力缺失做兜底而不是直接报错」。
 * 3. **后台还没声明隐私收集类型**（当前的实际情况）—— 微信返回
 *    `needAuthorization: false`，等价于「无需拦截」。
 *
 * 三者都不该把用户挡在页面外面：他们只是改不了自定义头像，
 * 而不是不能用这个页面。
 */

import Taro from '@tarojs/taro'

import { isH5 } from './platform'

/**
 * 查询回调的兜底等待。
 *
 * 接口存在但回调没来时（基础库内部的极端情况），不能让页面一直转圈。
 * 超时按「查不到具体状态」处理 —— 与「能力缺失」同一条出口。
 */
const QUERY_TIMEOUT_MS = 1500

export interface PrivacyState {
  /** 该端是否存在「隐私协议」这件事。`false` 时 `need` 恒为 `false` */
  supported: boolean
  /** 是否需要用户先同意才能使用头像 / 昵称能力 */
  need: boolean
  /** 隐私授权协议的名称（形如「用户隐私保护指引」）；取不到时为空串 */
  contractName: string
}

/** 能力缺失时的统一出口（见文件头三种情况） */
const UNSUPPORTED: PrivacyState = { supported: false, need: false, contractName: '' }

/**
 * 查询隐私授权状态。
 *
 * **不抛异常**：调用方只需要「要不要先弹同意」，拿不到答案时按不需要处理。
 */
export function queryPrivacyAuthorization(): Promise<PrivacyState> {
  if (isH5()) return Promise.resolve(UNSUPPORTED)

  // 旧基础库里这个成员可能整个不存在（不是函数则是 undefined）
  const query = Taro.getPrivacySetting
  if (typeof query !== 'function') return Promise.resolve(UNSUPPORTED)

  return new Promise<PrivacyState>((resolve) => {
    let settled = false
    const finish = (state: PrivacyState): void => {
      if (settled) return
      settled = true
      resolve(state)
    }

    try {
      query({
        success: (result) =>
          finish({
            supported: true,
            need: Boolean(result?.needAuthorization),
            contractName: result?.privacyContractName ?? ''
          }),
        fail: () => finish(UNSUPPORTED)
      })
    } catch {
      finish(UNSUPPORTED)
    }

    setTimeout(() => finish(UNSUPPORTED), QUERY_TIMEOUT_MS)
  })
}

/**
 * 打开隐私协议页面（微信原生页）。
 *
 * 用户应当能在同意之前**读到**自己要同意什么。拿不到协议名时这个入口
 * 仍然可用 —— 微信自己会处理「没配置过协议」的情况（调用失败），
 * 所以这里不预先判断。
 */
export function openPrivacyContract(): Promise<void> {
  if (isH5()) return Promise.resolve()

  return new Promise<void>((resolve) => {
    try {
      Taro.openPrivacyContract({ complete: () => resolve() })
    } catch {
      resolve()
    }
  })
}
