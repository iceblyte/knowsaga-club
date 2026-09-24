/**
 * 我的知识库（原型 05·5）。
 *
 * ## 这一页在整条链里的位置
 *
 * 「大厅上传文档」是**进入**知识库最省事的一条路（它连库名都不用知道，
 * 后端会去找或建默认库）；这一页是**回头管**的地方：看有哪些库、
 * 每个库有几份能用的文档、以及从哪个库出题。
 *
 * ## 行里的两个可点区域是**并列**的，不是嵌套的
 *
 * 原型那一行的版式是「图标 + 名字 + 副标题 …… 行尾胶囊」，而胶囊对
 * 就绪的库写的是「出题」，是个动作。最直觉的写法是给整行挂 onClick、
 * 再在胶囊上 `stopPropagation()` —— **但小程序端不保险**：微信的 `bindtap`
 * 一律冒泡，Taro 的运行时并不能从源码看出哪个 handler 会调 `stopPropagation`，
 * 于是点胶囊会**同时**触发整行的跳转（去详情）与胶囊自己的跳转（去出题），
 * 谁赢取决于跳转 API 的完成顺序 —— 表现是「点出题，进了详情页」。
 *
 * 所以这里把 `.li` 拆成两个**兄弟**热区：左半边（图标 + 文字）去详情，
 * 右半边（胶囊）去出题。一次点击只可能落在一个兄弟上，不需要任何冒泡控制。
 * 代价是图标与文字之间那条缝不可点 —— 那比一个「有时会走错页」的按钮好得多。
 *
 * ## 行尾胶囊三态
 *
 * | `ready_count` | `document_count` | 胶囊 | 点它 |
 * |---|---|---|---|
 * | > 0 | — | 「出题」（实心蓝） | 生成设置页 |
 * | 0 | > 0 | 「等待」 | 详情页（看是解析中还是全失败） |
 * | 0 | 0 | 「空库」 | 详情页（去上传） |
 *
 * 「还不能出题」的两种情形分开写，而不是都叫「等待」：一份文档都没有的库
 * 不会「等」出任何东西来，用户需要的是「去上传」而不是「再等等」。
 *
 * ## 概览卡里没有「已用 12.6 MB」
 *
 * 原型有这一格。后端没有按用户统计体积的接口（`GET /kb` 只给每个库的
 * 文档数与就绪数），前端自己把文档体积加起来会出现「列表说占了 12 MB、
 * 点进去只有 8 MB」这类不可解释的差异。**宁可不给这一格**，
 * 已登记进 `constants/copy.ts` 文件头第 5 条。
 *
 * ## 每次重新显示都刷新
 *
 * 从详情页回来时库的计数可能已经变了（传了文档 / 删了文档），
 * 从上传页回来时还可能多出一个库。只在挂载时取一次会让用户看到
 * 「刚传完文档，列表里还是 0 份」。做法与历史卷轴页一致：`useDidShow`
 * 里重取并跳过首次（挂载那次已由 `useAsyncData` 发起）。
 */

import { Text, View } from '@tarojs/components'
import { useDidShow } from '@tarojs/taro'
import { useRef } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import { ARCHIVE_COMMON, KB_LIST_COPY } from '../../../constants/copy'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { fetchBases } from '../../../services/kb'
import type { KbBaseItem } from '../../../types/api'
import { goPage } from '../../../utils/navigation'

import './index.scss'

/** 行尾胶囊：文案 + 修饰符 + 点它是「出题」还是「看详情」 */
function pillOf(item: KbBaseItem): { label: string; modifier: string; ask: boolean } {
  if (item.ready_count > 0) {
    // 实心蓝是「这是动作」的语法，与提醒条里的胶囊同一用法（见 base.scss）
    return { label: KB_LIST_COPY.ask, modifier: ' solid', ask: true }
  }
  if (item.document_count > 0) {
    return { label: KB_LIST_COPY.waiting, modifier: '', ask: false }
  }
  return { label: KB_LIST_COPY.blank, modifier: '', ask: false }
}

export default function KbListPage() {
  const { status, data, reload } = useAsyncData(fetchBases)

  const firstShowRef = useRef(true)
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false
      return
    }
    reload()
  })

  const openDetail = (kbId: string) => {
    goPage(`/pages/workshop/kb-detail/index?kb_id=${kbId}`, 'navigate')
  }

  const openGenerate = (kbId: string) => {
    goPage(`/pages/workshop/kb-generate/index?kb_id=${kbId}`, 'navigate')
  }

  const openUpload = () => {
    // 不带 kb_id：后端会落到默认库（design D16）。空态时用户还没见过任何库，
    // 让他先选一个库再上传是凭空加一步。
    goPage('/pages/workshop/kb-upload/index', 'navigate')
  }

  if (status === 'error') {
    return (
      <PhoneShell navTitle={KB_LIST_COPY.navTitle}>
        <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
      </PhoneShell>
    )
  }

  if (!data) {
    return (
      <PhoneShell navTitle={KB_LIST_COPY.navTitle}>
        <ArchiveState kind='loading' />
      </PhoneShell>
    )
  }

  if (data.items.length === 0) {
    return (
      <PhoneShell navTitle={KB_LIST_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={KB_LIST_COPY.emptyTitle}
          body={KB_LIST_COPY.emptyBody}
          actionText={KB_LIST_COPY.emptyCta}
          onAction={openUpload}
        />
      </PhoneShell>
    )
  }

  return (
    <PhoneShell navTitle={KB_LIST_COPY.navTitle}>
      <View className='card'>
        <View className='h sm'>{KB_LIST_COPY.summary(data.total)}</View>
      </View>

      {data.items.map((item) => {
        const pill = pillOf(item)
        return (
          <View className='li' key={item.id}>
            <View className='kb-list__tap' onClick={() => openDetail(item.id)}>
              <View className='ico'>{KB_LIST_COPY.icon}</View>
              <View className='tx'>
                <View className='n'>{item.name}</View>
                <View className='d'>
                  {KB_LIST_COPY.rowMeta(item.document_count, item.ready_count)}
                </View>
              </View>
            </View>

            <Text
              className={`pill${pill.modifier}`}
              onClick={() => (pill.ask ? openGenerate(item.id) : openDetail(item.id))}
            >
              {pill.label}
            </Text>
          </View>
        )
      })}

      <View className='spacer' />
    </PhoneShell>
  )
}
