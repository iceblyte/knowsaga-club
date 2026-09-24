/**
 * 文档的选取（原型 05·2「上传文档」）。
 *
 * ## 为什么必须拆成两半（与 `utils/avatar.ts` 同构）
 *
 * `Taro.chooseMessageFile` **只在微信端可用**（类型声明里写着 `@supported weapp`），
 * H5 没有这个能力。所以平台差异被拆成两半：
 *
 * - **两个分支**在本文件里（一个调 `chooseMessageFile`，一个用 DOM 的
 *   `<input type="file">`），对外**产出一致的 `PickedDocument`**；
 * - **页面不出现任何 `isH5()` 判断** —— 与头像那条路同一个约定。
 *
 * ## 为什么文件名要单独"产"出来
 *
 * `Taro.uploadFile` 只会把临时路径的**最后一段**当 multipart 的 filename。
 * 微信端那是 `tmp_xxxxxxxx.pdf` 这样的随机临时名：扩展名可能对，但名字不能用；
 * H5 端 `blob:` 路径更是连扩展名都没有。所以两者都必须把**真实文件名**
 * 单独带出去，作为表单字段 `filename` 显式提交（design D11）。
 * 后端据此判扩展名准入与界面显示名。
 *
 * ## 体积预检为什么在前端先拦一道
 *
 * 后端会按真实字节数严格判（`kb_doc_max_bytes`，默认 20 MB）。前端拦不住
 * 「改名成 .pdf 的 exe」——那是后端的事。但 20 MB 传上去要几十秒，
 * 让用户等完再收到 4002 是最差的一种失败，所以「**明显**超大就不发请求了」。
 * 两处各有一套数字，所以改上限时两边都要改（与 `AVATAR_MAX_BYTES` 同一条约定）。
 *
 * 拿不到体积时（`size` 为 0）一律放行，交给后端 —— 猜一个数字出来拦住用户
 * 比放过去更糟。
 */

import Taro from '@tarojs/taro'

import { isH5 } from './platform'

/**
 * 可上传的扩展名（小写、不含点）。**与后端准入清单一致**。
 *
 * 后端那侧是唯一权威（前端拦不住伪造扩展名），这里重复一份是为了
 * 「选文件时就能把不可选的东西灰掉」——那是体验，不是安全。
 */
export const DOCUMENT_EXTS = ['pdf', 'docx', 'md', 'txt'] as const

/** 文件选择框的 `accept`。点号开头的写法浏览器与微信都认。 */
export const DOCUMENT_ACCEPT = DOCUMENT_EXTS.map((ext) => `.${ext}`).join(',')

/**
 * 单份文档的大小上限。
 *
 * 与后端 `kb_doc_max_bytes` 一致（默认 20 MB）。这里的用途是「别传了」，
 * 后端的用途是「不许进」—— 少一个都不行。
 */
export const DOCUMENT_MAX_BYTES = 20 * 1024 * 1024

/** 用 MB 表述的上限，给文案用（「不超过 20 MB」）。 */
export const DOCUMENT_MAX_LABEL = `${DOCUMENT_MAX_BYTES / 1024 / 1024} MB`

/** 选中的文件。两个平台产出的**形状完全一致**。 */
export interface PickedDocument {
  /**
   * 交给 `Taro.uploadFile` 的本地路径。
   *
   * ⚠️ H5 分支下它是 **`URL.createObjectURL` 产生的 objectURL**（`blob:...`），
   * 不是文件系统路径。这条路径**已于 2026-09-24 在真浏览器实测可用**：文件选择器真弹出、
   * 上传落到 `POST /api/v1/kb/documents` 200。（中途曾因 Taro `uploadFile` 默认带凭证
   * 撞上 CORS 预检而**必失败**，已在 `services/request.ts` 显式关掉 `withCredentials`。）
   * 上传完成或放弃后应调 `releaseDocument()` 释放。
   */
  path: string
  /** 字节数；拿不到时为 0（见文件头：为 0 时不做本地预检） */
  size: number
  /** 原始文件名（含扩展名），直接作为表单字段提交给后端 */
  name: string
}

/**
 * 取扩展名（小写、不含点）。取不到时返回空串。
 *
 * 判据是**最后一个点之后的部分**（与后端 `loaders.ext_of` 同一口径），
 * 所以 `机器学习.v2.pdf` → `pdf`、`README` → `''`。
 */
export function extOf(filename: string): string {
  const trimmed = (filename || '').trim()
  const dot = trimmed.lastIndexOf('.')
  // 点在开头（`.gitignore` 这种）不算扩展名分隔符
  if (dot <= 0 || dot === trimmed.length - 1) return ''
  return trimmed.slice(dot + 1).toLowerCase()
}

/** 这份文件名是否在准入清单里。 */
export function isSupportedDocument(filename: string): boolean {
  const ext = extOf(filename)
  return (DOCUMENT_EXTS as readonly string[]).includes(ext)
}

/** 是否超过本地可接受的大小上限（`size` 为 0 时一律放行，见文件头）。 */
export function isTooLarge(size: number): boolean {
  return size > 0 && size > DOCUMENT_MAX_BYTES
}

/** 释放 objectURL（仅 H5 需要；小程序端是空操作）。 */
export function releaseDocument(document: PickedDocument | null): void {
  if (!document) return
  if (!document.path.startsWith('blob:')) return
  try {
    URL.revokeObjectURL(document.path)
  } catch {
    // 释放失败不该影响任何业务流程 —— 它只是内存回收
  }
}

