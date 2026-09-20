/**
 * 历史卷轴（原型 04·5）。
 *
 * ## 一项 = 一次挑战，不是一份卷轴
 *
 * 方案 §5.5 定的粒度：`attempts` 的一行就是列表里的一行。同一份卷轴重做三次
 * 就有三条记录，由 `attempt_no` 标出这是第几次。原型那行副标题写「正确率 80%」
 * 而详情页带「重做」按钮，两件事合起来只有「一局」这个粒度说得通 ——
 * 如果一项是一份卷轴，那「这份卷轴的正确率」在重做过几次之后就没有唯一值了。
 *
 * ## 为什么这一页不用 `useAsyncData`
 *
 * 那个 hook 的语义是「重新加载 = 用新结果**替换**旧结果」，而翻页要的是
 * **追加**。硬套的话得在它外面再留一份累积数组，等于同一份数据两个来源，
 * 切换领域时两边很容易不同步。所以这里自己写一个二十来行的加载器，
 * 把「第 1 页是重来、之后是接上」这件事只表达一次。
 * 竞态（连续切换领域时旧请求后回来）用自增序号挡掉，与 `useAsyncData` 同一套做法。
 *
 * ## 切换领域时先清空，宁可闪一下
 *
 * 保留上一个领域的记录会让筛选条高亮着新领域、列表里却是旧领域的条目 ——
 * 读起来就是「这个领域有这些记录」，而那是错的。所以第 1 页加载前先清空。
 * 反过来，**翻页**失败时不清空：那时列表是正确的，只是这一次没取到下一页，
 * 提示一下即可。
 *
 * ## 时间是后端给的，不在这里重算
 *
 * 行里的「今天 14:20 / 昨天 21:05 / 9 月 11 日」直接用 `finished_label`。
 * 前端自己用 `formatDateRelative` 算会因为时区差异出现「列表写今天、
 * 详情写昨天」这种自相矛盾 —— 后端按业务时区（Asia/Shanghai）算，
 * 前端跟着走才是唯一口径。
 *
 * ## 删除是软删除，且错一次不算错
 *
 * 需求 FR-B5：删除只移除记录，**累计 XP / 正确率 / 等级一概不变**。
 * 所以删完只需要把这一条从本地列表拿掉，**不需要**重新拉个人中心或看板。
 *
 * 重复删除服务端返回 4005（它刻意不做成幂等，那样「删错了」就永远发现不了）。
 * 但站在用户角度，他的目标（这条别在了）已经达成 —— 所以调用方把 4005
 * 当作成功处理，而不是弹一个「删除失败」让他反复点。
 *
 * ## 删除入口只有长按（原型如此），且它依赖触摸事件
 *
 * 原型的注解是「长按可删除」，版面里没有第二个删除入口，所以这里照做。
 * 需要知道的是：Taro 在 H5 端把 `onLongPress` 实现成「`touchstart` 之后
 * 350ms 触发」（见 `@tarojs/components` 的 `view.js`），**只认触摸事件**。
 * 也就是说手机上的小程序与移动端 H5 都能长按，而**桌面浏览器用鼠标长按不会有反应**
 * —— 那里没有 `touchstart`。这是 H5 作为「非交付目标」的已知边界，
 * 不是产品缺陷：交付形态是小程序。若将来要在桌面 H5 上也能删，
 * 需要另加一个原型没有的显式入口，那属于产品决策。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import { ARCHIVE_COMMON, SCROLLS_COPY } from '../../../constants/copy'
import type { AsyncStatus } from '../../../hooks/useAsyncData'
import { deleteScroll, fetchScrolls } from '../../../services/archive'
import type { ScrollItem, ScrollListResponse } from '../../../types/api'
import { goPage, goTab } from '../../../utils/navigation'

import './index.scss'

/** 「资源不存在或无权访问」—— 删除时它意味着「这条已经不在了」 */
const CODE_RESOURCE_NOT_FOUND = 4005

/**
 * 删除确认按钮的颜色，= `$bad`（#A63A2E，朱砂）。**必须显式传**。
 *
 * Taro 的 `showModal` 默认 `confirmColor` 是一个绿色（#3CC51F），
 * 那既不在设计系统的色板里，语义上更是反的 —— 在这套「纸与印」的配色下，
 * 绿色一律读作「正确 / 通过」，而这里是**破坏性动作**，要让用户看清楚。
 * 前端拿不到 scss 变量，与 `AccuracyRing` 里的做法一样，在这里写十六进制
 * 并注明它对应哪个令牌。
 */
