/**
 * 私有知识库的接口调用（原型 05 的第 2–8 屏）。
 *
 * | 函数 | 接口 | 原型屏 |
 * |---|---|---|
 * | `fetchBases` | `GET /kb` | 05·5 我的知识库 |
 * | `createBase` | `POST /kb` | 05·6 新建（本期不单独出屏，由列表页承载） |
 * | `fetchBaseDetail` | `GET /kb/{kb_id}` | 05·7 详情 / 05·3 解析进度轮询 |
 * | `updateBase` | `PATCH /kb/{kb_id}` | 05·7 改名 / 改描述 |
 * | `deleteBase` | `DELETE /kb/{kb_id}` | 05·7 删库 |
 * | `uploadDocument` | `POST /kb/documents` | 05·2 上传文档 |
 * | `reparseDocument` | `POST /kb/documents/{id}/reparse` | 05·3 失败态重试 |
 * | `deleteDocument` | `DELETE /kb/documents/{id}` | 05·7 删文档 |
 *
 * ## 三条贯穿全模块的约定
 *
 * **1. 越权与不存在是同一个 4005。** 每个按 id 访问的接口都可能在「别人的
 * 东西」与「已经没了」两种情况下返回同一句「内容不存在或已删除」。
 * 调用方**不要**试图从错误码推断是哪一种 —— 后端刻意不区分，那正是它要藏的
 * 信息。界面上就统一说「内容不存在或已删除」。
 *
 * **2. 上传走 `upload()` 而不是 `request()`。** 文件没有地方放进 JSON 里
 * （见 `services/request.ts` 的说明）。`filename` 与 `kb_id` 必须作为
 * **表单字段**额外带上：`Taro.uploadFile` 只会把临时路径的最后一段
 * 当 multipart filename，微信端那是随机临时名，判不了扩展名。
 *
 * **3. `poll_interval_ms` 由后端给，前端不写死。** 原型写 8 秒、本期是 2 秒，
 * 以后还可能变。页面照这个数字轮询即可。
 *
 * ## 为什么 id 一律按字符串传
 *
 * 与卷轴 / 题目的约定一致：后端的 `id` 是字符串形式的数据库主键，
 * 前端原样透传、原样当 key 用，不做 `Number()` 转换 ——
 * 转了之后在 URL 里拼回去还要再 `String()`，多一次往返就多一个出错的地方。
 */

import type {
  KbBaseDetailResponse,
  KbBaseItem,
  KbCreatePayload,
  KbDeleteResponse,
  KbDocumentDeleteResponse,
  KbDocumentEnvelope,
  KbListResponse,
  KbUpdatePayload
} from '../types/api'
import { request, upload } from './request'

/**
 * 我的知识库列表（05·5）。
 *
 * **不分页**：一个用户手上的资料库是「个位数」。这也是列表页唯一的
 * 「进来就刷新」的接口。
 *
 * 每项的 `ready_count` 是「能不能出题」的判据 —— 为 0 时「从本库出题」
 * 按钮要置灰（原型 05·5 的批注）。后端**不拦**这种请求（design D17）：
 * 取资料那一步本来就能区分「库是空的」与「没命中」，照常出题只是没有
 * 知识库依据，比「等了几秒才被告知库是空的」更符合「降级优先于失败」。
 *
 * @throws {ApiError} 4010（登录态失效后重建仍失败）
 */
export function fetchBases(): Promise<KbListResponse> {
  return request<KbListResponse>({ path: '/kb' })
}

/**
 * 新建知识库（05·6）。
 *
 * 名字在同一用户下**唯一**，重名报 4001 而不是静默返回已有的那一个 ——
 * 用户说了「新建」，回一份别的东西会让他以为名字被改了。
 * 所以调用方要在 4001 时提示「这个名字已经有了」，而不是刷新列表了事。
 *
 * @throws {ApiError} 4000（名字长度不在 2–40 字内）、4001（重名）、4010
 */
export function createBase(payload: KbCreatePayload): Promise<KbBaseItem> {
  return request<KbBaseItem>({
    path: '/kb',
    method: 'POST',
    data: payload as unknown as Record<string, unknown>
  })
}

/**
 * 知识库详情：库 + 它的**全部**文档（05·7）。
 *
 * 它同时是解析进度页轮询的那一个接口（05·3）—— 那一屏要看到的是一个整体
 * 状态（哪几份还在解析、哪份失败了），而不是某一页。
 * 文档列表因此也不分页（库的文档数上限由后端 `kb_max_docs_per_base` 卡住）。
 *
 * @throws {ApiError} 4000（kb_id 不是正整数）、4005（不存在或不属于当前用户）
 */
export function fetchBaseDetail(kbId: string): Promise<KbBaseDetailResponse> {
  return request<KbBaseDetailResponse>({ path: `/kb/${kbId}` })
}

