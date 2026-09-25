/**
 * 社团大厅（原型 01 第 2 / 3 屏）。
 *
 * 全屏只有一个目标：让用户把想学的东西写下来。所以：
 * - 输入区占满剩余高度（`.scrollbox{flex:1}`），视觉上就是页面的主角
 * - 空态给预设热门问题 chip，**点一下填进输入框**（见下）
 * - 已输入态把 chip 换成「追加资料」类动作
 *
 * 与原型的两处说明：
 * 1. 原型把 `AI 将联网补充` 这个 pill 画死在已输入态。实际上它取决于三件事：
 *    后端 `search_enabled`（有没有这个能力）、用户这次的意愿、输入里有没有链接。
 *    所以这里做成**可点的四态**（文案表见 `HALL_SEARCH_COPY`，判定见 `utils/retrieval`）：
 *    有能力且意愿开时是蓝色的「AI 将联网补充 / 读取链接并联网补充」，
 *    否则换成中性的「基于已有知识出题 / 仅读取你的链接」。
 *    保留同一个版位、同一个样式类，只多了 `onClick` —— **零新增元素即零布局漂移**。
 *    后端没有这个能力时点击只提示、不改意愿（用户改不了一个没配的能力）。
 * 2. `上传文档 / 粘贴网址 / 追加背景资料`（P1「卷轴工坊」的多源输入能力）
 *    在 2026-09-24 接通了两个：
 *    - 「上传文档」→ 知识库的上传页（私有知识库已落地）；
 *    - 「粘贴网址」→ 「选择输入方式」那一屏（链接本身靠粘进上面的输入框走
 *      「用户给的链接必读」，没有第二个页面可去）。
 *    「追加背景资料」在原型里没有对应屏，保持原来的 toast。
 *    三个 chip 的动作**分开写**，理由见 `handleAttachTap`。
 * 3. 底部那张冒险者档案卡（等级 / 累计 XP / 连续天数）原本是写死的演示数据，
 *    现在读 `GET /users/me`。它是这一屏唯一需要联网的东西，所以它自己
 *    承担加载态 —— 读不到时只出占位符，整屏不因此变成空页面。见 `HALL_PROFILE_COPY`。
 *
 * ## 预设问题 = 只填进输入框，不直接召唤（2026-09-23 按用户要求改回）
 *
 * ⚠️ **这条行为来回改过两次，别再凭直觉「修」回去。**
 *
 * | 时间 | 行为 | 起因 |
 * |---|---|---|
 * | 2026-09-22 之前 | 只填不发 | 初版 |
 * | 2026-09-22 | **改为点击即召唤** | 用户报「点了没反应、发不出去」 |
 * | 2026-09-23 | **改回只填不发** | 用户要求「点一下出现在搜索框中，用户自行点击召唤」 |
 *
 * 两次都不是谁写错了，而是**对同一个取舍选了不同答案**：
 * 自动召唤省一步，但替用户做了决定；只填不发把决定权还给用户，代价是多点一次。
 * 后者更稳，因为**召唤是一个要花钱的动作**（一次 LLM 出题 + 可能的联网检索），
 * 让它必须经过用户那一次明确的点击。
 *
 * 但「多点一次」不能变成新的困惑：09-22 那次报「点了没反应」的根因
 * **不是「没有自动发送」，而是填完之后界面上没有任何东西提示他还要再点一次**
 * （chip 行当场换成了「追加资料」，输入框里那行字也不显眼）。
 *
 * ⇒ 09-23 先加了一句说明 `热门问题 · 点一下填进输入框`；
 * **同一天又按用户要求删掉后半句，只留 `热门问题`**（用户明确不要这行提示）。
 * 所以现在这一处是「只填不发 ＋ 纯标题」，那点「点了没反应」的观感风险是
 * **知情接受**的（见渲染处注释）—— 别自作主张加回提示，
 * 更别因为「少了提示」就把它改回「点击即召唤」。
 *
 * ⚠️ 换文案时守住「每一条 ≥ 8 字」（`INPUT_MIN_LEN`，真源在后端 `text_cleaner`）。
 * 只填不发之后这条比原来更关键：字数不达标时用户点「召唤副本」会被拦下
 * （按钮是灰的，或服务端判 4001），而那是**用户自己按的**，
 * 所以必须保证预设的每一条都能直接过闸。
 */

