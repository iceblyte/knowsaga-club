/**
 * 知识库详情（原型 05·7）。
 *
 * ## 一页承担三件事，因为它们都需要「当前这个库」的完整快照
 *
 * 1. 看这个库是什么（名字、就绪状态、文档数、用途描述）；
 * 2. 管里面的文档（列表、状态、长按删除、去上传）；
 * 3. 从这个库出题（页脚那颗主按钮）。
 *
 * 三件事共用 `GET /kb/{kb_id}` 一次请求，所以不拆页。原型的「出题范围」
 * （全部文档 / 仅第 1-4 章 / 自定义）**整块不渲染** —— 它要保留文档的标题
 * 层级结构，而本期的分块是无结构的滑窗（design 的 Non-Goals），
 * 画一组点不动的 chip 比不画糟。
 *
 * ## 改名用页内输入态，不用弹窗
 *
 * Taro 这一版的 `showModal` **没有 `editable`**（只有 `content` + 两个按钮），
 * 弹不出一个能打字的输入框。所以「重命名」把头部那张卡切成编辑态：
 * 一个输入框 + 取消 / 保存。比引一个底部弹层组件轻，而且用户的视线不用离开
 * 那个名字（他正在改的就是它）。
 *
 * 提交前先做**能本地判定**的两件事：名字没变就不发请求（否则必然拿到一个
 * 4000）、长度不合规也不发（后端 `KB_NAME_MIN_LEN=2` / `KB_NAME_UI_MAX_LEN=40`）。
 * 重名是唯一必须问后端的（4001），所以那一条按码分支。
 *
 * ## 删除接在**长按**上，与历史卷轴页同一条路
 *
 * 原型 05·7 没有画删除入口。这里照 04·5（历史卷轴）已确立的写法：
 * 长按文档行 → 确认弹窗 → 删。Taro 在 H5 端把 `onLongPress` 实现成
 * 「`touchstart` 后 350ms」，只认触摸事件 —— 桌面浏览器用鼠标长按不会有反应。
 * 这是 H5 作为非交付目标的已知边界（小程序与移动端 H5 都正常），
 * 不是缺陷；页面上给了一行「长按文档可以删除」把可发现性补上。
 */

import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import ArchiveState from '../../../components/ArchiveState'
import PhoneShell from '../../../components/PhoneShell'
import {
  ARCHIVE_COMMON,
  KB_COMMON,
  KB_DETAIL_COPY,
  KB_PARSING_COPY,
  KB_STATUS_LABEL,
  kbStatusPill
} from '../../../constants/copy'
import { ERROR_CODE } from '../../../constants/api'
import { useAsyncData } from '../../../hooks/useAsyncData'
import { deleteBase, deleteDocument, fetchBaseDetail, updateBase } from '../../../services/kb'
import type { KbDocumentItem } from '../../../types/api'
import { formatBytes } from '../../../utils/cache'
import { goPage } from '../../../utils/navigation'

import './index.scss'

/**
 * 删除确认按钮的颜色，= `$bad`（#A63A2E，朱砂）。**必须显式传**。
 *
 * Taro 的 `showModal` 默认 `confirmColor` 是一个绿色，那既不在色板里，
 * 语义上更是反的（这套配色里绿色一律读作「正确 / 通过」）。
 * 前端拿不到 scss 变量，与历史卷轴页一样在这里写十六进制并注明对应令牌。
 */
const DESTRUCTIVE_COLOR = '#a63a2e'

/** 扩展名 → 行首方块里的标签（原型写的就是这三个大写字母） */
const EXT_LABEL: Record<string, string> = {
  pdf: 'PDF',
  docx: 'DOC',
  md: 'MD',
  txt: 'TXT'
}

function extLabelOf(doc: KbDocumentItem): string {
  return EXT_LABEL[doc.ext] ?? doc.ext.toUpperCase()
}

