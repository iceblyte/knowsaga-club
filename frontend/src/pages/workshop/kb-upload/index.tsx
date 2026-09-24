/**
 * 上传文档（原型 05·2）。
 *
 * ## 这一页是**两个入口共用**的，所以它自己判有没有库上下文
 *
 * | 从哪来 | 带 `kb_id`？ | 「最近上传」那一块 |
 * |---|---|---|
 * | 知识库详情页的「上传文档」 | 带 | 显示该库最新的三份 |
 * | 大厅的「上传文档」chip / 列表页空态 | 不带 | **整块不渲染** |
 *
 * 不带库 id 时后端会 `get_or_create_default_base()`（design D16），
 * 也就是落到一个按名字「查找或创建」的默认库。这时前端**没有任何办法**
 * 知道「最近上传」是哪些 —— `GET /kb` 只给每个库的计数，不给文档。
 * 与其凭库名猜一个、或者干脆显示「我的知识库」里全部文档（那可能是一百份），
 * 不如这一块不出现。已登记进 `constants/copy.ts` 文件头第 5 条。
 *
 * ## 本地预检拦的是「明显不合规」，不是「不合规」
 *
 * 格式与体积在**发请求之前**判一遍：20 MB 传上去要几十秒，让用户等完再收到
 * 一个 4002 是最差的一种失败。但前端拦不住「改名成 .pdf 的可执行文件」——
 * 那是后端的事（`loaders.py` 的扩展名准入 + 解析器自己对内容的验证）。
 * 拿不到体积时（`size === 0`）一律放行，猜一个数字拦住用户比放过去更糟。
 *
 * ## 上传成功后**不在这里等解析**
 *
 * `POST /kb/documents` 立刻返回，而响应里的 `status` 是**调用前的快照**
 * （通常是 `pending`，见 design D19）。所以这里不读那个字段，直接带着
 * 返回的 `kb_id` / `document.id` 去解析页 —— 终态只能由那一页轮询得到。
 *
 * ## objectURL 必须释放
 *
 * H5 分支下选中文件得到的是 `blob:` URL（`document-picker` 里建的）。
 * 传完（或换一个文件时）要 `releaseDocument()`，否则每选一次就漏一份
 * 文件内容的内存。小程序端是空操作。
 */

import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import PhoneShell from '../../../components/PhoneShell'
import { ERROR_CODE } from '../../../constants/api'
import { KB_STATUS_LABEL, KB_UPLOAD_COPY } from '../../../constants/copy'
import { fetchBaseDetail, uploadDocument } from '../../../services/kb'
import type { KbDocumentItem } from '../../../types/api'
import { formatBytes } from '../../../utils/cache'
import {
  DOCUMENT_MAX_LABEL,
  extOf,
  isSupportedDocument,
  isTooLarge,
  pickDocument,
  releaseDocument,
  type PickedDocument
} from '../../../utils/document-picker'
import { goPage } from '../../../utils/navigation'

import './index.scss'

/** 「最近上传」显示几份。原型排了两行，取 3 是「一屏放得下且不必滚动」 */
const RECENT_LIMIT = 3

const EXT_LABEL: Record<string, string> = {
  pdf: 'PDF',
  docx: 'DOC',
  md: 'MD',
  txt: 'TXT'
}

