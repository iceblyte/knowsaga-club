/**
 * 帮助与反馈（原型 07·8）。
 *
 * ## 与原型的三处不一致，以及为什么
 *
 * 1. **第 2 条 FAQ 的答案换掉了**。原型写「每天 3 次，会员不限次数」，而本产品
 *    既没有每日次数限制，也没有会员体系（会员那四屏在需求文档里被标为不做）。
 *    点开「查看」读到一条与事实相反的产品承诺，比少一条 FAQ 糟得多。
 *    需求 FR-D6 只要求 3 条 FAQ，没规定写哪三条。
 * 2. **「联系开发者」的副标题换掉了**（原型的「工作日 24 小时内回复」）。那是一个
 *    服务承诺，而这个仓库没有客服排班 —— 写上去就是编。换成这颗按钮**真的做的事**：
 *    复制账号信息，方便定位问题。
 * 3. **「举报题目问题」与「联系开发者」都是复制模板，不是发信**。MVP 没有反馈
 *    后台，也就没有收件箱。与其做一个点了没反应的入口，不如把模板放进剪贴板
 *    并说清下一步（粘给开发者）。这也是为什么两处的提示语都带动作
 *    （「粘贴给开发者即可」），而不是一句「已复制」。
 *
 * ## 展开态：行里的短结论 ≠ 展开的详细说明
 *
 * 行里的 `short` 是一句话结论，展开给的是「所以我该怎么做」。两者写成一模一样
 * 的话，那个「查看」就没有存在的意义（见 `SETTINGS_HELP_COPY` 的说明）。
 * 一次只展开一条：三条全开着会把这一屏变成一篇文章，而用户是来找某一条答案的。
 */

import { Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import PhoneShell from '../../../components/PhoneShell'
import { APP_COPY, SETTINGS_HELP_COPY } from '../../../constants/copy'
import { getUser } from '../../../services/session'

import './index.scss'

/**
 * 复制一段文本并给回执。
 *
 * 微信的 `setClipboardData` **自己会弹一个「内容已复制」**，所以这里不是
 * 「补一个提示」，而是**替换**它：`showToast` 是单例，后一个会顶掉前一个。
 * 我们要说的比「内容已复制」多一句下一步（粘给谁、能干什么）。
 */
async function copyText(data: string, okText: string, failText: string): Promise<void> {
  try {
    await Taro.setClipboardData({ data })
    Taro.showToast({ title: okText, icon: 'none' })
  } catch {
    Taro.showToast({ title: failText, icon: 'none' })
  }
}

export default function SettingsHelpPage() {
  /** 展开的 FAQ 下标；`null` 表示都收起 */
  const [openIndex, setOpenIndex] = useState<number | null>(null)

  /**
   * 账号信息。
   *
   * 取自**本地登录态快照**（`services/session`）—— 这一屏是兜底页面，
   * 为了两行模板再发一次 `GET /users/me` 不值当，而且拿不到时也不该
   * 让反馈入口变成死路（模板里写上「未取到」照样能用）。
   */
  const me = getUser()
  const account = me ? `${me.nickname} #${me.id}` : '（未取到账号信息）'

  const reportProblem = (): void => {
    void copyText(
      SETTINGS_HELP_COPY.reportTemplate(account),
      SETTINGS_HELP_COPY.reportCopied,
      SETTINGS_HELP_COPY.reportFailed
    )
  }

  const contactDeveloper = (): void => {
    void copyText(
      SETTINGS_HELP_COPY.contactTemplate(me?.nickname ?? '—', me?.id ?? 0, APP_COPY.version),
      SETTINGS_HELP_COPY.contactCopied,
      SETTINGS_HELP_COPY.copyFailed
    )
  }

  return (
    <PhoneShell navTitle={SETTINGS_HELP_COPY.navTitle} screenClassName='settings-help'>
      {/* ---- 常见问题：标题一张卡，问题行铺在板上（原型的排法）---- */}
      <View className='card plain'>
        <View className='h sm'>{SETTINGS_HELP_COPY.faqTitle}</View>
      </View>

      {SETTINGS_HELP_COPY.faq.map((item, index) => {
        const open = openIndex === index
        return (
          <View key={item.question}>
            <View className='li' onClick={() => setOpenIndex(open ? null : index)}>
              <View className='ico'>{item.icon}</View>
              <View className='tx'>
                <View className='n'>{item.question}</View>
                <View className='d'>{item.short}</View>
              </View>
              <Text className='pill'>
                {open ? SETTINGS_HELP_COPY.faqActionOpen : SETTINGS_HELP_COPY.faqAction}
              </Text>
            </View>

            {open && (
              <View className='card plain help__detail'>
                <View className='body sm'>{item.detail}</View>
              </View>
            )}
          </View>
        )
      })}

      {/* ---- 举报题目问题：原型用 `.card.bad` + 一个 32px 的警示章 ---- */}
      <View className='card bad' onClick={reportProblem}>
        <View className='row'>
          {/* 「!」是图形符号不是文案，与原型一致（原型也没有把它放进文案表） */}
          <View className='badge help__report-badge'>!</View>
          <View className='help__report-body'>
            <View className='help__report-title'>{SETTINGS_HELP_COPY.reportTitle}</View>
            <View className='tiny'>{SETTINGS_HELP_COPY.reportDesc}</View>
          </View>
          <Text className='tiny'>›</Text>
        </View>
      </View>

      {/* ---- 联系开发者：原型的 `li`，动作是「发信」，这里落到复制账号信息 ---- */}
      <View className='li' onClick={contactDeveloper}>
        <View className='ico'>邮</View>
        <View className='tx'>
          <View className='n'>{SETTINGS_HELP_COPY.contactTitle}</View>
          <View className='d'>{SETTINGS_HELP_COPY.contactDesc}</View>
        </View>
        <Text className='pill'>{SETTINGS_HELP_COPY.contactAction}</Text>
      </View>

      <View className='spacer' />

      {/* 页脚：版本号取自构建期注入的真实版本（FR-D4），不是原型上的 1.0.0 */}
      <View className='tiny help__footer'>{APP_COPY.footer()}</View>
    </PhoneShell>
  )
}
