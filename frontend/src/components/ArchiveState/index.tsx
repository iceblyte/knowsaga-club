/**
 * 档案页的三态占位：加载中 / 加载失败 / 空态。
 *
 * ## 为什么值得抽成一个组件
 *
 * 四个新页面（看板 / 知识树 / 错题本 / 勋章墙）各自都有这三种状态，
 * 而它们的**视觉与出口完全一致**：一个法阵 + 一句话 + 一个按钮。
 * 分头写的话，会出现「四个页面有四种转场动画、三种失败措辞」的情况 ——
 * 而这类不一致只会让产品显得没做完。
 *
 * ## 三态的区别不是装饰，是「用户能做什么」
 *
 * - `loading`：什么都做不了，所以**不给按钮**（给了也没用）。
 * - `error`：可以重试 → 给「重新加载」。这四页的读取都不写服务端状态，
 *   所以重试一定是安全的。
 * - `empty`：不是错误，是「还没有数据」。给的是**往哪里去**（去召唤一张卷轴），
 *   不是「再来一次」—— 再刷新一百次也变不出数据来。
 *
 * ## 空态不用「暂无数据」
 *
 * 「暂无数据」只说明缺失，读起来像加载失败。这里一律说清**为什么现在是空的、
 * 做完什么它就有了**。
 *
 * ## 它自己负责居中，不依赖调用方
 *
 * 本组件铺满内容区（`flex: 1`）并在内部居中主视觉。不给调用方留
 * 「记得传一个居中类名」这种活 —— 忘传的结果是内容贴在左上角，
 * 而那是四页里每一页都可能忘一次的事。
 */

import { Button, Text, View } from '@tarojs/components'

import type { SpriteName } from '../../assets/sprites'
import { ARCHIVE_COMMON } from '../../constants/copy'
import MagicStage from '../MagicStage'

import './index.scss'

export type ArchiveStateKind = 'loading' | 'error' | 'empty'

export interface ArchiveStateProps {
  kind: ArchiveStateKind
  /** 主标题；不传时按 `kind` 取默认文案 */
  title?: string
  /** 补充说明 */
  body?: string
  /**
   * 按钮文案与动作。
   *
   * `loading` 态**不该传**（见文件头）；`error` 态通常传「重新加载」；
   * `empty` 态传一个能带用户离开这里的动作。
   */
  actionText?: string
  onAction?: () => void
  /** 主视觉精灵；三态各有一个默认 */
  sprite?: SpriteName
}

/** 三态的默认精灵：等的是墨墨（书灵），出错是铜宝（宝箱怪），空的是拾拾 */
const DEFAULT_SPRITE: Record<ArchiveStateKind, SpriteName> = {
  loading: 'momo',
  error: 'tongbao',
  empty: 'shishi'
}

const DEFAULT_TITLE: Record<ArchiveStateKind, string> = {
  loading: ARCHIVE_COMMON.loading,
  error: ARCHIVE_COMMON.loadFailed,
  empty: ''
}

export default function ArchiveState({
  kind,
  title,
  body,
  actionText,
  onAction,
  sprite
}: ArchiveStateProps) {
  const resolvedTitle = title ?? DEFAULT_TITLE[kind]
  const showAction = kind !== 'loading' && Boolean(actionText) && Boolean(onAction)

  return (
    <View className='archive-state'>
      {/* 主视觉与文案吃掉全部剩余高度并在内部居中 —— 无论文案长短，
          按钮都在同一个位置，用户第二次进来不用重新找它 */}
      <View className='archive-state__main'>
        <MagicStage
          size={140}
          spriteSize={60}
          sprite={sprite ?? DEFAULT_SPRITE[kind]}
          spriteMotion={kind === 'loading' ? 'floaty' : 'none'}
        />
        <View className='archive-state__text'>
          {resolvedTitle ? <Text className='h archive-state__title'>{resolvedTitle}</Text> : null}
          {body ? <Text className='sub archive-state__desc'>{body}</Text> : null}
        </View>
      </View>

      {showAction ? (
        <Button className='btn ghost archive-state__btn' onClick={onAction}>
          {actionText}
        </Button>
      ) : null}
    </View>
  )
}