export default function KbUploadPage() {
  const router = useRouter<{ kb_id: string }>()
  const kbId = (router.params?.kb_id ?? '').trim()

  const [picked, setPicked] = useState<PickedDocument | null>(null)
  const [uploading, setUploading] = useState(false)
  /** 这个库里最新的几份文档（只有带了 `kb_id` 时才有） */
  const [recent, setRecent] = useState<KbDocumentItem[]>([])

  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
      // 组件卸载时释放可能还挂着的 objectURL
      releaseDocument(pickedRef.current)
    }
  }, [])

  /** 卸载时要读「最新」的那个 picked —— 用 ref 镜像，避免把 effect 变成每渲染重跑 */
  const pickedRef = useRef<PickedDocument | null>(null)
  pickedRef.current = picked

  useEffect(() => {
    if (!kbId) return
    let alive = true
    fetchBaseDetail(kbId).then(
      (result) => {
        if (!alive) return
        // 后端按上传先后（id 升序）给，所以**最后**几份才是最近的
        setRecent(result.documents.slice(-RECENT_LIMIT).reverse())
      },
      () => {
        // 「最近上传」是这一页的**附加信息**，读不到就整块不出现。
        // 不弹提示、不打断上传 —— 用户来这一页是为了传文件。
        if (alive) setRecent([])
      }
    )
    return () => {
      alive = false
    }
  }, [kbId])

  const handlePick = async () => {
    let next: PickedDocument | null
    try {
      next = await pickDocument()
    } catch {
      Taro.showToast({ title: KB_UPLOAD_COPY.pickFailed, icon: 'none' })
      return
    }
    // 取消：什么都不说。取消是正常操作，弹个提示反而像出了错
    if (!next) return

    if (!isSupportedDocument(next.name)) {
      releaseDocument(next)
      Taro.showToast({ title: KB_UPLOAD_COPY.unsupported, icon: 'none' })
      return
    }
    if (isTooLarge(next.size)) {
      releaseDocument(next)
      Taro.showToast({ title: KB_UPLOAD_COPY.tooLarge(DOCUMENT_MAX_LABEL), icon: 'none' })
      return
    }

    // 换一个文件时先放掉上一个的 objectURL
    releaseDocument(picked)
    setPicked(next)
  }

  const handleSubmit = async () => {
    if (!picked || uploading) return
    setUploading(true)
    try {
      const result = await uploadDocument({
        filePath: picked.path,
        filename: picked.name,
        kbId: kbId || undefined
      })
      releaseDocument(picked)
      setPicked(null)
      if (!aliveRef.current) return
      // 用返回的 kb_id（不带 kb_id 进来时，这里才知道落到了哪个库）
      goPage(
        `/pages/workshop/kb-parsing/index?kb_id=${result.document.kb_id}&doc_id=${result.document.id}`,
        'navigate'
      )
    } catch (reason) {
      if (!aliveRef.current) return
      const error = reason as { code?: number; message?: string } | null
      // 4002 的文案是**为文档写的**（不是头像那一句），直接展示后端的话，
      // 不要自己拼一句「文件不合规」把它盖掉
      const title =
        error?.code === ERROR_CODE.UPLOAD_INVALID && error.message
          ? error.message
          : KB_UPLOAD_COPY.uploadFailed
      Taro.showToast({ title, icon: 'none' })
    } finally {
      if (aliveRef.current) setUploading(false)
    }
  }

  return (
    <PhoneShell navTitle={KB_UPLOAD_COPY.navTitle}>
      {/* ---- 投放区 ---- */}
      <View className='kb-upload__dropzone' onClick={() => void handlePick()}>
        <Text className='kb-upload__dropzone-title'>{KB_UPLOAD_COPY.pickTitle}</Text>
        <Text className='kb-upload__dropzone-hint'>{KB_UPLOAD_COPY.pickHint}</Text>
        <Text className='kb-upload__dropzone-hint'>
          {KB_UPLOAD_COPY.sizeLimit(DOCUMENT_MAX_LABEL)}
        </Text>
      </View>

      {/* ---- 选中的文件 ---- */}
      {picked ? (
        <View className='card'>
          <View className='tiny'>{KB_UPLOAD_COPY.selectedLabel}</View>
          <View className='li'>
            <View className='ico'>
              <Text className='kb-upload__ext'>{EXT_LABEL[extOf(picked.name)] ?? 'FILE'}</Text>
            </View>
            <View className='tx'>
              <View className='n kb-upload__file-name'>{picked.name}</View>
              <View className='d'>{picked.size > 0 ? formatBytes(picked.size) : ''}</View>
            </View>
            <Text className='tiny' onClick={() => void handlePick()}>
              {KB_UPLOAD_COPY.reselect}
            </Text>
          </View>
        </View>
      ) : null}

      {/* ---- 最近上传（只有从某个库进来时才有，见文件头） ---- */}
      {recent.length > 0 ? (
        <View className='card'>
          <View className='tiny'>{KB_UPLOAD_COPY.recentLabel}</View>
          {recent.map((doc) => (
            <View
              className='li'
              key={doc.id}
              onClick={() =>
                goPage(
                  `/pages/workshop/kb-parsing/index?kb_id=${doc.kb_id}&doc_id=${doc.id}`,
                  'navigate'
                )
              }
            >
              <View className='ico'>
                <Text className='kb-upload__ext'>{EXT_LABEL[doc.ext] ?? doc.ext.toUpperCase()}</Text>
              </View>
              <View className='tx'>
                <View className='n kb-upload__file-name'>{doc.filename}</View>
                <View className='d'>{formatBytes(doc.size_bytes)}</View>
              </View>
              <Text className='pill'>{KB_STATUS_LABEL[doc.status]}</Text>
            </View>
          ))}
        </View>
      ) : null}

      <View className='spacer' />

      <Button
        className={`btn${picked && !uploading ? '' : ' dis'}`}
        disabled={!picked || uploading}
        onClick={() => void handleSubmit()}
      >
        {uploading ? KB_UPLOAD_COPY.uploading : KB_UPLOAD_COPY.submit}
      </Button>
      <View className='tiny kb-upload__status'>{KB_UPLOAD_COPY.uploadingHint}</View>
    </PhoneShell>
  )
}
