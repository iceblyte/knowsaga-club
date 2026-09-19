/**
 * 知识树（原型 04·4）。
 *
 * ## 顶部的「树冠」为什么是一团点，而不是原型那棵三层树
 *
 * 原型的树画了三层：`AI 基础 → RAG → (向量检索 / 知识库)`。那是**演示数据**
 * 里手写的从属关系。而真实数据里，知识点是一串**扁平的标签**
 * （`questions.knowledge_point`），没有任何父子信息。
 *
 * 凭空给它们编一层从属关系，就是往界面上放假数据 —— 用户会以为
 * 「向量检索属于 RAG」是系统从资料里推出来的，而实际上只是这里写死的一句话。
 * 所以树冠只表达**一件真事**：这个用户点亮了多少个领域、各自处在哪个状态。
 * 名字与掌握度由下面那张列表逐个给出，一个都不少。
 *
 * ## 树冠为什么用定位的圆点而不是 SVG
 *
 * 小程序没有 `<svg>` 组件，项目里渲染矢量图形的两条路都是 data URI
 * （静态的在 scss 里，动态的要在运行时拼字符串再编码）。这里的图形
 * **完全由数据算出来**，走 data URI 就得在运行时拼 SVG 再编码 ——
 * 而位置本来就可以直接算成百分比。
 *
 * 用百分比还有一个好处：**不会踩「内联样式写死 rpx」那个坑**
 * （见 `utils/style.ts`），也不用为每种屏幕宽度重算。
 *
 * 布局用向日葵排布（黄金角 137.5° + 半径按 √i 展开）：它天然均匀、
 * 不需要碰撞检测，数量少时是一小簇、多时自然铺满，像枝叶而不是表格。
 */

import { Button, Text, View } from '@tarojs/components'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import Sprite from '../../../components/Sprite'
import { ARCHIVE_COMMON, KNOWLEDGE_TREE_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchKnowledgeTree } from '../../../services/archive'
import type { KnowledgeNode, KnowledgeState } from '../../../types/api'
import { goTab } from '../../../utils/navigation'
import { styleOf } from '../../../utils/style'

import './index.scss'

// ---- 树冠的几何参数（原型 px）----
const CANOPY_W = 300
const CANOPY_H = 176
const CANOPY_CX = 150
const CANOPY_CY = 92
/** 圆点中心的最大半径。留出边距，否则边缘的点会被卡片裁掉 */
const CANOPY_R = 72
/** 圆点直径 */
const DOT = 14
/**
 * 树冠最多画这么多点。
 *
 * 向日葵排布在半径 72、点径 14 的盘里，超过约 70 个点就会开始互相重叠。
 * 取 48 是留足余量的保守值；超出的领域在下面的列表里照常逐条列出 ——
 * 树冠是氛围，列表才是清单。
 */
const CANOPY_MAX_DOTS = 48

/** 掌握度分档（与看板同一口径，见 pages/profile/dashboard） */
const LIT_THRESHOLD = 90

interface CanopyDot {
  key: string
  /** 百分比位置（相对树冠容器） */
  left: number
  top: number
  state: KnowledgeState
}

function canopyDots(nodes: KnowledgeNode[]): CanopyDot[] {
  const visible = nodes.slice(0, CANOPY_MAX_DOTS)
  const total = visible.length

  return visible.map((node, index) => {
    // 只有一个领域时放在正中，不然 sqrt 公式会把它推到边上
    const radius = total === 1 ? 0 : CANOPY_R * Math.sqrt((index + 0.5) / total)
    const angle = (index * 137.508 * Math.PI) / 180
    const x = CANOPY_CX + radius * Math.cos(angle) - DOT / 2
    const y = CANOPY_CY + radius * Math.sin(angle) - DOT / 2

    return {
      key: node.name,
      left: (x / CANOPY_W) * 100,
      top: (y / CANOPY_H) * 100,
      state: node.state
    }
  })
}

const STATE_PILL: Record<KnowledgeState, string> = {
  lit: 'pill ok',
  growing: 'pill gold',
  not_started: 'pill'
}