const DESTRUCTIVE_COLOR = '#a63a2e'

export default function ScrollsPage() {
  const [domain, setDomain] = useState('')
  const [items, setItems] = useState<ScrollItem[]>([])
  const [meta, setMeta] = useState<ScrollListResponse | null>(null)
  /** 只描述**第 1 页**的状态；翻页的状态在 `loadingMore` 里 */
  const [status, setStatus] = useState<AsyncStatus>('loading')
  const [loadingMore, setLoadingMore] = useState(false)
  /** 正在删除的那一条：既用于挡住重复点击，也让那一行变灰 */
  const [busyId, setBusyId] = useState<string | null>(null)

  /** 请求序号：只有序号等于当前值的响应才允许写入 state */
  const seqRef = useRef(0)
  /** 组件是否还挂着 */
  const aliveRef = useRef(true)
  /** 最新一次渲染时的领域，供 `useDidShow` 读取 */
  const domainRef = useRef(domain)
  domainRef.current = domain

  const load = useCallback((nextDomain: string, page: number) => {
    const seq = (seqRef.current += 1)

    if (page === 1) {
      // 见文件头：切换领域时先清空，避免「筛选条是新领域、列表是旧领域」
      setStatus('loading')
      setMeta(null)
      setItems([])
    } else {
      setLoadingMore(true)
    }

    fetchScrolls(nextDomain, page).then(
      (result) => {
        if (!aliveRef.current || seq !== seqRef.current) return
        setMeta(result)
        // 第 1 页是「重来」，其余是「接上」
        setItems((prev) => (page === 1 ? result.items : [...prev, ...result.items]))
        setStatus('ready')
        setLoadingMore(false)
      },
      () => {
        if (!aliveRef.current || seq !== seqRef.current) return
        setLoadingMore(false)
        if (page === 1) {
          setStatus('error')
          return
        }
        // 翻页失败不抹掉已经看到的记录，只说明这一次没取到
        Taro.showToast({ title: ARCHIVE_COMMON.loadFailed, icon: 'none' })
      }
    )
  }, [])

  useEffect(() => {
    aliveRef.current = true
    load(domain, 1)
    return () => {
      aliveRef.current = false
    }
  }, [domain, load])

  // 从详情页「重新挑战这一卷」回来时，那一局是一条**新的**记录，列表必须重来。
  // 首次（挂载）跳过 —— 那次请求已经由上面的 effect 发起了。
  const firstShowRef = useRef(true)
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false
      return
    }
    load(domainRef.current, 1)
  })

  /** 从列表里拿掉一条，并把总数减一 —— 页脚的「共 N 份」要跟着变 */
  const dropLocally = useCallback((attemptId: string) => {
    setItems((prev) => prev.filter((item) => item.attempt_id !== attemptId))
    setMeta((prev) => (prev ? { ...prev, total: Math.max(0, prev.total - 1) } : prev))
  }, [])

  const removeScroll = useCallback(
    async (attemptId: string) => {
      setBusyId(attemptId)
      try {
        await deleteScroll(attemptId)
        dropLocally(attemptId)
        Taro.showToast({ title: SCROLLS_COPY.deleted, icon: 'none' })
      } catch (error) {
        const code = (error as { code?: number } | null)?.code
        if (code === CODE_RESOURCE_NOT_FOUND) {
          // 它已经不在了 —— 用户的目标已达成，不弹失败让他反复点。
          // 本地同样拿掉，避免屏幕上留着一条服务端认为不存在的记录。
          dropLocally(attemptId)
          Taro.showToast({ title: SCROLLS_COPY.deleted, icon: 'none' })
        } else {
          Taro.showToast({ title: SCROLLS_COPY.deleteFailed, icon: 'none' })
        }
      } finally {
        setBusyId(null)
      }
    },
    [dropLocally]
  )

  const handleLongPress = useCallback(
    (item: ScrollItem) => {
      if (busyId) return
      Taro.showModal({
        title: SCROLLS_COPY.deleteTitle,
        // 用户对「删除」最大的顾虑是「成绩会不会一起没了」，
        // 所以这句必须把 FR-B5 的承诺说出来，而不是只问一句「确定吗」
        content: SCROLLS_COPY.deleteBody,
        confirmText: SCROLLS_COPY.deleteConfirm,
        cancelText: SCROLLS_COPY.deleteCancel,
        confirmColor: DESTRUCTIVE_COLOR,
        success: (res) => {
          if (res.confirm) void removeScroll(item.attempt_id)
        }
      })
    },
    [busyId, removeScroll]
  )

  if (!meta) {
    return (
      <PhoneShell navTitle={SCROLLS_COPY.navTitle}>
        {status === 'error' ? (
          <ArchiveState
            kind='error'
            actionText={ARCHIVE_COMMON.retry}
            onAction={() => load(domain, 1)}
          />
        ) : (
          <ArchiveState kind='loading' />
        )}
      </PhoneShell>
    )
  }

  // 一条都没有（且不在筛选中）→ 真正的空态。
  // 注意不能只看 `items.length === 0`：筛选出空结果时 items 也是空的，
  // 但那时用户需要看到筛选条以便切回去。
  if (meta.total === 0 && domain === '') {
    return (
      <PhoneShell navTitle={SCROLLS_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={SCROLLS_COPY.emptyTitle}
          body={SCROLLS_COPY.emptyBody}
          actionText={SCROLLS_COPY.emptyCta}
          onAction={() => goTab('/pages/hall/index')}
        />
      </PhoneShell>
    )
  }

  return (
    <PhoneShell navTitle={SCROLLS_COPY.navTitle}>
      {/* 领域筛选。`domains` 由服务端下发且**恒为全量**（不随当前筛选变化）——
          否则切到一个空结果后 chips 一起消失，用户就再也切不回去了。
          原型在这里的内联样式是 `gap:6px;flex-wrap:wrap`，落到 scss 里。 */}
      <View className='row scrolls__filters'>
        <Text
          className={`chip${domain === '' ? ' scrolls__filter--on' : ''}`}
          onClick={() => setDomain('')}
        >
          {SCROLLS_COPY.filterAll}
        </Text>

        {meta.domains.map((name) => (
          <Text
            key={name}
            className={`chip${domain === name ? ' scrolls__filter--on' : ''}`}
            onClick={() => setDomain(name)}
          >
            {name}
          </Text>
        ))}
      </View>

      {/* 每一行都是 `.screen` 的直接子元素：这样才吃到它的 `gap:10px`
          （原型就是这个结构）。外面套一层容器会把那 10px 吞掉。 */}
      {items.map((item) => (
        <View
          className={`li${busyId === item.attempt_id ? ' scrolls__row--busy' : ''}`}
          key={item.attempt_id}
          onClick={() =>
            goPage(`/pages/profile/scroll-detail/index?attempt_id=${item.attempt_id}`, 'navigate')
          }
          onLongPress={() => handleLongPress(item)}
        >
          <View className='ico'>{SCROLLS_COPY.icon}</View>

          <View className='tx'>
            <View className='n'>{item.title}</View>
            <View className='d'>{SCROLLS_COPY.rowMeta(item.finished_label, item.accuracy)}</View>
          </View>

          <Text className='pill'>{SCROLLS_COPY.questionPill(item.total_count)}</Text>
        </View>
      ))}

      {/* 筛选后一条都没有：这不是「还没有记录」，所以不说「完成一次挑战就有了」 */}
      {items.length === 0 ? (
        <View className='card parch scrolls__filter-empty'>
          <View className='h sm'>{SCROLLS_COPY.filterEmptyTitle}</View>
          <View className='sub scrolls__filter-empty-body'>{SCROLLS_COPY.filterEmptyBody}</View>
        </View>
      ) : null}

      <View className='spacer' />

      {/* 还有下一页时**不能**说「已经到底了」—— 那是在骗用户 */}
      {meta.has_more ? (
        <Button
          className={`btn ghost${loadingMore ? ' dis' : ''}`}
          disabled={loadingMore}
          onClick={() => load(domain, meta.page + 1)}
        >
          {loadingMore ? SCROLLS_COPY.loadingMore : SCROLLS_COPY.loadMore}
        </Button>
      ) : (
        <View className='tiny scrolls__footer'>{SCROLLS_COPY.footer(meta.total)}</View>
      )}
    </PhoneShell>
  )
}
