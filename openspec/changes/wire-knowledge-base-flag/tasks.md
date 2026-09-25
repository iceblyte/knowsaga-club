# Tasks

> 记账说明：本变更的代码**先落地并实测**，工件是按项目规则（行为变更必须立变更）**补记**的，
> 所以下面所有任务都已是 `[x]`，每条都带当时拿到的验证读数。时序上的偏差不掩盖，写在此处。

## 1. 后端：开关落点与能力下发（TDD：先测后实现）

- [x] 1.1 写测试（跑红）：`backend/tests/test_kb_tool.py` 增「开关关闭时 `build_kb_tool()` 返回 `None`」，
      并在同一条里先断言 `request.has_kb is True`（前提：请求确实带了库，否则这条测试没意义）
- [x] 1.2 写测试（跑红）：`backend/tests/test_health_api.py` 把 `knowledge_base_enabled`
      列入字段完整性断言，并新增一条「如实下发」用例：基线环境必须为 `False`（不许谎报）
- [x] 1.3 写测试（跑红）：`backend/tests/test_search_provider_kb.py` 与
      `test_search_agent_kb.py` 把开关纳入设置前提，并新增「开关关 ⇒ 进度名不得预告检索知识库」
- [x] 1.4 实现：`backend/app/llm/kb/tools.py` 的 `build_kb_tool()` 开头判开关，关闭即 `return None`；
      模块头写明「这是 D7 的实现点、唯一构造入口」与「它不是权限检查」
- [x] 1.5 实现：`backend/app/llm/search/agent.py` 的 `describe_step(request, settings)` 增形参，
      `can_search_kb=request.has_kb and settings.knowledge_base_enabled`
- [x] 1.6 实现：两处 `initial_step()` 调用点同步 —— `tavily.py` 传 `self._settings`、
      `noop.py` 用 `self._settings or get_settings()`；`base.py` 的 `describe_step` 文档同步
- [x] 1.7 实现：`backend/app/api/v1/routes/health.py` 下发 `knowledge_base_enabled`，
      文档串写明「入口显隐由前端承担，但值由后端给」与「不是权限」
- [x] 1.8 测试基线隔离：`backend/tests/conftest.py` 把 `KNOWLEDGE_BASE_ENABLED` 钉成 `false`
      （本机 `.env` 里是 `true`，不钉的话「默认关」类用例只在本机红/绿）；需要打开的模块走 KB 夹具
- [x] 1.9 跑焦点测试：`tests/test_health_api.py` + `test_kb_tool.py` + `test_search_provider_kb.py`
      + `test_search_agent_kb.py` + `test_config_search.py` ⇒ **63 passed**

## 2. 前端：四处入口显隐 + 卡片文案

- [x] 2.1 `frontend/src/types/api.ts`：`HealthInfo` 增 `knowledge_base_enabled: boolean`，
      注释写明它管的是「要不要让用户看见」
- [x] 2.2 `frontend/src/store/useAppStore.ts`：增 `knowledgeBaseEnabled`（默认 `false`）与 setter，
      注释写明它与 `searchEnabled` 同层（后端能力，不是用户意愿）
- [x] 2.3 `frontend/src/app.ts`：启动探测里回填 `store.setKnowledgeBaseEnabled(...)`，失败不阻塞启动
- [x] 2.4 `frontend/src/pages/hall/index.tsx`：新增 `KB_ATTACH_CHIPS`，按开关过滤出
      `visibleAttachChips`；**保留「追加背景资料」**（它与知识库无关）
- [x] 2.5 `frontend/src/pages/mine/index.tsx`：知识库行按开关显隐；
      ⚠️ 取 store 必须放在 `if (!data)` 提前 return **之前**（hooks 规则）
- [x] 2.6 `frontend/src/pages/workshop/index.tsx` + `frontend/src/constants/copy.ts`：
      两行入口按开关显隐，卡片文案在 `descWithKb` / `descWithoutKb` 之间切换
- [x] 2.7 类型与构建：`tsc --noEmit --skipLibCheck` **EXIT=0**；WeApp / H5 双端构建成功

## 3. 文档与配置文案对齐（红线：文案与实现冲突时改文案）

- [x] 3.1 `.env` 与 `.env.example`：把「后端**没有任何代码分支读它**」整段改成本开关的三处作用面，
      并明写「**不是权限位** —— 端点仍无条件注册」
- [x] 3.2 `docs/方案设计文档.md`：§14.4 那段「截至本次交付…没有任何运行时分支读它」改写为
      「2026-09-25 接线后更新」；§14.6 表格里 `KNOWLEDGE_BASE_ENABLED` 一行去掉「声明性」
- [x] 3.3 `openspec/changes/add-private-knowledge-base/tasks.md` 的 15.3（原「未落地的一处 design 承诺」）
      补注「已由 `wire-knowledge-base-flag` 兑现」，并留原记录作对照

## 4. 真浏览器验收（两条态，实测 DOM 文本计数）

- [x] 4.1 **关闭态**：`.env` 置 `false` → 重启后端（确认新进程启动时间晚于改动）→
      `/health` 实测下发 `knowledge_base_enabled: false`；浏览器（390×844）实测：
      大厅触发资料 chip 后 `上传文档 = 0`、`粘贴网址 = 0`、`追加背景资料 = 1`；
      「我的」页无知识库行；工坊两行入口消失，卡片文案变为
      「多源输入还在路上 —— 网页链接与视频的解析都还没做。」
- [x] 4.2 **打开态（往返）**：`.env` 置回 `true` → 重启后端 → `/health` 下发 `true`；
      浏览器实测大厅 `上传文档 = 1`、`粘贴网址 = 1`、`追加背景资料 = 1`
- [x] 4.3 控制台无 JS 错误 —— 仅 `favicon.ico` 404 与一条 `apple-mobile-web-app-capable`
      的弃用警告（两者都是既有现象）

## 5. 闸门

- [x] 5.1 全量 `pytest`（`CODEBUDDY_SAFE_DELETE_ENABLED=0` + 独立 basetemp 避开 safe-delete 收尾崩）
      ⇒ **EXIT=0，1179 个用例全绿、零 F/E**（上次闸门基线 1172 ⇒ 本变更净增 7 条）；
      另跑一次带 `--cov=app`：**TOTAL 4831 语句 / 330 未覆盖 / 93%**，退出码同为 0。
      ⚠️ 读数取自进度行逐字数点（16×72+27=1179）—— PowerShell 重定向会把末尾的
      `=== N passed ===` 汇总行丢掉，所以退出码 + 进度行才是判据（见 `REDLINES-toolchain.md`）。
- [x] 5.2 `python tools/scan_secrets.py`（`431` 文件，无真实凭证）
- [x] 5.3 `tsc --noEmit --skipLibCheck` EXIT=0；WeApp / H5 双端构建成功
- [x] 5.4 `openspec validate --all --json`：**5 passed / 0 failed**（4 份规格 + 本变更）

## 6. 后续（不在本变更内，故意不勾选）

- 把开关做成**权限位**（端点按开关不注册 / 拒绝）—— 本变更明确不做，边界已写进规格。
- 运行期热切换（现为启动时读，改 `.env` 需重启后端）。
- 分用户灰度或远程配置中心。
