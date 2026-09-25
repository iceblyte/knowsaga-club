# Design

## Context

见 `proposal.md` 的 Why。技术现状：

- 知识库检索作为**第三个取材工具**接在既有 Agent 循环里（`run_search_agent`）；
  工具由 `app/llm/kb/tools.py` 的 `build_kb_tool(request, settings)` 构造 ——
  Tavily 与 Noop 两个 Provider 都调它，是**唯一入口**。
- 进度卡第一步的名字由 `describe_step(request, can_search_web, can_read_pages, can_search_kb)` 算，
  两个 Provider 的 `initial_step()` 各调一次；`gather()` 回来时 `SearchOutcome.step_name`
  由 `run_search_agent` 内部再算一次。**两处算同一个名字，必须一致**。
- 前端启动时已在 `app.ts` 里做一次 `GET /health` 探测（拿 `search_enabled` 等），
  结果写进 `useAppStore`。
- 交付时这个开关只在 `config.py` 里声明过；`__init__.py` 的惰性导入让它「顺带」管住了
  chromadb 的加载代价，但**没有任何分支真正读它**。

硬约束相关项（`openspec/config.yaml`）：① 后端 TDD，tasks 体现先测后实现；
② 前端改动零视觉漂移，要实测证据；③ 文案与实现冲突时改文案。

## Goals / Non-Goals

**Goals:**

- 开关关闭时，**取材链真的不绑**知识库工具，前端**真的不显示**四处入口，且卡片文案不撒谎。
- 开关打开时，行为与「没有这个开关」逐位一致 —— 不引入任何可见差异。
- 开关值只有一个事实来源（后端），前端不另配一份。

**Non-Goals:**

- 不做权限控制（端点注册方式不变）、不做热切换、不做分用户开关。
- 不重构取材链，不改任何既有工具的行为与上限。

## Decisions

### D-1 开关落点选在 `build_kb_tool()`，不在取材链上再判一次

**选它**：这是唯一的工具构造入口。关掉时返回 `None`，于是
`run_search_agent` 里 `kb_tool is not None` 的判定、`initial_step` 给出的进度名、
以及「模型点名调用未提供的工具会被拒绝」这三处**自动一致**。

**替代方案**：在 `run_search_agent` 与两个 `initial_step` 里各判一次开关。否决理由：
三处各判一次就迟早漂移，症状正是本变更要消灭的那类 —— 进度卡写着「检索你的知识库」，
实际一次都没查（`base.py` 的 `describe_step` 文档里已把这个失败模式写下来了）。

### D-2 开关值经 `GET /health` 下发，不新建专用接口

**选它**：`app.ts` 启动时已经打这一次探测（`search_enabled` 就是这么来的），
加一个字段是**零新增请求**；`HealthInfo` 是现成的类型落点。

**替代方案**：新建 `GET /config`。否决理由：多一次往返、多一个要维护的端点，
而它要回答的问题与 `/health` 完全同类（「这个部署有哪些能力」）。
**替代方案**：把开关编译进前端常量。否决理由：两边各配一份必然漂移 ——
后端关掉了、前端还显示入口，正是本变更要修的病。

### D-3 前端默认 `false`：探测不到就按「关」处理

`useAppStore.knowledgeBaseEnabled` 初值为 `false`。取不到值（后端没起、请求失败）时保持
「看不见」。取舍：**「看不见但能用」优于「看得见却点不通」** —— 前者只是少一个入口，
后者会让用户以为功能坏了、进而怀疑整个应用。

### D-4 它不是权限位，这条边界要写进注释与规格

`/kb/*` 八个端点**仍无条件注册**（原设计 D18 的理由不变：挂开关会让关掉时前端拿到 404，
与「路径写错」同形）。因此本开关管的是「让不让用户看见」，**不是**「拦不拦得住请求」。
这条边界容易在半年后被误读成安全控制，所以在 `health.py`、`tools.py` 的注释与
`private-knowledge-base` 的需求里都明写。

### D-5 工坊卡片文案随开关切换，不是只藏入口

`WORKSHOP_COPY` 拆成 `descWithKb` / `descWithoutKb`。关掉时那句
「现在可以把文档收进知识库、拿它出题」是**空头承诺** —— 按硬约束③（文案与实现冲突时改文案），
切回「多源输入还在路上」那版，而不是把入口藏掉却留着一句假承诺。

## Risks / Trade-offs

- [前端持有的是**启动快照**；后端中途改开关，前端仍按旧值显示] → 本期接受：开关是启动时读的，
  改 `.env` 必须重启后端；重启后前端刷新会重新探测。已在 Non-goals 明确不做热更新。
- [测试基线被本机 `.env` 污染] → `tests/conftest.py` 把 `KNOWLEDGE_BASE_ENABLED` 钉成 `false`
  （与既有 `KNOWLEDGE_SEARCH_ENABLED` 同一手法），需要打开的模块用 KB 夹具显式打开。
  不钉的表现是「只在本机红/绿」，最坏情况下把「默认关 ⇒ 前端看不见入口」这条悄悄测没了。
- [`knowledge_base_enabled` 被当成权限位，将来有人靠它做访问控制] → 注释 + 规格双处写明边界，
  并留一条 Scenario 钉死「开关关闭 ≠ 接口关闭」。
- [两处算进度名漂移] → 由 `describe_step` 单一实现 + 测试里「两处名字逐字相同」的断言兜住。

## Migration Plan

1. **后端**（TDD）：先写测试跑红（`/health` 字段、`build_kb_tool` 关时返 `None`、
   `describe_step` 与 `gather` 的名字一致、开关关时进度名不得预告检索知识库）→ 再改实现。
2. **前端**：`types/api.ts` → `store/useAppStore.ts` → `app.ts` → 三个页面 + `copy.ts`；
   `tsc --noEmit --skipLibCheck` 必须 EXIT=0。
3. **文档**：`.env`、`.env.example`、`docs/方案设计文档.md` §14.4 / §14.6 同步。
4. **闸门**：全量 `pytest` + `tsc --noEmit` + `python tools/scan_secrets.py` + 双端构建。
5. **真浏览器两条态验收**：`false` ⇒ 四处入口不可见且卡片文案切换；`true` ⇒ 四处入口回来。

**回滚**：把 `KNOWLEDGE_BASE_ENABLED` 置 `true` 即回到「入口永远可见、取材链永远绑工具」的旧行为，
**无需回滚代码**；代码层回滚则是撤掉这 12 个请求/响应文件里的判定，无数据表、无迁移。

## Open Questions

无。开关的默认值、落点与下发方式都由本变更定死；「要不要顺带做权限位」已列入 Non-goals，
需要时另立变更。
