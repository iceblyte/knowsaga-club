#!/usr/bin/env node
/**
 * 链接抽取的**前后端一致性检查**。
 *
 * ## 它解决什么问题
 *
 * 判「输入里有没有链接」有两份实现：`src/utils/links.ts`（大厅那只 pill 显示哪句话）
 * 与 `backend/app/utils/links.py`（服务端决定真的去读哪些页面）。两处一旦不一致，
 * 用户看到的是「pill 说会读取你的链接，进度条第一步却说理解你的输入」——
 * 只会被理解成功能坏了。
 *
 * 本项目已经在算分上吃过一次「同一口径两处实现」的亏，所以这里同样不靠人眼：
 * 判据写在 `shared/link-cases.json`，两端各自断言同一份数据。
 * 后端的对应检查是 `backend/tests/test_links.py`。
 *
 * ## 怎么把 TS 跑起来
 *
 * 不引测试框架（前端没有 test runner，加一套的维护成本高于收益）。
 * 直接用 Taro 已经装好的 `typescript` 把 `links.ts` 转成 CommonJS 再执行。
 * `links.ts` 没有任何 import —— 所以那份 JS 没有运行时依赖，`new Function` 里就能跑；
 * 万一将来有人给它加了真实 import，下面的 `noRuntimeDeps` 会立刻抛错，
 * 而不是静默跑成另一份逻辑。
 *
 * ## 用法
 *
 * ```
 * cd frontend && npm run check:links
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

const CASES_PATH = path.join(REPO, 'shared', 'link-cases.json')
const SOURCE_PATH = path.join(FRONTEND, 'src', 'utils', 'links.ts')

/** 共享用例少于这个数就判定「文件被误删/清空」——否则空数组会让检查空转成绿。 */
const MIN_CASES = 20

function loadLinksModule() {
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
    throw new Error(`links.ts 转译失败：\n${text}`)
  }

  const mod = { exports: {} }
  const noRuntimeDeps = (id) => {
    throw new Error(`links.ts 出现了运行时依赖 "${id}"，本检查脚本只支持纯逻辑模块`)
  }
  new Function('exports', 'module', 'require', outputText)(mod.exports, mod, noRuntimeDeps)
  return mod.exports
}

const links = loadLinksModule()
const payload = JSON.parse(fs.readFileSync(CASES_PATH, 'utf8'))
const cases = payload.cases || []

console.log(`共享用例：${CASES_PATH}`)
console.log(`前端实现：${SOURCE_PATH}`)

if (cases.length < MIN_CASES) {
  console.error('')
  console.error(`共享用例只有 ${cases.length} 条（至少应有 ${MIN_CASES} 条）。`)
  console.error('文件可能被误删或清空 —— 用例太少时这条检查会空转成绿，所以直接判失败。')
  process.exit(1)
}

const failures = []
let checked = 0

for (const item of cases) {
  const text = String(item.text == null ? '' : item.text)
  const expected = (item.urls || []).map(String)

  const actual = links.extractUrls(text)
  checked += 1
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    failures.push(
      `${item.name} · extractUrls\n     期望 ${JSON.stringify(expected)}\n     实际 ${JSON.stringify(actual)}`
    )
  }

  const actualHas = links.hasUrl(text)
  const expectedHas = expected.length > 0
  checked += 1
  if (actualHas !== expectedHas) {
    failures.push(
      `${item.name} · hasUrl\n     期望 ${JSON.stringify(expectedHas)}\n     实际 ${JSON.stringify(actualHas)}`
    )
  }
}

console.log(`断言 ${checked} 项（${cases.length} 条用例 × extractUrls / hasUrl）`)

if (failures.length > 0) {
  console.error('')
  console.error(`发现 ${failures.length} 处前后端不一致：`)
  for (const line of failures) {
    console.error(`  ! ${line}`)
  }
  console.error('')
  console.error('请先对齐 shared/link-cases.json 与两份实现，再提交。')
  process.exit(1)
}

console.log('一致：前端实现与共享用例逐条吻合。')