export default function KbDetailPage() {
  const router = useRouter<{ kb_id: string }>()
  const kbId = (router.params?.kb_id ?? '').trim()

  const { status, data, error, reload } = useAsyncData(
    () => fetchBaseDetail(kbId),
    kbId || '__missing__'
  )

  /** 改名：编辑态 / 草稿 / 提交中。`editing` 为假时输入框整块不渲染 */
  const [editing, setEditing] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [savingName, setSavingName] = useState(false)
  /** 正在删除的那一条文档（挡住重复点击 + 让那一行变灰） */
  const [busyDocId, setBusyDocId] = useState<string | null>(null)
  const [deletingBase, setDeletingBase] = useState(false)

  /** 组件是否还挂着：改名 / 删除的响应回来时可能已经离开这一页 */
  const aliveRef = useRef(true)
  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  const notFound = !kbId || (error as { code?: number } | null)?.code === ERROR_CODE.RESOURCE_NOT_FOUND

  const startRename = useCallback(() => {
    if (!data) return
    setNameDraft(data.base.name)
    setEditing(true)
  }, [data])

  const submitRename = useCallback(async () => {
    if (!data) return
    const next = nameDraft.trim()
    if (next === data.base.name) {
      Taro.showToast({ title: KB_DETAIL_COPY.renameSame, icon: 'none' })
      return
    }
    if (next.length < KB_COMMON.nameMin) {
      Taro.showToast({ title: KB_DETAIL_COPY.renameTooShort(KB_COMMON.nameMin), icon: 'none' })
      return
    }
    if (next.length > KB_COMMON.nameMax) {
      Taro.showToast({ title: KB_DETAIL_COPY.renameTooLong(KB_COMMON.nameMax), icon: 'none' })
      return
    }

    setSavingName(true)
    try {
      await updateBase(kbId, { name: next })
      if (!aliveRef.current) return
      Taro.showToast({ title: KB_DETAIL_COPY.renameDone, icon: 'none' })
      setEditing(false)
      reload()
    } catch (reason) {
      if (!aliveRef.current) return
      const code = (reason as { code?: number } | null)?.code
      Taro.showToast({
        title: code === ERROR_CODE.INVALID_INPUT ? KB_DETAIL_COPY.renameConflict : KB_DETAIL_COPY.renameFailed,
        icon: 'none'
      })
    } finally {
      if (aliveRef.current) setSavingName(false)
    }
  }, [data, kbId, nameDraft, reload])

  const removeDocument = useCallback(
    async (docId: string) => {
      setBusyDocId(docId)
      try {
        await deleteDocument(docId)
        if (!aliveRef.current) return
        Taro.showToast({ title: KB_DETAIL_COPY.deleteDocDone, icon: 'none' })
        // 文档数、知识块数、就绪数都会变 —— 重新拉一次比在本地减一更可靠
        reload()
      } catch (reason) {
        if (!aliveRef.current) return
        const code = (reason as { code?: number } | null)?.code
        if (code === ERROR_CODE.RESOURCE_NOT_FOUND) {
          // 它已经不在了：用户的目标已达成，不弹失败让他反复点
          Taro.showToast({ title: KB_DETAIL_COPY.deleteDocDone, icon: 'none' })
          reload()
        } else {
          Taro.showToast({ title: KB_DETAIL_COPY.deleteDocFailed, icon: 'none' })
        }
      } finally {
        if (aliveRef.current) setBusyDocId(null)
      }
    },
    [reload]
  )

  const confirmRemoveDocument = useCallback(
    (doc: KbDocumentItem) => {
      if (busyDocId) return
      Taro.showModal({
        title: KB_DETAIL_COPY.deleteDocTitle,
        content: KB_DETAIL_COPY.deleteDocBody,
        confirmText: KB_DETAIL_COPY.deleteDocConfirm,
        cancelText: KB_DETAIL_COPY.deleteDocCancel,
        confirmColor: DESTRUCTIVE_COLOR,
        success: (res) => {
          if (res.confirm) void removeDocument(doc.id)
        }
      })
    },
    [busyDocId, removeDocument]
  )

  const removeBase = useCallback(() => {
    if (deletingBase) return
    Taro.showModal({
      title: KB_DETAIL_COPY.deleteBaseTitle,
      content: KB_DETAIL_COPY.deleteBaseBody,
      confirmText: KB_DETAIL_COPY.deleteDocConfirm,
      cancelText: KB_DETAIL_COPY.deleteDocCancel,
      confirmColor: DESTRUCTIVE_COLOR,
      success: async (res) => {
        if (!res.confirm) return
        setDeletingBase(true)
        try {
          await deleteBase(kbId)
        } catch (reason) {
          // 4005 意味着它已经不在了 —— 那正是用户要的结果，不回退
          if ((reason as { code?: number } | null)?.code !== ERROR_CODE.RESOURCE_NOT_FOUND) {
            Taro.showToast({ title: KB_DETAIL_COPY.deleteDocFailed, icon: 'none' })
            setDeletingBase(false)
            return
          }
        }
        // 库没了，这一页就没有内容 —— 退回列表（用 navigateBack 会更省事，
        // 但上一页可能是「我的」，那就会回到一个与知识库无关的地方）
        goPage('/pages/workshop/kb-list/index', 'redirect')
      }
    })
  }, [deletingBase, kbId])

  if (notFound) {
    return (
      <PhoneShell navTitle={KB_DETAIL_COPY.docsLabel}>
        <ArchiveState
          kind='empty'
          title={KB_COMMON.notFound}
          body='它可能已经被删除，或者不属于当前账号。'
          actionText='回到知识库'
          onAction={() => goPage('/pages/workshop/kb-list/index', 'redirect')}
        />
      </PhoneShell>
    )
  }

  if (status === 'error') {
    return (
      <PhoneShell navTitle='知识库'>
        <ArchiveState kind='error' actionText={ARCHIVE_COMMON.retry} onAction={reload} />
      </PhoneShell>
    )
  }

  if (!data) {
    return (
      <PhoneShell navTitle='知识库'>
        <ArchiveState kind='loading' />
      </PhoneShell>
    )
  }

  const { base, documents } = data
  const chunkTotal = documents.reduce((sum, doc) => sum + doc.chunk_count, 0)
  const canAsk = base.ready_count > 0

  return (
    <PhoneShell navTitle={base.name}>
      {/* ---- 这个库是什么 ---- */}
      <View className='card'>
        <View className='between'>
          <Text className={`pill${base.ready_count > 0 ? ' ok' : ''}`}>
            {base.ready_count > 0 ? KB_DETAIL_COPY.readyPill : KB_DETAIL_COPY.pendingPill}
          </Text>
          {!editing ? (
            <Text className='tiny' onClick={startRename}>
              {KB_DETAIL_COPY.renameAction}
            </Text>
          ) : null}
        </View>

        {editing ? (
          <>
            <View className='tiny kb-detail__head'>{KB_DETAIL_COPY.renameLabel}</View>
            <Input
              className='kb-detail__input'
              type='text'
              value={nameDraft}
              maxlength={KB_COMMON.nameMax}
              placeholder={KB_DETAIL_COPY.renamePlaceholder}
              onInput={(event) => setNameDraft(event.detail.value)}
            />
            <View className='row kb-detail__rename-hint'>
              <Text className='tiny'>
                {KB_DETAIL_COPY.renameHint(KB_COMMON.nameMin, KB_COMMON.nameMax)}
              </Text>
            </View>
            <View className='row kb-detail__rename-row'>
              <Button
                className={`btn sm${savingName ? ' dis' : ''}`}
                disabled={savingName}
                onClick={() => void submitRename()}
              >
                {KB_DETAIL_COPY.renameSave}
              </Button>
              <Button
                className='btn sm ghost'
                disabled={savingName}
                onClick={() => setEditing(false)}
              >
                {KB_DETAIL_COPY.renameCancel}
              </Button>
            </View>
          </>
        ) : (
          <>
            <View className='h kb-detail__head'>
              {KB_DETAIL_COPY.summary(base.document_count, chunkTotal)}
            </View>
            <View className='sub kb-detail__desc'>
              {base.description || KB_DETAIL_COPY.descriptionEmpty}
            </View>
          </>
        )}
      </View>

      {/* ---- 里面的文档 ---- */}
      <View className='card'>
        <View className='between'>
          <View className='tiny'>{KB_DETAIL_COPY.docsLabel}</View>
          {documents.length > 0 ? (
            <View className='tiny'>{KB_DETAIL_COPY.docActionHint}</View>
          ) : null}
        </View>

        {documents.length === 0 ? (
          <View className='sub kb-detail__desc'>{KB_DETAIL_COPY.docsEmpty}</View>
        ) : (
          documents.map((doc) => (
            <View
              className={`li${busyDocId === doc.id ? ' kb-detail__row--busy' : ''}`}
              key={doc.id}
              onClick={() => goPage(`/pages/workshop/kb-parsing/index?kb_id=${base.id}&doc_id=${doc.id}`, 'navigate')}
              onLongPress={() => confirmRemoveDocument(doc)}
            >
              <View className='ico'>
                <Text className='kb-detail__ext'>{extLabelOf(doc)}</Text>
              </View>

              <View className='tx'>
                <View className='n'>{doc.filename}</View>
                {doc.status === 'failed' ? (
                  // 失败行给的是**原因**（后端下发的一句话），不是「解析失败」
                  // 这四个字 —— 用户要拿它判断「改文件重传」还是「换个文件」
                  <View className='d kb-detail__row-error'>
                    {KB_DETAIL_COPY.docFailedPrefix}
                    {doc.error_message || KB_PARSING_COPY.failedFallback}
                  </View>
                ) : (
                  <View className='d'>
                    {KB_DETAIL_COPY.docMeta(doc.page_count, doc.chunk_count)} ·{' '}
                    {formatBytes(doc.size_bytes)}
                  </View>
                )}
              </View>

              <Text className={`pill${kbStatusPill(doc.status) ? ` ${kbStatusPill(doc.status)}` : ''}`}>
                {KB_STATUS_LABEL[doc.status]}
              </Text>
            </View>
          ))
        )}
      </View>

      <Button
        className='btn ghost'
        onClick={() => goPage(`/pages/workshop/kb-upload/index?kb_id=${base.id}`, 'navigate')}
      >
        {KB_DETAIL_COPY.uploadAction}
      </Button>

      <View className='spacer' />

      {/* 出题：库还没就绪时置灰并说明原因（原型 05·5 的批注，design D17 定的是
          「拦在前端」——后端不拦，因为「库是空的」这件事一次查询就能知道，
          让用户等几秒才被告知要比现在就告诉他差得多）。 */}
      <Button
        className={`btn${canAsk ? '' : ' dis'}`}
        disabled={!canAsk}
        onClick={() => goPage(`/pages/workshop/kb-generate/index?kb_id=${base.id}`, 'navigate')}
      >
        {KB_DETAIL_COPY.askAction}
      </Button>
      {!canAsk ? (
        <View className='tiny kb-detail__hint'>{KB_DETAIL_COPY.askBlockedHint}</View>
      ) : null}

      <View className='tiny kb-detail__danger' onClick={removeBase}>
        {KB_DETAIL_COPY.deleteBaseAction}
      </View>
    </PhoneShell>
  )
}
