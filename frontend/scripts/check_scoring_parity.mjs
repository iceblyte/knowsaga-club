#!/usr/bin/env node
/**
 * 前后端算分的**一致性检查**。
 *
 * ## 它解决什么问题
 *
 * 判题有两份实现：`src/utils/scoring.ts`（答题时的即时反馈）与
 * `backend/app/services/scoring.py`（交卷后的权威结算）。两处一旦不一致，
 * 用户看到的就是「答题时显示答对，结算页少给 40 XP」——最难解释、
 * 也最伤信任的一类 bug。
 *
 * 本项目已经吃过「同一口径两处实现」的亏，所以这里不靠人眼比对：
 * 规则写在 `shared/scoring-cases.json`，两边各自断言同一份数据。
 * 后端的对应检查是 `backend/tests/test_scoring.py`。
 *
 * ## 怎么把 TS 跑起来
 *
 * 不引测试框架（前端没有 test runner，加一套的维护成本高于收益）。
 * 直接用 Taro 已经装好的 `typescript` 把 `scoring.ts` 转成 CommonJS 再执行。
 * `scoring.ts` 只有 `import type`，转译后会被完全擦除 —— 所以那份 JS
 * 没有任何运行时依赖，`new Function` 里就能跑；万一将来有人加了真实 import，
 * 下面的 `require` 会立刻抛错，不会静默跑成另一份逻辑。
 *
 * ## 用法
 *
 * ```
 * cd frontend && node scripts/check_scoring_parity.mjs
 * ```
 *
 * 退出码：0 = 两边完全一致；1 = 有分歧（会列出每一条）。
 */

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const ts = require('typescript')

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')
const REPO = path.resolve(FRONTEND, '..')

const CASES_PATH = path.join(REPO, 'shared', 'scoring-cases.json')
const SOURCE_PATH = path.join(FRONTEND, 'src', 'utils', 'scoring.ts')

function loadScoringModule() {
  const source = fs.readFileSync(SOURCE_PATH, 'utf8')
  const { outputText, diagnostics } = ts.transpileModule(source, {
    fileName: SOURCE_PATH,
    reportDiagnostics: true,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2019,
      isolatedModules: true
    }
  })

  const errors = (diagnostics || []).filter((d) => d.category === ts.DiagnosticCategory.Error)
  if (errors.length > 0) {
    const text = errors.map((d) => ts.flattenDiagnosticMessageText(d.messageText, ' ')).join('\n')
    throw new Error(`scoring.ts 转译失败：\n${text}`)
  }

  const mod = { exports: {} }
  const noRuntimeDeps = (id) => {
    throw new Error(`scoring.ts 出现了运行时依赖 "${id}"，本检查脚本只支持纯逻辑模块`)
  }
  new Function('exports', 'module', 'require', outputText)(mod.exports, mod, noRuntimeDeps)
  return mod.exports
}

const scoring = loadScoringModule()
const cases = JSON.parse(fs.readFileSync(CASES_PATH, 'utf8'))

const failures = []
let checked = 0
const groups = new Map()

function record(group, name, actual, expected) {
  checked += 1
  groups.set(group, (groups.get(group) || 0) + 1)
  if (actual !== expected) {
    failures.push(`${group} · ${name}\n     期望 ${JSON.stringify(expected)}\n     实际 ${JSON.stringify(actual)}`)
  }
}

for (const item of cases.grade_cases || []) {
  const result = scoring.gradeQuestion(
    { id: 'q', type: item.type, answer: item.answer },
    item.selected
  )
  record('grade_cases', `${item.name} · outcome`, result.outcome, item.expected.outcome)
  record('grade_cases', `${item.name} · earned_xp`, result.earnedXp, item.expected.earned_xp)
  record('grade_cases', `${item.name} · max_xp`, result.maxXp, item.expected.max_xp)
}

for (const item of cases.accuracy_cases || []) {
  record('accuracy_cases', item.name, scoring.accuracyOf(item.correct_count, item.total_count), item.expected)
}

for (const item of cases.coins_cases || []) {
  record('coins_cases', item.name, scoring.coinsOf(item.xp), item.expected)
}

// 百分位**不在这里比对**，因为 2026-09-24 起它已经被整条删掉了
// （列 / 计算链 / 接口字段全没了，迁移 `sql/06`）。那一格换成了「与自己的历史比」：
// 后端 `progress_service.py` 算好六态塞进 `summary.progress` / `report.progress`，
// 前端只负责把状态翻成文案（`constants/copy.ts :: progressTextOf`）。
// 前端这一侧没有可算的公式，自然也就没有共享用例。

// -----------------------------------------------------------------------------
// 输出
// -----------------------------------------------------------------------------
const countLine = [...groups.entries()].map(([k, v]) => `${k} ${v} 条`).join(' | ')
console.log(`共享用例：${CASES_PATH}`)
console.log(`前端实现：${SOURCE_PATH}`)
console.log(`断言 ${checked} 项（${countLine}）`)

if (failures.length > 0) {
  console.error('')
  console.error(`发现 ${failures.length} 处前后端不一致：`)
  for (const line of failures) {
    console.error(`  ! ${line}`)
  }
  console.error('')
  console.error('请先对齐 shared/scoring-cases.json 与两份实现，再提交。')
  process.exit(1)
}

console.log('一致：前端实现与共享用例逐条吻合。')