/**
 * 用户取消选择。
 *
 * 与 `utils/avatar.ts` 的 `isPickCancel` 是**同一判据**（`errMsg` 里含
 * `cancel`）：`chooseMessageFile` 在用户点「取消」时走的也是 fail 回调，
 * `errMsg` 形如 `chooseMessageFile:fail cancel`。
 *
 * 为什么不从 `avatar.ts` import：那边那个函数与头像选择器的错误形态绑在一起，
 * 两个模块共用一个「字符串里找 cancel」的实现并不比各写三行更可靠，
 * 反而会让「改头像的取消判定」意外影响文档选择。**判据必须一致**这件事
 * 由这条注释守住。
 */
function isPickCancel(error: unknown): boolean {
  const message =
    typeof error === 'string'
      ? error
      : typeof (error as { errMsg?: unknown } | null)?.errMsg === 'string'
        ? (error as { errMsg: string }).errMsg
        : ''
  return message.includes('cancel')
}

/**
 * 选一份文档。
 *
 * @returns 用户取消时返回 `null`（**不是异常** —— 取消是正常操作，
 *          当成错误会让用户什么都没做就收到一个提示）
 * @throws 选文件失败（无权限、环境不支持等）时抛原始错误，由调用方决定怎么说
 */
export async function pickDocument(): Promise<PickedDocument | null> {
  return isH5() ? pickOnH5() : pickOnWeapp()
}

/** 微信端：从聊天记录里选一个文件（`@supported weapp`）。 */
async function pickOnWeapp(): Promise<PickedDocument | null> {
  let result: Awaited<ReturnType<typeof Taro.chooseMessageFile>>
  try {
    result = await Taro.chooseMessageFile({
      count: 1,
      type: 'file',
      // 扩展名列表让选择器把不可选的文件灰掉（体验，不是安全 ——
      // 真正的准入判定在后端，见文件头）
      extension: [...DOCUMENT_EXTS]
    })
  } catch (error) {
    if (isPickCancel(error)) return null
    throw error
  }

  const file = result.tempFiles?.[0]
  const path = (file?.path || '').trim()
  if (!path) return null

  return {
    path,
    size: typeof file?.size === 'number' && file.size > 0 ? file.size : 0,
    // 微信给的 `name` 就是聊天里那个文件名（含扩展名）
    name: (file?.name || '').trim()
  }
}

/**
 * H5：DOM 的 `<input type="file">`。
 *
 * ## 为什么不能直接用 `Taro.chooseMessageFile`
 *
 * 它在 H5 下没有实现（类型声明标了 `@supported weapp`），调用会抛。
 * Taro 在 H5 也没有提供等价 API，所以这里直接用 DOM —— 页面里不出现
 * `isH5()` 判断，全部收在本函数内。
 *
 * ## 取消是怎么判定的
 *
 * 浏览器**不会**给 `input[type=file]` 任何"取消"事件：用户点取消后
 * 什么都不会发生，`change` 不触发 —— 如果只等 `change`，这个 Promise
 * 会永远挂着，页面就一直停在"选择中"。
 *
 * 通行的办法是盯 `window` 的 `focus`：文件选择框是模态的，关闭时窗口会重新
 * 获得焦点。拿到焦点后**等一个宏任务**再校验 —— `change` 与 `focus` 的
 * 先后顺序在各浏览器里并不一致，先让 `change` 有机会跑完。
 *
 * ⚠️ 这是启发式判定：极端情况下（用户在对话框里停留后直接关掉整个窗口）
 * 可能不触发。它的失败模式是"一直停在选择中"，不会误判成"取消"而丢掉
 * 用户已经选好的文件 —— 这个方向的错误是可以接受的。
 */
function pickOnH5(): Promise<PickedDocument | null> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = DOCUMENT_ACCEPT
    input.style.position = 'fixed'
    input.style.left = '-9999px'

    let settled = false

    const cleanup = (): void => {
      window.removeEventListener('focus', onWindowFocus)
      input.remove()
    }

    const finish = (value: PickedDocument | null): void => {
      if (settled) return
      settled = true
      cleanup()
      resolve(value)
    }

    const fail = (error: unknown): void => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }

    function onWindowFocus(): void {
      // 让 `change`（若会发生）先跑完。0ms 的 setTimeout 已经排到宏任务队尾，
      // 足以让同一次交互里 `change` 先执行。
      setTimeout(() => {
        if (settled) return
        const file = input.files?.[0]
        if (!file) {
          finish(null)
          return
        }
        // `change` 万一没触发（老浏览器 / 某些 WebView），这里兜住
        finish(toPicked(input, file))
      }, 0)
    }

    input.addEventListener('change', () => {
      const file = input.files?.[0]
      if (!file) {
        finish(null)
        return
      }
      finish(toPicked(input, file))
    })

    input.addEventListener('error', () => {
      fail(new Error('文件选择器初始化失败'))
    })

    window.addEventListener('focus', onWindowFocus)

    document.body.appendChild(input)
    input.click()
  })
}

/** 把浏览器给的 `File` 转成统一形状（含 objectURL）。 */
function toPicked(input: HTMLInputElement, file: File): PickedDocument {
  let url = ''
  try {
    url = URL.createObjectURL(file)
  } catch {
    // 极少数环境（老 WebView / 隐私模式）拿不到 objectURL。
    // 此时退而用 `input.value` —— 它在浏览器里是 `C:\fakepath\名字.pdf`，
    // **不能**当上传路径用，但至少让"体积与文件名的预检"先跑起来，
    // 错误会在真正上传时以一次 4000/网络失败的形式暴露，而不是静默丢失。
    url = input.value
  }

  return {
    path: url,
    size: typeof file.size === 'number' && file.size > 0 ? file.size : 0,
    name: (file.name || '').trim()
  }
}
