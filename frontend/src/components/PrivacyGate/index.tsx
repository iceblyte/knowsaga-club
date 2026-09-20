/**
 * 隐私协议同意面板（方案 §7.4 的时序要求）。
 *
 * ## 它挡住的到底是什么
 *
 * 微信的「头像昵称填写能力」与《小程序用户隐私保护指引》绑定。用户没同意之前，
 * `<input type="nickname">` **不报错、不弹窗**，而是**降级成普通文本输入框**：
 * 界面上看不出任何区别，用户以为自己在填微信昵称，微信侧的校验其实已经不在。
 * 这是本项目最需要防的「静默失效」，所以未同意时**不渲染编辑控件**，
 * 而是渲染这块面板。
 *
 * ## 为什么面板里必须用 `<button open-type="agreePrivacyAuthorization">`
 *
 * 只有微信官方这个 `open-type` 才会被平台**记账**成「用户同意过了」。
 * 换成普通按钮再调 `requirePrivacyAuthorize()` 也能走通，但那条路径需要
 * 自己实现 `onNeedPrivacyAuthorization` 的 resolve 协议（还要传对 buttonId），
 * 而当前页面并没有「先调隐私接口再补救」的场景 —— 我们是先拦、后放。
 * 少一层协议就少一处会静默失效的地方。
 *
 * ## 它只在小程序端出现
 *
 * `utils/privacy.ts` 在 H5 与低版本基础库上一律返回 `need: false`（见那里的说明），
 * 所以这个组件在那些环境里**根本不会被渲染**。因此这里不再写 `isH5()` 分支 ——
 * 一个永远不会执行的浏览器降级分支，只会让人误以为 H5 上有隐私协议这件事。
 */

import { Button, Text, View } from '@tarojs/components'

import { SETTINGS_PROFILE_COPY } from '../../constants/copy'
import { openPrivacyContract } from '../../utils/privacy'

import './index.scss'

export interface PrivacyGateProps {
  /** 协议名称（`getPrivacySetting` 给的 `privacyContractName`）；拿不到时为空串 */
  contractName: string
  /** 用户同意之后：调用方重新查询一次状态，通过则放出编辑控件 */
  onAgree: () => void
  /**
   * 用户选择「暂不使用」。
   *
   * 拒绝的代价必须与同意**一样低** —— 只留一个返回箭头、把拒绝藏在上一步里，
   * 是一道看不见的门槛。所以这里给一个平等的按钮，由调用方决定退到哪里。
   */
  onLater: () => void
}

export default function PrivacyGate({ contractName, onAgree, onLater }: PrivacyGateProps) {
  return (
    <View className='privacy-gate slip'>
      <View className='privacy-gate__title'>{SETTINGS_PROFILE_COPY.privacyTitle}</View>
      <View className='body sm privacy-gate__body'>{SETTINGS_PROFILE_COPY.privacyBody}</View>

      {/* 用户应当能在同意之前读到自己要同意什么。拿不到协议名时这个入口仍然在
          —— 微信自己会处理「没配置过协议」的情况（调用失败），这里不预先判断 */}
      <Text className='tiny privacy-gate__link' onClick={() => void openPrivacyContract()}>
        {contractName
          ? `${SETTINGS_PROFILE_COPY.privacyRead}《${contractName}》`
          : SETTINGS_PROFILE_COPY.privacyRead}
      </Text>

      <View className='privacy-gate__actions'>
        <Button
          className='btn privacy-gate__agree'
          openType='agreePrivacyAuthorization'
          onAgreePrivacyAuthorization={onAgree}
        >
          {SETTINGS_PROFILE_COPY.privacyAgree}
        </Button>

        <Button className='btn ghost sm privacy-gate__later' onClick={onLater}>
          {SETTINGS_PROFILE_COPY.privacyLater}
        </Button>
      </View>
    </View>
  )
}