import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useMemo, useRef, useState } from 'react'

import PhoneShell from '../../components/PhoneShell'
import ReminderPrompt from '../../components/ReminderPrompt'
import Sprite from '../../components/Sprite'
import {
  ARCHIVE_COMMON,
  COMMON_COPY,
  HALL_PROFILE_COPY,
  HALL_SEARCH_COPY
} from '../../constants/copy'
import {
  INPUT_MAX_LEN,
  INPUT_MIN_LEN,
  MOCK_ATTACH_CHIPS,
  MOCK_SUGGESTIONS
} from '../../constants/mock'
import { useAsyncData } from '../../hooks/useAsyncData'
import { useTabPage } from '../../hooks/useTabPage'
import { fetchProfile } from '../../services/archive'
import { DEFAULT_QUIZ_OPTIONS, useAppStore } from '../../store/useAppStore'
import type { UserPublic } from '../../types/api'
import { hasUrl } from '../../utils/links'
import { goPage } from '../../utils/navigation'
import type { RetrievalMode } from '../../utils/retrieval'
import { resolveRetrievalMode } from '../../utils/retrieval'
import { styleOf } from '../../utils/style'

import './index.scss'

/**
 * 档案副行（原型「1280 / 2000 XP」）。
 *
 * 三种「不在正常态」的情况合成一处，因为它们在这一行里长得一样 ——
 * 都是「这里现在没有数字」：
 *
 * - `user` 为 `null` 且还没失败 → 占位破折号；
 * - `user` 为 `null` 且已经失败 → 说明读不到的原因，而不是继续摆破折号
 *   （一个永远不动的破折号看起来像界面坏了，说不清是哪一边的问题）；
 * - 满级 → 分母取自身，写成分数就是「8000 / 8000」，只报累计值。
 */
function xpLine(user: UserPublic | null, failed: boolean): string {
  if (!user) return failed ? ARCHIVE_COMMON.loadFailed : HALL_PROFILE_COPY.unknown
  if (user.xp_to_next_level <= 0) return HALL_PROFILE_COPY.xpTotal(user.xp_total)
  return HALL_PROFILE_COPY.xpFraction(user.xp_total, user.next_level_xp)
}

/**
 * 取材路径 → pill 文案（`design.md` D8 的四态表 + 「后端没能力」那一行）。
 *
 * 分支判定本身在 `utils/retrieval`（召唤页的兜底步骤名用的是同一份判定）。
 */
const PILL_LABEL: Record<RetrievalMode, string> = {
  unavailable: HALL_SEARCH_COPY.unavailable,
  online: HALL_SEARCH_COPY.online,
  'online-with-link': HALL_SEARCH_COPY.onlineWithLink,
  'link-only': HALL_SEARCH_COPY.linkOnly,
  offline: HALL_SEARCH_COPY.offline
}

/** 蓝色实心胶囊只表示「后端有能力 **且** 用户这次想用」—— 也是那两个「愿意联网」的态。 */
function pillIsActive(mode: RetrievalMode): boolean {
  return mode === 'online' || mode === 'online-with-link'
}

/**
 * 通向知识库的两个 chip。功能开关关掉时一并隐藏（design D18）：
 * 它们分别去 `kb-upload` 与 `kb-source`，留着就是给用户指一条走不通的路。
 * 「追加背景资料」不在其中 —— 它本来只是个占位 toast，与知识库无关。
 */
const KB_ATTACH_CHIPS: readonly string[] = ['上传文档', '粘贴网址']