const STATE_LABEL: Record<KnowledgeState, string> = {
  lit: KNOWLEDGE_TREE_COPY.stateLit,
  growing: KNOWLEDGE_TREE_COPY.stateGrowing,
  not_started: KNOWLEDGE_TREE_COPY.stateNotStarted
}

/** 列表左侧那个 28px 单字方块的配色，三态各一套（原型三行样例） */
function iconClass(state: KnowledgeState): string {
  if (state === 'lit') return 'tree__ico tree__ico--lit'
  if (state === 'growing') return 'tree__ico tree__ico--growing'
  return 'tree__ico tree__ico--none'
}

function masteryClass(mastery: number): string {
  if (mastery >= LIT_THRESHOLD) return 'c-ok'
  if (mastery <= 0) return 'c-mute'
  return 'c-gold'
}

export default function KnowledgeTreePage() {
  const { status, data, reload } = useAsyncData(() => fetchKnowledgeTree())

  if (!data) {
    return (
      <PhoneShell navTitle={KNOWLEDGE_TREE_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  if (data.nodes.length === 0) {
    return (
      <PhoneShell navTitle={KNOWLEDGE_TREE_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={KNOWLEDGE_TREE_COPY.emptyTitle}
          body={KNOWLEDGE_TREE_COPY.emptyBody}
          actionText={KNOWLEDGE_TREE_COPY.emptyCta}
          onAction={() => goTab('/pages/hall/index')}
        />
      </PhoneShell>
    )
  }

  const dots = canopyDots(data.nodes)
  // 点亮的用实心绿，进行中用黄铜，没开始的只是一个圈
  const dotClass: Record<KnowledgeState, string> = {
    lit: 'tree__dot tree__dot--lit',
    growing: 'tree__dot tree__dot--growing',
    not_started: 'tree__dot tree__dot--none'
  }

  return (
    <PhoneShell navTitle={KNOWLEDGE_TREE_COPY.navTitle}>
      {/* ---- 树冠 ---- */}
      <View className='card plain'>
        <View className='tree__canopy'>
          {dots.map((dot) => (
            <View
              key={dot.key}
              className={dotClass[dot.state]}
              style={styleOf({ left: `${dot.left}%`, top: `${dot.top}%` })}
            />
          ))}
          {/* 树根：拾拾守在正中间。整棵树的「生长」都发生在他周围 */}
          <View className='tree__root'>
            <Sprite name='shishi' size={26} />
          </View>
        </View>
      </View>

      {/* ---- 领域清单 ---- */}
      <View className='card'>
        <View className='stack tight'>
          {data.nodes.map((node) => (
            <View
              className={`row tree__row${
                node.name === data.next_target ? ' tree__row--target' : ''
              }`}
              key={node.name}
            >
              <View className={iconClass(node.state)}>{node.name.slice(0, 1)}</View>

              <View className='tree__body'>
                <View className='between'>
                  <Text className='tiny'>{node.name}</Text>
                  <Text className={`tiny ${masteryClass(node.mastery)}`}>{node.mastery}%</Text>
                </View>
                <View className='tree__row-gap' />
                <View className={`bar ${node.state === 'lit' ? 'ok' : ''}`}>
                  <View style={styleOf({ width: `${node.mastery}%` })} />
                </View>
              </View>

              <Text className={STATE_PILL[node.state]}>{STATE_LABEL[node.state]}</Text>
            </View>
          ))}
        </View>
      </View>

      {/* ---- 建议与出口 ---- */}
      <View className='card parch'>
        <View className='row tree__tip'>
          <Text className='body sm tree__tip-text'>
            {data.suggestion || KNOWLEDGE_TREE_COPY.noSuggestion}
          </Text>
          <Button
            className='btn gold tree__tip-btn'
            onClick={() => goTab('/pages/hall/index')}
          >
            {KNOWLEDGE_TREE_COPY.cta}
          </Button>
        </View>
      </View>
    </PhoneShell>
  )
}
