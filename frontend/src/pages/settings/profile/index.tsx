/**
 * 头像与昵称（原型外，方案 §7.4 明确要求新增的一屏）。
 *
 * ## 两条路，两个提交时机
 *
 * - **头像**：选完就传（`POST /users/me/avatar`）或选完就改（`PATCH /users/me`），
 *   不攒到「保存」里。头像是一张会立刻显示出来的图，让它停在「待保存」状态
 *   没有意义 —— 而且用户会以为已经换好了。
 * - **昵称**：改完按保存。文本是**可以慢慢改**的东西（打字、删掉、再打），
 *   每敲一个字符提交一次既浪费又会在服务端留下一串中间态。
 *
 * 所以页面底部那颗「保存」只管昵称。这也意味着它不该在昵称没变时假装保存成功
 * （见 `unchanged` / `nicknameRequired` 两段文案）。
 *
 * ## 隐私时序：先拦住，再放开
 *
 * 未同意《用户隐私保护指引》时，微信会把 `<input type="nickname">` **降级成
 * 普通输入框**，界面上看不出任何区别 —— 用户以为在填微信昵称，微信侧的校验
 * 其实已经不在。这是本项目最需要防的静默失效，所以**未同意时不渲染编辑控件**
 * （`PrivacyGate` 顶掉头像选择器与昵称输入框），而不是渲染一个「能用但其实是假的」的界面。
 *
 * 状态未知（`privacy === null`，查询还没回来）时**也先不渲染**：先渲染再拦
 * 会有一个短暂窗口，用户可能正好点进输入框。查询在 H5 与低版本基础库上是
 * 同步返回「不需要」的（见 `utils/privacy`），所以这个中间态几乎看不见。
 *
 * 预置头像**不依赖微信能力**（它只是一个 PATCH），所以它在任何状态下都可用 ——
 * 没同意协议的用户照样能换头像，只是不能用微信昵称那一套。
 *
 * ## 头像上传成功后为什么还要 `reload()`
 *
 * 上传接口只返回 `{ user }`，**没有 `stats`**（改头像不影响副本数）。
 * 拿它替换页面数据会让统计消失，所以先用 `updateUser` 同步本地登录态快照
 * （个人中心、公会卡读的是它），再 `reload()` 取回完整的一份。
 * 多一次 GET，换来的是页面上的数字始终来自同一个接口。
 *
 * ## 选中的预置头像
 *
 * 「自定义头像优先」是服务端的读取规则（方案 §5.1），所以有自定义头像时
 * 预置那一排**一个都不高亮** —— 高亮某一个会让用户以为当前用的是它。
 * 点任意一个预置头像会连自定义头像一起换掉（后端在写 `avatar_key` 时
 * 会清掉 `avatar_url`，否则点了看不到变化）。
 */

