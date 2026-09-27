#!/usr/bin/env node
/**
 * UI 主题的「一致性闸门」—— 一条命令验完四处必须互相对齐的东西。
 *
 * ## 为什么要有它
 *
 * 主题这套东西有四份表示：
 *   1. `shared/ui-themes.json`          —— 手写的核心色（真源）
 *   2. `lib/ui-theme-recipe.mjs` 的派生 —— 算出来的其余令牌
 *   3. `src/styles/_themes.scss`        —— 生成物（入库，跑起来真加载的就是它）
 *   4. `src/styles/tokens.scss`         —— 默认主题的 var() 兜底字面量
 *
 * 本项目在「同一口径两处实现」上吃过亏（算分那回）。所以这里把它们两两钉住：
 *   · 生成物 vs 真源 —— `gen_theme_scss.mjs --check`（改了 JSON 忘了重生成会红）
 *   · 派生值 vs WCAG —— `audit_theme_contrast.mjs`（含「兜底字面量 vs 手抄表」核对）
 *
 * ## 用法
 *
 * ```
 * cd frontend && npm run check:theme
 * ```
 *
 * 退出码：0 = 全绿；1 = 有任一项不过（会打印是哪一步、为什么）。
 * 生成物过期时提示「跑 gen:theme」，而不是自动改写 —— 提交前应该看得见 diff。
 */

import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const run = (script, ...args) => {
  const result = spawnSync(process.execPath, [path.join(HERE, script), ...args], {
    stdio: 'inherit'
  })
  if (result.error) {
    console.error(`无法运行 ${script}：${result.error.message}`)
    process.exit(1)
  }
  return result.status ?? 1
}

const steps = [
  ['生成物是否与真源一致', () => run('gen_theme_scss.mjs', '--check')],
  ['五套主题的 WCAG 体检', () => run('audit_theme_contrast.mjs')]
]

const failures = []
for (const [label, step] of steps) {
  console.log(`\n── ${label}`)
  if (step() !== 0) failures.push(label)
}

console.log('')
if (failures.length > 0) {
  console.error(`主题闸门未通过：${failures.join(' / ')}`)
  process.exit(1)
}
console.log('主题闸门通过：生成物最新 + 五套主题语义色全部达标。')
