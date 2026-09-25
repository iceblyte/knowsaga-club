# Proposal

## Why

`KNOWLEDGE_BASE_ENABLED` 交付时只在配置里声明了一行，**运行时零读取**：关掉它之后，
前端照样显示四处入口、取材链照样把知识库检索交给模型。于是 `.env` 里那句「关掉即不启用」
成了**用期望语义冒充已实现语义** —— 部署方按注释关干净了，实际什么都不会变，
而他会以为自己已经关掉了。

## What Changes

- **取材链**：`build_kb_tool()` 在开关关闭时返回 `None`，与「这次没带库」走同一条路径 ——
  模型一次知识库检索都发不出来。这是 design D7 的实现点：它是**唯一的工具构造入口**，
  两个 Provider 都走它，所以「绑不绑工具」与「进度名说不说检索知识库」自动一致。
- **能力下发**：`GET /health` 增 `knowledge_base_enabled`，作为前端入口显隐的**唯一事实来源**。
- **前端入口**：大厅两枚资料 chip（上传文档 / 粘贴网址）、「我的」知识库行、工坊两行入口
  按开关显隐；工坊卡片文案随开关切换（关掉时不再承诺「可以把文档收进知识库」）。
- **文案对齐**：`.env`、`.env.example`、`docs/方案设计文档.md` §14.4 / §14.6 里
  「声明性、无运行时分支读它」的表述全部改掉。
- 不新增接口与数据表；`/kb/*` 仍无条件注册 —— **它不是权限位**。

## Capabilities

### New Capabilities

（无。本变更不引入新能力，只把已交付能力的开关语义补成真的。）

### Modified Capabilities

- `knowledge-retrieval`: 取材方式与「本次可用工具集合」多一个前提 —— 本部署启用了知识库能力；
  开关关闭时进度第一条不得预告「检索你的知识库」。
- `private-knowledge-base`: 新增两条需求 —— 「功能开关决定这条路可不可见，它不是权限位」
  与「开关值必须由后端下发给前端」。

## Impact

- **后端 5 文件**：`app/llm/kb/tools.py`（开关落点）、`app/llm/search/agent.py`（`describe_step`
  带开关）、`app/llm/search/{tavily,noop}.py`（两处 `initial_step` 调用点）、
  `app/api/v1/routes/health.py`（只增一个字段，无签名破坏）。
- **前端 7 文件**：`types/api.ts`、`store/useAppStore.ts`、`app.ts`、
  `pages/{hall,mine,workshop}/index.tsx`、`constants/copy.ts`。
- **测试 5 文件**：`test_health_api.py`、`test_kb_tool.py`、`test_search_provider_kb.py`、
  `test_search_agent_kb.py`、`conftest.py`（把测试基线钉成「关」，免得本机 `.env` 漏进测试）。
- **文档**：`.env`、`.env.example`、`docs/方案设计文档.md`。
- 无数据表、无依赖、无数据迁移。

## Non-goals（不做什么）

- **不把开关做成权限位**：知识库的八个端点仍无条件注册、直接调用照常响应。
  本期只解决「用户能不能看见这条路」；「没有权限的人能不能调通」由登录态与归属校验承担。
- 不做运行时热切换（开关仍是**启动时读**，改 `.env` 要重启后端）、不做分用户灰度、不引入配置中心。
- 不改开关打开时任何既有页面与链路的行为 —— 开着的部署应当**零变化**。