/**
 * 改名 / 改描述（05·7）。**只提交要改的字段**。
 *
 * 两个字段都不给会被后端判 4000，而不是「静默成功」—— 一个什么都没改的
 * PATCH 在客户端看起来与改成功一模一样，而用户明明改过东西。
 * 类型上已经要求至少一个（`KbUpdatePayload` 是联合），所以这条在编译期就成立。
 *
 * @throws {ApiError} 4000（两个都没给 / 名字长度不合规）、4001（重名）、4005
 */
export function updateBase(kbId: string, payload: KbUpdatePayload): Promise<KbBaseItem> {
  return request<KbBaseItem>({
    path: `/kb/${kbId}`,
    method: 'PATCH',
    data: payload as unknown as Record<string, unknown>
  })
}

/**
 * 删除知识库（05·7）：库、全部文档、全部向量、全部原文件一起清。
 *
 * **不可撤销**，所以调用方必须先让用户确认。重复删除报 4005 ——
 * 与 `deleteScroll` 同一条约定：要表现得幂等就由调用方把 4005 当成成功
 * （东西本来就已经不在了，用户的目标已达成）。
 *
 * @throws {ApiError} 4000、4005（不存在 / 不属于当前用户 / 已经删过）
 */
export function deleteBase(kbId: string): Promise<KbDeleteResponse> {
  return request<KbDeleteResponse>({ path: `/kb/${kbId}`, method: 'DELETE' })
}

export interface UploadDocumentOptions {
  /** 本地文件路径（`chooseMessageFile` 或 H5 `<input type=file>` 的产物） */
  filePath: string
  /**
   * 客户端给的**原始文件名**，形如 `机器学习导论.pdf`。
   *
   * ⚠️ 必须显式传。它决定两件事：扩展名准入（`.pdf` / `.docx` / `.md` / `.txt`）
   * 与界面上的显示名。不传的话后端会退而取 multipart 的 filename，
   * 而微信端那是随机临时名 —— 用户会看到一份叫 `tmp_xxx` 的文档，
   * 格式判定也会失败。
   */
  filename: string
  /**
   * 传到哪个库。**不传则落到「默认库」**（大厅那个「上传文档」入口
   * 不知道任何库 id，见 design D16）。
   */
  kbId?: string
}

/**
 * 上传一份文档（05·2）。**立刻返回**，解析在后台跑。
 *
 * 响应里的 `document.status` 是**调用前的快照**，通常是 `pending` ——
 * 不要等它变成 `ready` 再跳转，终态靠轮询 `fetchBaseDetail`（design D19）。
 * 同理也不要去解析 `parsed_at` / `chunk_count`。
 *
 * ⚠️ 体积与格式的错误码是 **4002**，且它的文案是为文档写的（不是头像那一句）——
 * 直接展示即可，不要自己拼一句「文件不合规」把后端的话盖掉。
 *
 * @throws {ApiError} 4002（格式不支持 / 体积超限 / 抽取不到内容）、
 *                    4000（`kb_id` 非正整数）、4005（kb_id 不存在或不属于当前用户）
 */
export function uploadDocument(options: UploadDocumentOptions): Promise<KbDocumentEnvelope> {
  const formData: Record<string, string> = { filename: options.filename }
  if (options.kbId) formData.kb_id = options.kbId

  return upload<KbDocumentEnvelope>({
    path: '/kb/documents',
    filePath: options.filePath,
    formData
  })
}

/**
 * 重新解析一份文档（05·3 失败态的「重试」）。
 *
 * 它是**唯一**的恢复手段：进程重启遗留的「解析中」、上游抖动导致的失败、
 * 用户把文件改好之后的重试，都走这一条。所以后端**不限制**当前状态 ——
 * 一份已经 `ready` 的文档也能重新解析（用于「我换了同名文件」的场景）。
 *
 * 与上传同理：响应里的 `status` 是 `parsing`（服务层故意先写进去的，
 * 让界面马上有反应），终态仍要轮询。
 *
 * @throws {ApiError} 4000、4005（不存在 / 不属于当前用户）
 */
export function reparseDocument(docId: string): Promise<KbDocumentEnvelope> {
  return request<KbDocumentEnvelope>({
    path: `/kb/documents/${docId}/reparse`,
    method: 'POST'
  })
}

/**
 * 删除一份文档（05·7）：记录 + 向量 + 原文件。
 *
 * ⚠️ 这条最容易写漏的是**向量的清理在服务端**：删掉记录却不删向量，
 * 症状是「删掉的内容还会出现在题目里」。前端不需要做任何额外的事，
 * 但也不要在前端「先隐藏条目再看结果」—— 万一服务端失败了，
 * 用户会以为已经删掉了。
 *
 * @throws {ApiError} 4000、4005（不存在 / 不属于当前用户）
 */
export function deleteDocument(docId: string): Promise<KbDocumentDeleteResponse> {
  return request<KbDocumentDeleteResponse>({
    path: `/kb/documents/${docId}`,
    method: 'DELETE'
  })
}
