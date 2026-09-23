/**
 * 「这次取材走哪条路」的**唯一判定**。
 *
 * ## 为什么要有这个文件
 *
 * 同一套判据（后端有没有能力 × 用户这次想不想联网 × 输入里有没有链接）在两处被用到：
 *
 * - 大厅那只 pill 显示哪句话（`HALL_SEARCH_COPY`）；
 * - 召唤页「后端还没回第一个状态」时的本地兜底步骤名（`SUMMON_STEPS`）。
 *
 * 两处各写一遍分支，迟早会改歪一处 —— 而歪掉的表现是「pill 说会读你的链接，
 * 进度条第一步却说理解你的输入」，用户只会认为功能坏了。
 * 所以判定收在这里，页面只负责把 mode 映射成自己那套文案。
 *
 * ## 与后端的对应关系
 *
 * 后端对应的是 `app/llm/search/base.py` 的 `build_initial_step(request, can_search_web, can_read_pages)`，
 * 优先级同样是 **链接 > 主动检索 > 理解输入**；能力缺席时无论意愿与链接如何，
 * 都退回「理解你的输入」（`NoopSearchProvider` 一次网络都不碰，不能显示「联网检索知识」）。
 * 这里的 `canSearch` 同时代表后端的 `can_search_web` 与 `can_read_pages` ——
 * 当前只有「全有（tavily）」与「全无（noop）」两种 Provider。
 */

/** 取材路径。取值与 `design.md` D8 的 pill 四态表逐行对应（`unavailable` 是第五行）。 */
export type RetrievalMode =
  /** 后端没有这个能力 —— 意愿与链接都不影响结果 */
  | 'unavailable'
  /** 有能力 · 意愿开 · 无链接 */
  | 'online'
  /** 有能力 · 意愿开 · 有链接 */
  | 'online-with-link'
  /** 有能力 · 意愿关 · 有链接（链接**始终**被读，不受意愿约束） */
  | 'link-only'
  /** 有能力 · 意愿关 · 无链接 */
  | 'offline'

/**
 * 按「能力 × 意愿 × 有无链接」定出取材路径。
 *
 * @param canSearch 后端是否配好了联网检索（`GET /health` 的 `search_enabled`）。
 * @param wantsSearch 用户这次的意愿（大厅 pill 的状态）。
 * @param hasLink 输入里有没有用户自己贴的链接（`utils/links`）。
 */
export function resolveRetrievalMode(
  canSearch: boolean,
  wantsSearch: boolean,
  hasLink: boolean
): RetrievalMode {
  if (!canSearch) return 'unavailable'
  if (wantsSearch) return hasLink ? 'online-with-link' : 'online'
  return hasLink ? 'link-only' : 'offline'
}