export default function HallPage() {
  useTabPage('hall')

  const userInput = useAppStore((s) => s.userInput)
  const setUserInput = useAppStore((s) => s.setUserInput)
  const searchEnabled = useAppStore((s) => s.searchEnabled)
  const useSearch = useAppStore((s) => s.useSearch)
  const setUseSearch = useAppStore((s) => s.setUseSearch)
  const setQuizOptions = useAppStore((s) => s.setQuizOptions)
  // 私有知识库的总开关（后端经 `GET /health` 下发）。
  const knowledgeBaseEnabled = useAppStore((s) => s.knowledgeBaseEnabled)

  /**
   * 该显示哪几个「追加资料」chip。
   *
   * ⚠️ 这是 `KNOWLEDGE_BASE_ENABLED` 前端落点之一（design D18）：关掉时滤掉
   * 「上传文档 / 粘贴网址」，因为那两个目的地都是知识库的页面。
   * 保留「追加背景资料」—— 它与知识库无关，本来就是占位 toast。
   */
  const visibleAttachChips = useMemo(
    () =>
      knowledgeBaseEnabled
        ? MOCK_ATTACH_CHIPS
        : MOCK_ATTACH_CHIPS.filter((chip) => !KB_ATTACH_CHIPS.includes(chip)),
    [knowledgeBaseEnabled]
  )

  /** 冒险者档案（原型 01 底部那张卡）。`me` 为 `null` 时卡片只出占位符 */
  const { status, data, reload } = useAsyncData(() => fetchProfile())
  const me = data?.user ?? null

  const [draft, setDraft] = useState(userInput)

  /** 每次重新显示递增，透给页内提醒让它重新判断该不该出现（刚复习完就该消失） */
  const [showSeq, setShowSeq] = useState(0)

  // 首次（挂载时）跳过刷新：那一次由 `useAsyncData` 自己发起，
  // 不跳过的话进大厅会连发两个一模一样的 `/users/me`
  const firstShowRef = useRef(true)

  useDidShow(() => {
    // 从召唤页返回时同步回已提交的输入
    setDraft(useAppStore.getState().userInput)
    setShowSeq((value) => value + 1)

    // 这是标签页，打完一局再切回来页面不会卸载 —— 档案卡上的等级与 XP
    // 必须重取，否则它会永远停在进这一屏的那一刻。
    // `useAsyncData` 重新加载期间保留旧数据，所以这里不会闪空。
    if (firstShowRef.current) {
      firstShowRef.current = false
      return
    }
    reload()
  })

  const trimmedLen = draft.trim().length
  const canSubmit = trimmedLen >= INPUT_MIN_LEN
  const hasInput = trimmedLen > 0

  /**
   * 输入里有没有链接（与后端**同源**的规则，见 `utils/links` 与 `shared/link-cases.json`）。
   *
   * 它只决定 pill 显示哪句话 —— 服务端会自己再算一遍。前端算错不会导致
   * 「贴了链接却没被读」，最多是那一句话说得不准。
   */
  const inputHasLink = useMemo(() => hasUrl(draft), [draft])

  /**
   * 取材路径（能力 × 意愿 × 有无链接）。判定与召唤页兜底步骤名**共用**
   * `utils/retrieval` 的同一份逻辑 —— 两处各写一遍迟早会改歪一处。
   */
  const mode = resolveRetrievalMode(searchEnabled, useSearch, inputHasLink)
  const pillLabel = PILL_LABEL[mode]
  const pillBlue = pillIsActive(mode)

  /**
   * 点 pill = 翻转本次召唤的意愿。
   *
   * 能力关时**只提示、不改意愿**。若这时顺手把意愿也翻掉，等哪天后端配好 key，
   * 界面会莫名其妙停在「基于已有知识出题」上，而没人知道是谁改的。
   */
  const handlePillTap = () => {
    if (!searchEnabled) {
      Taro.showToast({ title: HALL_SEARCH_COPY.unavailableToast, icon: 'none' })
      return
    }
    setUseSearch(!useSearch)
  }

  /**
   * 点预设问题 = **填进输入框**（2026-09-23 按用户要求改回；两次改动的取舍见文件头）。
   *
   * 只做两件事，**不跳转**：把问题写进输入框，等用户自己点「召唤副本」。
   * 于是下面「召唤副本」按钮的 `canSubmit` 与字数校验照旧生效 ——
   * 用户还有机会改几个字再发，而不是被 chip 直接替他决定一次付费的召唤。
   *
   * ## 为什么也写 store，而不只 `setDraft`
   *
   * 大厅是**标签页**：切走再切回来组件不卸载，`useDidShow` 会执行
   * `setDraft(store.userInput)` 把输入框**重置回 store 里的值**。
   * 只写本地 draft 的话，用户点完 chip、顺手切一下标签页再回来，
   * 刚填进去的那句话就被这个重置擦掉了 —— 表现和「点了没反应」一模一样。
   *
   * 同理 `onInput` 也镜像进 store（见下），这样 draft 与 store 永远一致，
   * 那次重置就成了一步无副作用的空操作，用户**手打的**内容也不会被擦掉。
   */
  const fillPreset = (question: string) => {
    setDraft(question)
    setUserInput(question)
  }

  /**
   * 三个「追加资料」chip 各自去真正的页面（2026-09-24 接通）。
   *
   * 接通之前它们统一弹一句 `COMMON_COPY.comingSoon`（「这功能还在路上」）。
   * 现在「上传文档」已经真的能走通了，所以它直接进上传页 —— chip 上写的
   * 就是「上传文档」，让用户先看一屏「选择输入方式」再点一次是多余的。
   *
   * 另外两个 chip（粘贴网址 / 追加背景资料）仍然没有对应能力：
   *
   * - 「粘贴网址」其实**已经能用** —— 但它的用法是把链接粘进上面那个输入框
   *   （后端「用户给的链接必读」那一套），没有第二个页面可去。所以它进的是
   *   「选择输入方式」那一屏，在那里能看到四种来源的现状；
   * - 「追加背景资料」在原型里就是一个还没定义的东西（没有对应屏），
   *   所以它保持原来的 toast —— 这是**唯一**还该弹这句的地方。
   *
   * ⚠️ 三个 chip 的动作**必须分开写**，不要图省事合成一个 handler：
   * 合成之后任何一次调整都会同时改掉另外两个，而它们的答案本来就不一样。
   */
  const handleAttachTap = (chip: string) => {
    if (chip === '上传文档') {
      // 不带 kb_id：落到默认库（design D16），用户不必先挑一个库
      goPage('/pages/workshop/kb-upload/index', 'navigate')
      return
    }
    if (chip === '粘贴网址') {
      goPage('/pages/workshop/kb-source/index', 'navigate')
      return
    }
    Taro.showToast({ title: COMMON_COPY.comingSoon, icon: 'none' })
  }

  const handleSubmit = () => {
    if (!canSubmit) {
      Taro.showToast({
        title: `再多写几个字吧（至少 ${INPUT_MIN_LEN} 个）`,
        icon: 'none'
      })
      return
    }
    setUserInput(draft.trim())
    /**
     * ⚠️ 大厅这条必须**显式写回默认出题参数**。
     *
     * 知识库那条路会把 `kbId` 写进 store，而 store 是内存态的、不会自己清。
     * 不重置的话，用户从知识库出过题之后回到大厅用一句话召唤，
     * 这一局仍然会在**上一个知识库里取材** —— 而他刚刚完全没有提到那个库。
     * 题量与难度同理（知识库那页可以选 3 题，大厅这一路一直是 5 题）。
     */
    setQuizOptions(DEFAULT_QUIZ_OPTIONS)
    goPage('/pages/summon/index', 'navigate')
  }

  return (
    <PhoneShell navTitle='社团大厅' showBack={false} scroll={false} reserveTabBar>
      {/* 身份欢迎卡 */}
      <View className='card'>
        <View className='row'>
          <View className='hall__sprite-slot'>
            <Sprite name='shishi' size={46} />
          </View>
          <View className='hall__welcome-text'>
            {/* 这两行在原型里是 <div>（块级）。小程序里 <text> 默认 inline，
                两行会挤在同一行，所以这里必须用 View 才等于原型的换行效果。 */}
            <View className='h sm'>冒险者，欢迎回到社团大厅</View>
            <View className='sub hall__welcome-sub'>今天想拾取哪一块知识？</View>
          </View>
        </View>
      </View>

      {/* 今日有到期错题的页内提示（方案 §8.5）。
          放在欢迎卡之后、输入框之前：它是一条「顺带告诉你」，
          不该抢输入框的位置，也不该被压到屏幕底部看不见。
          今日无到期错题、或今天已点过「今天先不复习」时它什么都不渲染。 */}
      <ReminderPrompt refreshKey={showSeq} />

      {/* 卷轴输入框：占满剩余高度 */}
      <View className='scrollbox hall__input'>
        <View className='inner'>
          <Textarea
            className='hall__textarea'
            placeholderClass='hall__placeholder'
            value={draft}
            placeholder={'说出你想学的任何知识…\n一句话 / 一段文字 / 一个网址 / 一份文档'}
            maxlength={INPUT_MAX_LEN}
            autoHeight={false}
            cursorSpacing={24}
            // 手打的字也镜像进 store —— 与 `fillPreset` 同一个理由：
            // 大厅是标签页，`useDidShow` 会拿 store 的值重置输入框，
            // 两边不一致时用户切个标签页回来，刚打的字就被擦掉了。
            // 镜像之后 draft 与 store 永远相等，那次重置就成了空操作。
            onInput={(e) => {
              const next = e.detail.value.slice(0, INPUT_MAX_LEN)
              setDraft(next)
              setUserInput(next)
            }}
          />
          <View className='between'>
            {hasInput ? (
              <Text
                className={`pill${pillBlue ? ' blue' : ''}`}
                onClick={handlePillTap}
              >
                {pillLabel}
              </Text>
            ) : (
              <View />
            )}
            <Text className='tiny'>
              {draft.length} / {INPUT_MAX_LEN}
            </Text>
          </View>
        </View>
      </View>

      {/* 空态：预设热门问题 / 已输入态：追加资料 chip。
          两种状态的 chip **动作完全不同**（一个是「填进输入框」，
          一个是「本期还没做的多源输入」），所以不共用一个 handler。 */}
      {hasInput ? (
        <View className='row hall__chips'>
          {visibleAttachChips.map((chip) => (
            <Text key={chip} className='chip' onClick={() => handleAttachTap(chip)}>
              {chip}
            </Text>
          ))}
        </View>
      ) : (
        <>
          {/* 标题只留「热门问题」——后半句「· 点一下填进输入框」是 09-23 加的，
              当天又按用户要求删掉。09-22 那次「点了没反应」曾靠这半句来消解，
              现在改为**知情接受**：chip 只填不发，界面上不再解释点击后果。
              **这是用户明确的选择，不是漏写** —— 别加回提示，
              也别拿「少了提示」当理由把它改回「点击即召唤」。 */}
          <View className='tiny hall__chips-label'>
            热门问题
          </View>
          <View className='row hall__chips'>
            {MOCK_SUGGESTIONS.map((question) => (
              <Text key={question} className='chip' onClick={() => fillPreset(question)}>
                {question}
              </Text>
            ))}
          </View>
        </>
      )}

      <Button className={`btn${canSubmit ? '' : ' dis'}`} disabled={!canSubmit} onClick={handleSubmit}>
        召唤副本
      </Button>

      {/* 冒险者档案（真实数据：`GET /users/me`，见 `HALL_PROFILE_COPY`）。
          注意：等级进度条属于**卡片内部**的元素 —— 原型里 `.between` 之后紧跟一个
          8px 留白，然后才是 `.bar.blue`，但整条 bar 仍在 `.card` 里。
          早前把它写在 `card` 闭合之后，于是变成一条悬在卡片与标签栏之间的孤立蓝条
          （轨道色 $paper3 与底板 $board 接近，看上去就只剩那条 64% 的蓝色）。

          读不到数据时这张卡**照样在**，只是数字位置变成占位符 ——
          它不能整块消失，也不能退回默认值：`.hall__input` 是 `flex:1`，
          卡片一旦消失，上面的输入框会立刻长高，等数据回来再缩回去，
          看上去就是「页面自己抖了一下」。 */}
      <View className='card'>
        <View className='between'>
          <View className='row hall__adventurer'>
            <Sprite name='scholar' size={32} />
            <View>
              {/* 同上：原型是 <div>，块级才换行 */}
              <View className='hall__level'>
                {me ? HALL_PROFILE_COPY.level(me.level, me.level_title) : HALL_PROFILE_COPY.unknown}
              </View>
              <View className='tiny'>{xpLine(me, status === 'error')}</View>
            </View>
          </View>
          {/* 连续天数是胶囊，缺数据时**整个不渲染**：它在右侧，
              消失不会挪动左边的头像与等级（`between` 只把两端撑开） */}
          {me ? (
            <Text className='pill gold'>{HALL_PROFILE_COPY.streak(me.streak_days)}</Text>
          ) : null}
        </View>

        {/* 原型 `<div style="height:8px">`：档案行与进度条之间的留白 */}
        <View className='hall__gap' />

        {/* 等级进度条，宽度由服务端给的 `level_progress` 决定 */}
        <View className='bar blue'>
          <View style={styleOf({ width: `${me?.level_progress ?? 0}%` })} />
        </View>
      </View>
    </PhoneShell>
  )
}
