/**
 * 等待页的「平滑进度」。
 *
 * ## 为什么需要它（本轮修复第 5 条）
 *
 * 后端只在**两个时刻**更新「生成闯关题目」这一步：开始
 * （`正在生成第 1 / 5 题`）与结束（`已生成 5 道题`）。中间没有任何事件可报 ——
 * 5 道题是**一次** LLM 调用出来的，服务端根本不存在「第 2 题开始了」这种时刻。
 * 于是那二三十秒里界面一动不动：秒数不变（`SUMMON_COPY` 的「预计 12 秒」是
 * 一个**静态**字段）、题号不变。用户的第一反应是「卡死了」，然后去点取消。
 *
 * ## 这里插值的不是「进度」，是「还要多久」
 *
 * 它是**估算**，不是真值。所以边界卡得很死，四条规矩一条都不能松：
 *
 * 1. **只递增、永不回退** —— 数值往回跳会让用户以为出错了；
 * 2. **题号停在 `N - 1`** —— 最后一道题只有后端的「已生成 N 道题」能宣布，
 *    客户端不许替它说完成；
 * 3. **秒数走完就换一句话**（「比预计多花了一会儿」），而不是继续报一个假 0；
 * 4. **进度条不许到 100%** —— 还在跑的时候停在 95% 以下，`100%` 只属于
 *    服务端给的终态。
 *
 * ## 唯一的标尺是服务端自己给的两个数
 *
 * `estimated_seconds`（`POST /quiz/generate` 下发）与题量（从服务端**自己的**
 * 详情文案里解析）。不引入任何本地魔法常数 —— 这里做的只是把服务端已经说过的
 * 事铺平到每一秒，而不是另编一套进度。所以「步骤文案由后端给、前端不自己编」
 * 这条规则没有被破坏：**措辞仍然逐字来自服务端**（见 `advanceQuestionDetail`
 * 只替换一个数字，连空格都保留原样）。
 *
 * 服务端一旦改了详情文案的措辞，下面的正则匹配不上 → 插值自动关闭，
 * 界面退回「只有两个端点」的老样子。**这是有意的 fail-open**：
 * 宁可不平滑，也不要拼出一句服务端没说过的话。
 */

/** 一次服务端更新之后，进度条最多还能往前爬多少点（安全上限，见文件头） */
const MAX_CREEP = 25

/** 未进入终态时的进度上限。`100` 只属于服务端（见文件头第 4 条） */
const MAX_UNFINISHED = 95

/** 生成步骤最少按几秒估。太小的值会让题号几秒就冲到 N-1 */
const MIN_GENERATE_SECONDS = 5

/** 「正在生成第 3 / 5 题」——只认服务端自己那一种写法 */
const QUESTION_DETAIL = /(第\s*)(\d+)(\s*\/\s*)(\d+)(\s*题)/

/** 已等待的秒数（负数与 NaN 都按 0 处理：时钟回拨不该让界面倒退） */
function safeElapsed(elapsed: number): number {
  return Number.isFinite(elapsed) && elapsed > 0 ? elapsed : 0
}

/**
 * 「大约还要多久」。
 *
 * 返回 `0` 表示**已经超过预计时长**。调用方必须换一句文案，而不是
 * 显示「预计 0 秒」—— 那读起来像「立刻就好」，而事实是它已经超时了。
 */
export function remainingSeconds(estimated: number, elapsed: number): number {
  const total = Number.isFinite(estimated) && estimated > 0 ? estimated : 0
  return Math.max(0, Math.ceil(total - safeElapsed(elapsed)))
}

/**
 * 进度条的显示值。
 *
 * 服务端给的值是**下限**（它说 30 就是 30），上面那点爬升来自时间比例，
 * 并且一次服务端更新之后最多再多爬 `MAX_CREEP` 点 —— 没有这个上限的话，
 * 一个卡住的任务会把进度条一路推到 95%，用户会一直等一个永远不来的结果。
 */
export function smoothProgress(
  progress: number,
  elapsed: number,
  estimated: number,
  finished: boolean
): number {
  const base = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0
  if (finished) return 100

  const total = Number.isFinite(estimated) && estimated > 0 ? estimated : 0
  if (total === 0) return base

  const ratio = Math.min(safeElapsed(elapsed) / total, 1)
  const target = Math.round(ratio * MAX_UNFINISHED)
  return Math.max(base, Math.min(target, base + MAX_CREEP, MAX_UNFINISHED))
}

/**
 * 把服务端的「正在生成第 x / N 题」推进到第 `shown` 题。
 *
 * **只替换第一个数字**，`第` / `/` / `题` 与那几处空格全部逐字保留服务端的原样 ——
 * 这样即使后端把「第 1 / 5 题」改成「第 1/5 题」，这里也不会拼出两种写法。
 *
 * 匹配不上（措辞变了、或这一步还没开始生成）时原样返回。
 */
export function advanceQuestionDetail(detail: string, shown: number): string {
  if (!QUESTION_DETAIL.test(detail)) return detail
  return detail.replace(
    QUESTION_DETAIL,
    (_match, head: string, _current: string, middle: string, total: string, tail: string) =>
      `${head}${shown}${middle}${total}${tail}`
  )
}

/**
 * 当前应该显示到第几题（1-based）。返回 `null` 表示「这一步不该被插值」。
 *
 * `elapsedInStep` 是**进入生成这一步之后**的秒数，不是整个任务的耗时 ——
 * 从任务开始算会把前面检索的时间也算进来，题号一上来就冲到第 2 题。
 *
 * 结果单调不减，且上限是 `N - 1`（见文件头第 2 条）。
 */
export function smoothQuestionIndex(
  detail: string,
  status: string,
  elapsedInStep: number | null,
  estimated: number
): number | null {
  if (status !== 'running' || elapsedInStep === null) return null

  const matched = QUESTION_DETAIL.exec(detail)
  if (!matched) return null

  const total = Number(matched[4])
  if (!Number.isFinite(total) || total < 2) return null

  // 生成这一步的预算：检索那一步通常几秒就完，所以整个任务的预计时长
  // 拿来当这一步的标尺（留一点给检索与校验，避免一进生成就算满）
  const budget = Math.max(MIN_GENERATE_SECONDS, estimated - 3)
  const ratio = Math.min(safeElapsed(elapsedInStep) / budget, 1)

  // N 道题里有 N-1 个「空档」：第 1 题是起点，第 N 题留给服务端宣布
  const advanced = 1 + Math.floor(ratio * (total - 1))
  return Math.max(1, Math.min(total - 1, advanced))
}
