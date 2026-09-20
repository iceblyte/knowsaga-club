/**
 * 头像选择控件（方案 §7.4）。
 *
 * ## 为什么它必须是一个组件，而不是一个工具函数
 *
 * 小程序端的官方路径是 **`<button open-type="chooseAvatar">`** —— 这是一个
 * **组件**，只能由用户点击触发，没法在函数里「调一下」。而 H5 没有这个组件，
 * 要退到 `Taro.chooseImage`（浏览器里就是一个文件选择框）。
 *
 * 两种方式的**触发入口形态不同**，所以分叉只能落在 JSX 这一层。把它关进
 * 这个组件之后，页面里就不需要写 `isH5()` 了（方案 §7.4 要求「平台差异
 * 收敛在工具层，不在页面里散写环境判断」—— 组件是「工具层」的另一半）。
 *
 * ## 大小校验放在这里，不放在页面
 *
 * 只有这里知道「这次选到的东西有多大」：`chooseImage` 会给 `size`，
 * `chooseAvatar` 不给（微信只回一个临时路径）。页面拿到的是统一的
 * `onPick(path)`，不需要关心这条差异。
 *
 * ## 取消不是失败
 *
 * 用户在系统选择器里点「取消」时 `chooseImage` 走的是 fail 回调。
 * 把它当成错误会让用户在什么都没做的情况下收到一个提示。判定见
 * `utils/avatar.ts` 的 `isPickCancel`。
 */

import { Button, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { SETTINGS_PROFILE_COPY } from '../../constants/copy'
import { isTooLarge, pickAvatar, type PickedAvatar } from '../../utils/avatar'
import { isH5 } from '../../utils/platform'
import Avatar from '../Avatar'

import './index.scss'

export interface AvatarPickerProps {
  /** 预置头像键（服务端给的），预览兜底用 */
  avatarKey: string
  /** 已生效的自定义头像地址（服务端给的） */
  avatarUrl: string | null
  /**
   * 刚选好、**还没上传成功**的本地路径。
   *
   * 非空时预览它而不是服务端那张 —— 否则用户选完图会先看到旧头像，
   * 要等上传 + `reload()` 走完才变，中间那段像是「点了没反应」。
   */
  localPath: string
  /** 上传中：按钮禁用，文字换成进行时 */
  busy: boolean
  onPick: (picked: PickedAvatar) => void
}

/** 原型 00 的 `.advatar` 在 07·4 用的尺寸（比 04·1 的 58 大一圈） */
const PREVIEW_SIZE = 72

export default function AvatarPicker({
  avatarKey,
  avatarUrl,
  localPath,
  busy,
  onPick
}: AvatarPickerProps) {
  const accept = (picked: PickedAvatar | null): void => {
    if (!picked) return // 用户取消：什么都不做
    if (isTooLarge(picked.size)) {
      Taro.showToast({ title: SETTINGS_PROFILE_COPY.avatarTooLarge, icon: 'none' })
      return
    }
    onPick(picked)
  }

  /** H5 这条路：系统文件 / 相册选择器 */
  const chooseFromLibrary = (): void => {
    pickAvatar()
      .then(accept)
      .catch(() => {
        // 走到这里说明不是「取消」，而是真的选不了（无权限、被裁剪的 webview 等）
        Taro.showToast({ title: SETTINGS_PROFILE_COPY.avatarPickFailed, icon: 'none' })
      })
  }

  return (
    <View className='avatar-picker'>
      <Avatar
        avatarKey={avatarKey}
        avatarUrl={localPath || avatarUrl}
        size={PREVIEW_SIZE}
        className='avatar-picker__img'
      />

      {isH5() ? (
        <Button
          className='btn ghost sm avatar-picker__btn'
          disabled={busy}
          onClick={chooseFromLibrary}
        >
          {busy ? SETTINGS_PROFILE_COPY.avatarUploading : SETTINGS_PROFILE_COPY.avatarPickH5}
        </Button>
      ) : (
        /* 微信官方路径：点这个按钮弹出「使用微信头像 / 从相册选择」 */
        <Button
          className='btn ghost sm avatar-picker__btn'
          openType='chooseAvatar'
          disabled={busy}
          onChooseAvatar={(event) => {
            // `onChooseAvatar` 在 Taro 的类型里是未细化的 `CommonEventFunction`，
            // 所以这里自己取 detail —— 与真实小程序返回的 `{avatarUrl}` 对应
            const detail = (event as unknown as { detail?: { avatarUrl?: string } }).detail
            const path = (detail?.avatarUrl ?? '').trim()
            if (!path) return
            // 微信只给路径、不给大小，所以 size 传 0（本地校验跳过，交给后端）
            accept({ path, size: 0 })
          }}
        >
          {busy ? SETTINGS_PROFILE_COPY.avatarUploading : SETTINGS_PROFILE_COPY.avatarPickWeapp}
        </Button>
      )}

      <View className='tiny avatar-picker__hint'>{SETTINGS_PROFILE_COPY.avatarHint}</View>
    </View>
  )
}