import { Button, Input, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import Avatar from '../../../components/Avatar'
import AvatarPicker from '../../../components/AvatarPicker'
import PhoneShell from '../../../components/PhoneShell'
import PrivacyGate from '../../../components/PrivacyGate'
import { ARCHIVE_COMMON, AVATAR_PRESETS, SETTINGS_PROFILE_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchProfile } from '../../../services/archive'
import { updateUser } from '../../../services/session'
import { updateProfile, uploadAvatar } from '../../../services/settings'
import type { PickedAvatar } from '../../../utils/avatar'
import { goPage } from '../../../utils/navigation'
import { isH5 } from '../../../utils/platform'
import { queryPrivacyAuthorization, type PrivacyState } from '../../../utils/privacy'

import './index.scss'

/**
 * 昵称输入框的 `type`。
 *
 * 小程序端必须是 `'nickname'` —— 只有它才会让微信在输入框上方给出
 * 「使用微信昵称」的填写入口。H5 没有这个类型（也没有那套能力），用 `'text'`。
 *
 * 这里有一次类型断言：Taro 的 `InputProps['type']` 是它自己列的一套联合类型，
 * 里面没有 `'nickname'`。断言成 `'text'` 是为了过类型检查，运行时传的仍是
 * `'nickname'` —— 一个**只在 H5 分支之外生效**的字面量。
 */
const NICKNAME_INPUT_TYPE = (isH5() ? 'text' : 'nickname') as 'text'

export default function SettingsProfilePage() {
  const { status, data, reload } = useAsyncData(() => fetchProfile())

  /**
   * 昵称草稿。
   *
   * `null` 表示「用户还没动过」，此时显示服务端的值。不用 `useEffect` 在数据
   * 到达后回填 —— 那样用户在数据回来之前敲的字符会被覆盖掉。
   */
  const [nickDraft, setNickDraft] = useState<string | null>(null)
  /** 刚选好、还没上传完的本地路径（预览用） */
  const [pickedPath, setPickedPath] = useState('')
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  /** `null` = 还没查出来（见文件头：这个状态下不渲染编辑控件） */
  const [privacy, setPrivacy] = useState<PrivacyState | null>(null)

  useEffect(() => {
    let alive = true
    queryPrivacyAuthorization().then((state) => {
      if (alive) setPrivacy(state)
    })
    return () => {
      alive = false
    }
  }, [])

  if (!data || !privacy) {
    return (
      <PhoneShell navTitle={SETTINGS_PROFILE_COPY.navTitle} screenClassName='settings-profile'>
        {status === 'error' ? (
          <ArchiveState
            kind='error'
            title={SETTINGS_PROFILE_COPY.loadFailed}
            actionText={ARCHIVE_COMMON.retry}
            onAction={reload}
          />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  const { user } = data
  const nickname = nickDraft ?? user.nickname
  /** 未同意隐私协议时不放编辑控件（见文件头） */
  const editorReady = !privacy.need

  /** 同意之后重查一次；`need` 变成 `false` 时编辑控件自然出现 */
  const acceptPrivacy = (): void => {
    queryPrivacyAuthorization().then(setPrivacy)
  }

  /** 拒绝的出口：退回设置页。不留在这一屏对着一个不能用的界面 */
  const leave = (): void => {
    Taro.navigateBack({ delta: 1 }).catch(() => {
      goPage('/pages/settings/index')
    })
  }

  const handlePick = (picked: PickedAvatar): void => {
    setPickedPath(picked.path)
    setUploading(true)
    uploadAvatar(picked.path)
      .then((result) => {
        updateUser(result.user)
        reload()
      })
      .catch(() => {
        // 撤掉预览：留着它会让用户以为已经换上了
        setPickedPath('')
        Taro.showToast({ title: SETTINGS_PROFILE_COPY.avatarFailed, icon: 'none' })
      })
      .finally(() => {
        setUploading(false)
      })
  }

  const choosePreset = (key: string): void => {
    if (uploading || saving) return
    // 当前用的就是它（且没有自定义头像）→ 无事可做。
    // 界面已经把「选中的那个」高亮出来了，所以不必再弹一句提示。
    if (!user.avatar_url && user.avatar_key === key) return

    updateProfile({ avatar_key: key })
      .then((result) => {
        updateUser(result.user)
        setPickedPath('')
        reload()
      })
      .catch(() => {
        Taro.showToast({ title: SETTINGS_PROFILE_COPY.saveFailed, icon: 'none' })
      })
  }

  const saveNickname = async (): Promise<void> => {
    if (saving) return

    const next = nickname.trim()
    if (!next) {
      Taro.showToast({ title: SETTINGS_PROFILE_COPY.nicknameRequired, icon: 'none' })
      return
    }
    if (next === user.nickname) {
      Taro.showToast({ title: SETTINGS_PROFILE_COPY.unchanged, icon: 'none' })
      return
    }

    setSaving(true)
    try {
      const result = await updateProfile({ nickname: next })
      updateUser(result.user)
      setNickDraft(null)
      reload()
      Taro.showToast({ title: SETTINGS_PROFILE_COPY.saved, icon: 'none' })
    } catch (error) {
      // 昵称的规则在后端（`normalize_nickname` 判 4001），它的文案比前端
      // 能编的任何一句都准 —— 拿不到就用兜底，不自己编一句「格式不对」。
      const message =
        error instanceof Error && error.message
          ? error.message
          : SETTINGS_PROFILE_COPY.saveFailed
      Taro.showToast({ title: message, icon: 'none' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <PhoneShell navTitle={SETTINGS_PROFILE_COPY.navTitle} screenClassName='settings-profile'>
      {privacy.need && (
        <PrivacyGate
          contractName={privacy.contractName}
          onAgree={acceptPrivacy}
          onLater={leave}
        />
      )}

      {/* ---- 头像：自选图片（依赖微信能力，未同意时由 PrivacyGate 顶掉）---- */}
      {editorReady && (
        <View className='card plain'>
          <View className='tiny settings-profile__label'>
            {SETTINGS_PROFILE_COPY.avatarLabel}
          </View>
          <AvatarPicker
            avatarKey={user.avatar_key}
            avatarUrl={user.avatar_url}
            localPath={pickedPath}
            busy={uploading}
            onPick={handlePick}
          />
        </View>
      )}

      {/* ---- 预置头像：不依赖微信能力，任何状态下都能用 ---- */}
      <View className='card plain'>
        <View className='tiny settings-profile__label'>
          {SETTINGS_PROFILE_COPY.presetLabel}
        </View>
        <View className='row settings-profile__presets'>
          {AVATAR_PRESETS.map((preset) => {
            const active = !user.avatar_url && user.avatar_key === preset.key
            return (
              <View
                key={preset.key}
                className={`settings-profile__preset${
                  active ? ' settings-profile__preset--on' : ''
                }`}
                onClick={() => choosePreset(preset.key)}
              >
                <Avatar avatarKey={preset.key} size={44} />
                <View className='tiny'>{preset.label}</View>
              </View>
            )
          })}
        </View>
      </View>

      {/* ---- 昵称 ---- */}
      {editorReady && (
        <View className='card plain'>
          <View className='tiny settings-profile__label'>
            {SETTINGS_PROFILE_COPY.nicknameLabel}
          </View>
          <Input
            className='settings-profile__input'
            type={NICKNAME_INPUT_TYPE}
            value={nickname}
            placeholder={SETTINGS_PROFILE_COPY.nicknamePlaceholder}
            onInput={(event) => setNickDraft(event.detail.value)}
          />
          <View className='tiny settings-profile__hint'>
            {SETTINGS_PROFILE_COPY.nicknameHint}
          </View>
        </View>
      )}

      <View className='spacer' />

      {/* 未同意协议时这里没有按钮 —— `PrivacyGate` 已经把「来 / 不来」两条路
          都摆在面板里了，再在页脚留一颗孤零零的按钮只会让人以为还有别的动作 */}
      {editorReady && (
        <Button className='btn' disabled={saving} onClick={() => void saveNickname()}>
          {saving ? SETTINGS_PROFILE_COPY.saving : SETTINGS_PROFILE_COPY.save}
        </Button>
      )}
    </PhoneShell>
  )
}
