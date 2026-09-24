/**
 * 文档解析中（原型 05·3）。
 *
 * ## 这一页是**文档的状态页**，不只是「解析中」那一小段
 *
 * 四态各有一副面孔：解析中 / 已就绪 / 解析失败 / 已经不在了。
 * 之所以四态都收在这一页，是因为它们的**数据来源是同一个**
 * （`GET /kb/{kb_id}` 里那一份文档），而用户在四个状态下的下一个动作
 * 也都在这一页能给出（等 / 去出题 / 重试 / 回列表）。
 *
 * ## 轮询：驱动它的是「上一次的结果」，不是 `setInterval`
 *
 * 判据只有一条 —— **只要这份文档还没到终态就再问一次**。所以轮询的节拍
 * 挂在「`polls` 计数 + 状态是否终态」上（见下面那个 effect）：
 * 每次响应回来都会让 `polls` 加一，effect 因此重跑并排下一个定时器；
 * 状态变成 `ready` / `failed` 后 `shouldPoll` 为假，定时器不再排。
 *
 * 用 `setInterval` 的话有三件事要自己管：切走页面时停、请求比间隔慢时
 * 堆积、以及终态后还要手动清。挂在 effect 上，这三件事都是**布局自带的**。
 *
 * ## 间隔由后端给，但这一页拿不到信封
 *
 * `POST /kb/documents` 与 reparse 的响应里有 `poll_interval_ms`（后端配置），
 * 而 `GET /kb/{kb_id}` 没有。所以上传页跳过来时把那个值**带在 URL 里**，
 * 本页优先用它；从详情页点进来（没有那个值）时退回兜底间隔。
 * 两条路的差别只在快慢，不影响正确性 —— 终态永远只由这一页的响应决定。
 *
 * ## 停止追问 ≠ 判失败
 *
 * 解析是耗时操作（20 MB 的 PDF 可能好几分钟），所以给轮询设了一条时限。
 * 到了时限**不把页面判成失败**，而是换成「还在进行，可以回头再看」
 * 加一个手动刷新 —— 后台可能下一秒就成功，说「失败」是冤枉它。
 * 真正失败是后端给的（`status === 'failed'` + `error_message`）。
 *
 * ## 一连串请求都失败才会翻脸
 *
 * 单次网络抖动不该让整页变成错误页：解析还在后台跑。连续失败到阈值之后
 * 才显示错误态（可重试）；从没成功过一次时更早翻脸 —— 那时用户连这份文档
 * 都还没看到，让他对着一个空转的圈等毫无意义。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import MagicStage from '../../../components/MagicStage'
import PhoneShell from '../../../components/PhoneShell'
import { ERROR_CODE, FALLBACK_POLL_INTERVAL_MS } from '../../../constants/api'
import { ARCHIVE_COMMON, KB_PARSING_COPY } from '../../../constants/copy'
import { fetchBaseDetail, reparseDocument } from '../../../services/kb'
import type { KbDocumentItem } from '../../../types/api'
import { formatBytes } from '../../../utils/cache'
import { goPage } from '../../../utils/navigation'

import './index.scss'

/**
 * 轮询总时长上限（3 分钟）。
 *
 * 比出题那一套的 `POLL_DEADLINE_MS`（100s）宽得多：解析一份几十页的 PDF
 * 本来就慢，用出题那条线会在正常路径上误停。到点只是**停止追问**，
 * 不判失败（见文件头）。
 */
const PARSE_POLL_DEADLINE_MS = 180000

/** 连续失败到几次才翻成错误页 */
const MAX_POLL_FAILURES = 3

/** 终态：到了就不用再问 */
function isTerminal(doc: KbDocumentItem | null): boolean {
  return doc !== null && (doc.status === 'ready' || doc.status === 'failed')
}

