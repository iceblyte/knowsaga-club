# Proposal

## Why

需求里承诺过「用户想学什么就输入什么 —— 一句话、一段话，甚至一整个文档」。前两种早已兑现，
**文档这一路一直空着**：出题只能拿模型记忆与公开网页，而企业培训材料、客服知识库、专用题库、
内部文档这类私有资料，模型既不知道也搜不到。而这恰恰是这类应用最有价值的场景。

## What Changes

- **新增私有知识库**：上传 PDF / Word / Markdown，后端异步解析 → 分块 → 向量化 → 存入 Chroma，
  并落库记录知识库、文档及其解析状态。
- **每个用户一个 collection**（`user_{id}`）；上传与检索都校验归属，越权一律拒绝。
- **借现有 Agent 循环接入**：知识库检索成为第三个取材工具，与「关键词检索」「按网址读取整页」
  并列，由模型自主选择。轮次 / 次数 / 超时 / 进度文案 / 资料快照**全部复用现有那条**，
  不新建第二条链。
- 指定知识库时用该库资料出题；**关掉联网开关不影响知识库检索** —— 关的是「主动联网」，
  不是「读你自己的资料」。
- 新增知识库管理页与其入口（卷轴工坊、大厅「上传文档」、我的）。
- 新功能默认关闭（`KNOWLEDGE_BASE_ENABLED=false`）；向量化需新增配置 `DASHSCOPE_API_KEY`。

## Capabilities

### New Capabilities

- `private-knowledge-base`: 自建知识库全链路 —— 上传准入（格式 / 体积）、异步解析与状态机、
  按用户隔离的向量存储、检索契约（条数 / 截断 / 相关性阈值）、删除与失败兜底。

### Modified Capabilities

- `knowledge-retrieval`: 「把两种取材工具同时交给模型」扩为三种（新增知识库检索），
  且知识库检索不受联网开关约束。
- `quiz-grounding`: 明确来自用户知识库的资料属于「用户自己的资料」，不适用「无关即忽略」，
  且优先级高于公开检索结果。

## Impact

- **数据表**：新增 `knowledge_bases` / `knowledge_documents`（`backend/sql/07_*.sql`）。
- **接口**：新增 `/api/v1/kb/*`（建库 / 列表 / 详情 / 改名 / 删除 / 上传 / 文档状态 / 删文档）；
  `POST /quiz/generate` 增加可选 `kb_id`。
- **后端代码**：新增 `app/llm/kb/**`、`app/services/kb_*.py`、`app/api/v1/routes/kb.py`；
  改 `llm/search/{base,agent,collector}.py`（各加一个可选口子，默认关 ⇒ 行为不变）。
- **前端**：新增 `services/kb.ts`、`utils/file-picker.ts` 与 6 个页面；改 `app.config.ts` 路由、
  `types/api.ts` 与 `constants/copy.ts` 的 `SourceType` 增 `'kb'`。
- **配置 / 依赖**：`.env.example` 增 6 项；`.gitignore` 增向量库目录；`requirements.txt` 增 6 个包。
- **文档**：`docs/需求分析文档.md`、`docs/方案设计文档.md`、`docs/MVP开发计划.md`。

## Non-goals（不做什么）

- **不做视频解析**；**不做链接类文档** —— 已有的「用户给的链接必读」已覆盖，不重复造。
- 不做文档内容的前端预览 / 在线编辑；不做知识库分享与协作。
- 不做增量重解析与文档版本管理：改文件 = 删除后重传。
- 不改题量上限（维持 5 题）、不改判题 / XP / 金币 / 勋章 / 报告链路。
- 不新建第二条检索链路；不改原型 8 屏之外的任何页面。
