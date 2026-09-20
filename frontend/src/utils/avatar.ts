/**
 * 头像的选取与上传前置校验（原型外的「头像与昵称」页）。
 *
 * ## 选图为什么不能是一个纯函数
 *
 * 小程序端的官方路径是 **`<button open-type="chooseAvatar">`**（方案 §7.4 明确采用），
 * 它是个**组件**，只能由用户点击触发，没法在工具函数里「调一下」。
 * H5 没有这个组件，走 `Taro.chooseImage`（浏览器里就是一个文件选择框）。
 *
 * 所以平台差异被拆成两半：
 *
 * - **组件那一半**在 `components/AvatarPicker`（它渲染按钮，并决定用哪种方式）；
 * - **工具这一半**在本文件（`chooseImage` 的调用、取消判定、大小校验）。
 *
 * 页面本身不出现任何 `isH5()` 判断。
 *
 * ## 大小为什么在前端先拦一道
 *
 * 后端会读文件魔数严格校验（方案 §7.5），前端拦不住「改名成 .jpg 的 exe」。
 * 但 2 MB 的图片传上去要几十秒，让用户等完再收到 4002 是最差的一种失败，
 * 所以「**明显**超大就不发请求了」。这里只做这一件事，不判断格式 ——
 * 两处各有一套格式规则时，总有一处先过期。
 *
 * `chooseAvatar` 那条路径拿不到文件大小（微信只给一个临时路径），
 * 所以校验只在能拿到大小的时候做。漏网的交给后端 4002。
 */

import Taro from '@tarojs/taro'

/**
 * 头像大小上限。
 *
 * 与后端 `AVATAR_MAX_BYTES` 一致（方案 §7.5）。这里重复一个数字是有意的：
 * 前端的用途是「别传了」，后端的用途是「不许进」—— 前者是体验，后者是安全，
 * 少一个都不行。改上限时两处都要改。
 */
export const AVATAR_MAX_BYTES = 2 * 1024 * 1024

/** 用 MB 表述的上限，给文案用（「不超过 2 MB」） */
export const AVATAR_MAX_LABEL = `${AVATAR_MAX_BYTES / 1024 / 1024} MB`

export interface PickedAvatar {
  /** 本地临时路径，直接交给 `Taro.uploadFile` */
  path: string
  /** 字节数；拿不到时为 0（`chooseAvatar` 那条路径） */
  size: number
}

/**
 * 用户取消选择。
 *
 * `chooseImage` 在用户点「取消」时走的是 **fail 回调**，`errMsg` 形如
 * `chooseImage:fail cancel`。把它当成错误会让用户在什么都没做的情况下
 * 看到一个红点提示 —— 取消是正常操作，不是失败。
 */
export function isPickCancel(error: unknown): boolean {
  const message =
    typeof error === 'string'
      ? error
      : typeof (error as { errMsg?: unknown } | null)?.errMsg === 'string'
        ? ((error as { errMsg: string }).errMsg)
        : ''
  return message.includes('cancel')
}

/**
 * 从相册 / 相机选一张图（H5 与「不想用微信头像」的场景）。
 *
 * @returns 用户取消时返回 `null`（不是异常）
 * @throws 选图失败（无权限等）时抛原始错误，由调用方决定怎么说
 */
export async function pickAvatar(): Promise<PickedAvatar | null> {
  let result: Awaited<ReturnType<typeof Taro.chooseImage>>
  try {
    result = await Taro.chooseImage({
      count: 1,
      // 头像最终会被裁成小圆形，没必要传原图
      sizeType: ['compressed'],
      sourceType: ['album', 'camera']
    })
  } catch (error) {
    if (isPickCancel(error)) return null
    throw error
  }

  const file = result.tempFiles?.[0]
  const path = (file?.path || result.tempFilePaths?.[0] || '').trim()
  if (!path) return null

  // 缩略图 / 部分平台不返回 size（`0`），此时不做本地校验，交给后端
  const size = typeof file?.size === 'number' && file.size > 0 ? file.size : 0
  return { path, size }
}

/** 是否超过本地可接受的大小上限（`size` 为 0 时一律放行，见文件头） */
export function isTooLarge(size: number): boolean {
  return size > AVATAR_MAX_BYTES
}