export default function KbParsingPage() {
  const router = useRouter<{ kb_id: string; doc_id: string; interval: string }>()
  const kbId = (router.params?.kb_id ?? '').trim()
  const docId = (router.params?.doc_id ?? '').trim()

  /** 页面的加载态。`ready` 之后由 `doc` 自己的状态决定画什么 */
  const [page, setPage] = useState<'loading' | 'ready' | 'error'>('loading')
  const [doc, setDoc] = useState<KbDocumentItem | null>(null)
  /** 这份文档已经不在了（被删 / 越权 / 库没了） */
  const [gone, setGone] = useState(false)
  /** 轮询到达时限（不是失败，见文件头） */
  const [timedOut, setTimedOut] = useState(false)
  const [retrying, setRetrying] = useState(false)
  /** 每完成一次请求加一 —— 它唯一的作用是让轮询的 effect 重跑 */
  const [polls, setPolls] = useState(0)
  /** 页面是否可见：切走时停表，回来时接着问 */
  const [visible, setVisible] = useState(true)

  const aliveRef = useRef(true)
  /** 连续失败次数 */
  const failuresRef = useRef(0)
  /** 至少成功过一次 —— 没成功过时更早显示错误页 */
  const seenRef = useRef(false)
  /** 轮询时限的绝对时刻；0 表示还没开始计时 */
  const deadlineRef = useRef(0)
  /** 当前生效的轮询间隔（URL 给的值优先，见文件头） */
  const intervalRef = useRef(
    Number.parseInt(router.params?.interval ?? '', 10) > 0
      ? Number.parseInt(router.params.interval, 10)
      : FALLBACK_POLL_INTERVAL_MS
  )

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  useDidShow(() => setVisible(true))
  useDidHide(() => setVisible(false))

  const load = useCallback(async () => {
    try {
      const result = await fetchBaseDetail(kbId)
      if (!aliveRef.current) return
      failuresRef.current = 0
      seenRef.current = true
      const found = result.documents.find((item) => item.id === docId) ?? null
      if (!found) {
        // 库还在、文档没了 —— 与「库都没了」同样处理：给出口，不停在转圈上
        setGone(true)
      }
      setDoc(found)
      setPage('ready')
    } catch (reason) {
      if (!aliveRef.current) return
      if ((reason as { code?: number } | null)?.code === ERROR_CODE.RESOURCE_NOT_FOUND) {
        setGone(true)
        setPage('ready')
        return
      }
      failuresRef.current += 1
      if (failuresRef.current >= MAX_POLL_FAILURES || !seenRef.current) {
        setPage('error')
      }
    } finally {
      if (aliveRef.current) setPolls((count) => count + 1)
    }
  }, [docId, kbId])

  /**
   * 进页先立刻问一次。
   *
   * ⚠️ 这一行不能省，否则整页**死锁**：轮询的节拍挂在 `shouldPoll` 上，
   * 而它要求 `page === 'ready'`；`page` 只有 `load()` 自己会写成 `'ready'`。
   * 少了这第一次调用，就没有任何东西能触发第一次请求 ——
   * 页面永远停在初始的 `loading` 态（表现为「正在翻开档案…」一直转），
   * 界面上看不出任何异常，只有数后端请求数才发现一次都没发。
   * 浏览器实测踩过：`tsc` 与双端构建全绿，HTTP 层零请求。
   */
  useEffect(() => {
    void load()
  }, [load])

  /** 还需要继续问吗。终态 / 已消失 / 时限到了 / 已经翻成错误页时都不再问 */
  const shouldPoll = page === 'ready' && !gone && !timedOut && !isTerminal(doc)

  useEffect(() => {
    if (!shouldPoll || !visible) return
    if (deadlineRef.current === 0) deadlineRef.current = Date.now() + PARSE_POLL_DEADLINE_MS
    if (Date.now() >= deadlineRef.current) {
      setTimedOut(true)
      return
    }
    const timer = setTimeout(() => {
      void load()
    }, intervalRef.current)
    return () => clearTimeout(timer)
  }, [shouldPoll, visible, polls, load])

  const restart = useCallback(() => {
    failuresRef.current = 0
    deadlineRef.current = 0
    setTimedOut(false)
    setPage('loading')
    void load()
  }, [load])

  const handleReparse = useCallback(async () => {
    if (retrying) return
    setRetrying(true)
    try {
      const result = await reparseDocument(docId)
      if (!aliveRef.current) return
      // 重试的响应里带着后端给的轮询间隔，用它（比 URL 上那个更新）
      if (result.poll_interval_ms > 0) intervalRef.current = result.poll_interval_ms
      failuresRef.current = 0
      deadlineRef.current = 0
      setTimedOut(false)
      // 服务端已经把它写成 `parsing` 了（design D19），所以界面马上有反应
      setDoc(result.document)
      setPage('ready')
      setPolls((count) => count + 1)
    } catch {
      // 不把整页判成失败：文档还在，只是这一次重试没发出去。
      // 弹一句提示，用户再点一次即可 —— 按钮没有进入任何不可恢复的状态。
      if (aliveRef.current) {
        Taro.showToast({ title: KB_PARSING_COPY.retryFailed, icon: 'none' })
      }
    } finally {
      if (aliveRef.current) setRetrying(false)
    }
  }, [docId, retrying])

  // ---- 四态之前的三种「整页」状态 ----

  if (!kbId || !docId || gone) {
    return (
      <PhoneShell navTitle={KB_PARSING_COPY.navTitle}>
        <ArchiveState
          kind='empty'
          title={KB_PARSING_COPY.goneTitle}
          body={KB_PARSING_COPY.goneBody}
          actionText={KB_PARSING_COPY.goneCta}
          onAction={() => goPage('/pages/workshop/kb-list/index', 'redirect')}
        />
      </PhoneShell>
    )
  }

  if (page === 'loading' && !doc) {
    return (
      <PhoneShell navTitle={KB_PARSING_COPY.navTitle}>
        <ArchiveState kind='loading' />
      </PhoneShell>
    )
  }

  if (page === 'error') {
    return (
      <PhoneShell navTitle={KB_PARSING_COPY.navTitle}>
        <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={restart} />
      </PhoneShell>
    )
  }

  if (!doc) {
    // 理论上到不了（`page === 'ready'` 时必有 doc 或 gone），兜住不让它崩
    return (
      <PhoneShell navTitle={KB_PARSING_COPY.navTitle}>
        <ArchiveState kind='loading' />
      </PhoneShell>
    )
  }

  // ---- 已就绪 ----
  if (doc.status === 'ready') {
    return (
      <PhoneShell navTitle={KB_PARSING_COPY.navReady}>
        <View className='card'>
          <View className='kb-parsing__hero'>
            <MagicStage size={140} spriteSize={58} sprite='momo' still />
            <Text className='kb-parsing__title'>{KB_PARSING_COPY.readyTitle}</Text>
            <Text className='sub kb-parsing__file'>{doc.filename}</Text>
            <Text className='tiny'>{KB_PARSING_COPY.readyBlocks(doc.chunk_count)}</Text>
          </View>
        </View>

        <View className='body sm'>{KB_PARSING_COPY.readyBody}</View>

        <View className='spacer' />

        <Button
          className='btn'
          onClick={() => goPage(`/pages/workshop/kb-generate/index?kb_id=${kbId}`, 'navigate')}
        >
          {KB_PARSING_COPY.readyCta}
        </Button>
      </PhoneShell>
    )
  }

  // ---- 解析失败 ----
  if (doc.status === 'failed') {
    return (
      <PhoneShell navTitle={KB_PARSING_COPY.navFailed}>
        <View className='card bad'>
          <View className='kb-parsing__hero'>
            <MagicStage size={140} spriteSize={58} sprite='tongbao' still />
            <Text className='kb-parsing__title'>{KB_PARSING_COPY.failedTitle}</Text>
            <Text className='sub kb-parsing__file'>{doc.filename}</Text>
          </View>
          {/* 失败时给的是**原因** —— 那是用户能拿来判断怎么办的唯一线索 */}
          <View className='body sm kb-parsing__reason'>
            {doc.error_message || KB_PARSING_COPY.failedFallback}
          </View>
        </View>

        <View className='body sm'>{KB_PARSING_COPY.failedHint}</View>

        <View className='spacer' />

        <Button
          className={`btn${retrying ? ' dis' : ''}`}
          disabled={retrying}
          onClick={() => void handleReparse()}
        >
          {retrying ? KB_PARSING_COPY.retrying : KB_PARSING_COPY.retry}
        </Button>
      </PhoneShell>
    )
  }

  // ---- 解析中 / 等待中 ----
  return (
    <PhoneShell navTitle={KB_PARSING_COPY.navTitle}>
      <View className='card'>
        <View className='kb-parsing__hero'>
          <MagicStage size={140} spriteSize={58} sprite='momo' />
          <Text className='kb-parsing__title'>{KB_PARSING_COPY.title}</Text>
          <Text className='sub kb-parsing__file'>
            {doc.filename}
            {doc.size_bytes > 0 ? ` · ${formatBytes(doc.size_bytes)}` : ''}
          </Text>
        </View>

        <View className='rule' />

        <View className='tiny'>{KB_PARSING_COPY.stepsLabel}</View>
        <View className='kb-parsing__steps'>
          {KB_PARSING_COPY.steps.map((step) => (
            <View className='kb-parsing__step' key={step}>
              <View className='dotmark' />
              <Text className='kb-parsing__step-text'>{step}</Text>
            </View>
          ))}
        </View>
      </View>

      <View className='tiny kb-parsing__hint'>
        {timedOut ? KB_PARSING_COPY.stillRunning : KB_PARSING_COPY.pollingHint}
      </View>

      <View className='spacer' />

      {/* 只有停表之后才给手动刷新 —— 正常轮询时给它是多余的按钮 */}
      {timedOut ? (
        <Button className='btn ghost' onClick={restart}>
          {KB_PARSING_COPY.refresh}
        </Button>
      ) : null}
    </PhoneShell>
  )
}
