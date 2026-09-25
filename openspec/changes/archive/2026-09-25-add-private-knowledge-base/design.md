# Design

## Context

动机见 proposal.md。这里只列**决定了方案形状**的既有事实（均已核对源码）：

**取材层已经是一个「多工具 Agent」，不是一条写死的链。**
`app/llm/search/` 的形状是：`SearchProvider`（能力位 + `initial_step()` + `gather()`）
→ `run_search_agent()` 的手写有界循环 → `collector.collect_results()` → `SearchResult`
→ `SearchOutcome.as_reference()` 进 Prompt / `serialize_references()` 进 `quizzes.references`。
循环里 `offered` 这个列表决定了绑给模型哪些工具，轮次 / 工具调用次数 / 总时长三个上限、
每次调用的超时外包、进度回调、`ToolMessage` 回喂全部与工具**种类无关**。
⇒ 再加一个数据源的边际成本是「把工具塞进 `offered`」，不是「再写一条链」。

**但有三处按工具名硬编码的分支，加工具时必须同时改**（漏一处的症状都是静默的）：
1. `collector._KNOWN_TOOLS` 是白名单，**未知工具只记一条 warning 然后跳过** ——
   漏改的症状是「命中数永远是 0」，日志里看不出是漏登记。
2. `agent._timeout_for()` 按名字取超时，未知名字回落到 `search_tool_timeout_seconds`。
3. `agent._call_count()` / `agent._describe()` 按名字算条目数与进度文案。

**`SearchResult` 的两个维度已经分好了。** `kind` 是**形态**（`snippet` / `page`），
`source` 是**来源归属**（`user` = 用户自己给的链接，`web` = AI 检索到的）。
`ReferenceCaps.limit_for(kind)` 决定单条截断上限；`as_reference()` 里
`来源：{url}` 直接拿 URL 拼。

**任务表是进程内内存 + TTL。** `task_service` 的模块 docstring 写着「MVP 不做后端持久化」，
`TaskType = Literal["quiz", "report"]`，`TaskRecord` 只有 `quiz` / `report` 两个产出槽，
默认 TTL 600 秒。进程重启即全部丢失。

**错误码里已经有两个正好合用的**：
`4002 UPLOAD_INVALID` 的**语义**是「上传文件不合规」（`exceptions.py` 文件头的表格），
只是 `DEFAULT_MESSAGES` 里那条默认文案是头像场景写的；
`4005 RESOURCE_NOT_FOUND` 的注释明确写着「越权与不存在**故意**返回同一个码」。

**前端上传已有一条可复用的路。** `services/request.ts` 的 `upload<T>()` 包了
`Taro.uploadFile` 与统一信封解包；`utils/avatar.ts` 确立了「平台差异拆成组件那一半 + 工具那一半」
的写法。但 `Taro.chooseMessageFile` 的类型声明里只有 `@supported weapp`，
**H5 没有这个 API**，头像是走 `chooseImage`（两端都有）才幸免的。

## Goals / Non-Goals

**Goals:**

- 知识库成为现有 Agent 循环里的**第三个工具**，不新增第二条检索链。
- 三处既有文件（`base.py` / `agent.py` / `collector.py`）的改动都做成
  **默认关 ⇒ 行为逐位不变**：不传 `kb` 时，工具集合、进度文案、超时、结果采集与今天完全一致。
- 解析状态**持久化**，不依赖内存任务表。
- 「不是你的」与「不存在」在任何知识库接口上不可区分。
- 新依赖与新配置**默认不生效**，不影响未开启该功能的部署。

**Non-Goals:**

- 不做视频解析、不做「链接型文档」（proposal 已列）。
- 不做**章节级出题范围**（原型第 7 屏的「仅第 1-4 章」）：需要保留文档的标题层级结构，
  而当前分块策略是无结构的滑窗；本期不做，也不为它预留字段。
- 不做**题型控制**（原型第 8 屏的「单选 3 / 多选 1 / 判断 1」）：出题链目前没有题型参数的
  控制面，加它等于改核心出题契约。
- 不做文档的多版本 / 增量重解析。
- 不改题量上限（维持 5 题）。

## Decisions

### D1 知识库检索做成第三个工具，塞进现有循环

考虑过三种接入方式：

| 做法 | 否决理由 |
|---|---|
| 新建一条 RAG 链，与检索链并列，出题前各跑一次 | 两条链各有一套轮次 / 超时 / 降级 / 进度文案 / 快照落库，等于把已有的有界性与降级语义全部复制一遍；而且「先检索再联网」的顺序被写死，退回硬编码路由 |
| 由服务端按规则决定（有库就只查库） | 需求明确要 **Agentic 路由**；而且规则永远猜不准「这一题该用库还是该联网」 |
| **作为第三个工具绑给同一次循环（采用）** | 轮次 / 调用次数 / 总时长 / 超时 / 进度 / `ToolMessage` 截断 / 快照落库**全部复用**；模型能自行决定只用其一、两个都用、或都不用 |

代价：`offered` 变长后，模型在一次调用里可选的动作变多，可能多花一次往返。
用既有的 `search_agent_max_tool_calls`（4）与 `search_agent_budget_seconds`（20）兜住，
不新增上限旋钮。

### D2 Chroma：每用户一个 collection（`user_{id}`），库级过滤走元数据

按用户隔离 collection，与最初方案一致。collection 内每条向量携带
`{kb_id, doc_id, chunk_index, filename}` 元数据，检索时强制
`where={"kb_id": <本次指定的库>}`。

拒绝「每知识库一个 collection」：collection 数量会随用户 × 库数增长，
而 Chroma 每个 collection 是一份独立的 HNSW 索引文件，小库多起来之后
文件数与内存开销都不划算；而「每用户一个」在用户量上来之前完全够用。

**检索必须同时满足两个条件**：落在 `user_{本人}` 这个 collection 里、且 `kb_id` 匹配。
两个条件缺任何一个都会造成跨用户或跨库泄漏，所以它们都写在 `store.py` 的**同一个函数**里，
不允许调用方自己拼 `where`。

### D3 解析状态落库，**不复用** `task_service`

⚠️ **这一条推翻了上一轮口头方案**（当时说的是「复用 task_service，`task_type` 加 `'kb'`」）。
读完源码后确认那样做是错的：

| 事实（见 Context） | 后果 |
|---|---|
| 任务表是进程内内存 | 解析完之前重启服务，记录就没了；而文档本身还在，状态无从得知 |
| TTL 默认 600 秒 | 用户上传后隔一夜回来，文档永远停在「解析中」 |
| `TaskRecord` 只有 `quiz` / `report` 两个产出槽 | 文档状态要塞进 `report: dict`，字段名与语义彻底不符 |

改为：**状态存在 `knowledge_documents.status` 上**，前端轮询 `GET /kb/{id}`。
解析仍然跑在后台线程池（**独立于出题的那一个**，理由同 `report_service` ——
解析不该排在出题任务后面等），但它只负责「把状态从 `parsing` 推到 `ready`/`failed`」，
**不持有真相**。

### D4 向量化走 dashscope SDK，不用 OpenAI 兼容端点

百炼的 `text-embedding-v4` 在原生 SDK 里有一个 `text_type` 参数（`document` / `query`），
官方的用法是**入库的文本传 `document`、检索的查询传 `query`**。
OpenAI 兼容端点没有这个概念（OpenAI 的 embeddings API 里不存在对应字段），
走兼容端点等于把这个区分丢掉 —— 而它恰好是影响召回质量的那一项。

所以自写一个约二十行的 `Embeddings` 适配器（`app/llm/kb/embedding.py`）：
`embed_documents()` → `text_type="document"`，`embed_query()` → `text_type="query"`，
两端都带上固定的 `dimension`。

**维度必须固定并配置化**：collection 一旦建好，向量维度就锁死了，
中途换维度不会报错、只会让新写入的向量检不出来。所以 `EMBEDDING_DIM=1024`
是配置项而不是代码里的魔法数，且写进 collection 的元数据以便排查。

**批量大小取 10**（配置项 `EMBEDDING_BATCH_SIZE`）。上游对单次请求的条数有上限 ——
⚠️ 2026-09-24 用真实 key 实测**上限恰为 10**（n=10 通过，n=11 起返
`400 InvalidParameter: it should not be larger than 10`），所以这个默认值**贴住上限、
只能调小不能调大**；超限不是截断，而是整次调用失败。（原判「取一个明显安全的值」
据此收窄为「取到上限」——已同步 `config.py` / `.env.example` 注释。）

### D5 知识库结果用 `source="kb"`，`kind` 仍是 `snippet`

`kind` 回答**形态**，`source` 回答**归属**。知识库返回的是切分后的片段，
形态就是 `snippet`（它绝不是「整页正文」那一类）；归属上它是用户自己的资料，
所以 `source` 加一个取值 `"kb"`，与 `user`（用户当场给的链接）、`web`（AI 搜到的）并列。

这个选择让三件事零成本成立：
- `ReferenceCaps.limit_for("snippet")` 直接适用；
- `quiz-grounding` 里「用户自己给的资料不适用『无关即忽略』」可以直接按
  `source in ("user", "kb")` 判定，不必再引入一个维度；
- `quizzes.references` 的快照天然记录了来源构成，报告链与排查都能看出「这题依据了知识库」。

### D6 知识库片段用伪 URL 承载来源标识

`SearchResult.url` 是必填的，而知识库片段没有 URL。用
`kb://{kb_id}/{doc_id}#{chunk_index}` 填这个位置。

为什么不是「复用文件名」：`collector._dedupe()` 按 URL 去重，
同一份文档的不同片段必须能被区分开 —— 用文件名会把它们合成一条。

为什么不新增字段：`SearchResult` 是 `as_reference()` / `serialize_references()` /
落库 JSON 的共同输入，加字段意味着三处都要跟着改，而伪 URL 在所有既有消费点上
都已经是「一串标识符」的语义。

`as_reference()` 对 `source == "kb"` 单独出一种更可读的形态
（`来源：你的知识库《{文件名}》`），**不动其它 source 的输出格式** ——
既有的 Prompt 契约测试就是按原格式钉的。

### D7 `can_search_kb` 不做成 Provider 能力位

`can_search_web` / `can_read_pages` 之所以是 Provider 的属性，是因为它们取决于
「配了哪个检索服务、有没有 key」。知识库检索不依赖这些：它取决于
**配置里 `KNOWLEDGE_BASE_ENABLED` 是否为真**与**本次请求有没有带库**。

做成 Provider 能力位会立刻造出一个不一致：同一个 Noop Provider，
带库的请求该说 `True`、不带库的该说 `False`。所以它作为
`build_initial_step(..., can_search_kb=...)` 的**入参**，由调用方按请求算好传进来；
`build_initial_step` 保持纯函数（`base.py` 是叶子模块，不 import 配置）。

### D8 Noop Provider 也要能跑知识库检索

`KNOWLEDGE_SEARCH_ENABLED=false` 时 `get_search_provider()` 返回 `NoopSearchProvider`，
而它的 `gather()` 直接返回 `disabled`。**这正是「只用知识库、不开联网」的默认配置**，
不改它的话，用户选了自己的库、上传了解析好，出题时却一条资料都拿不到，
而且日志显示「取材未启用」——看起来完全正常。

所以 `NoopSearchProvider` 增加一个分支：**带库的请求仍走一轮循环，只是没有任何联网工具可绑**。
它需要拿到 `settings`（用来建知识库工具），构造签名因此从 `NoopSearchProvider()`
变为可选的 `NoopSearchProvider(settings=None)`；不传时 `gather()` 保持今天的原样。
既有的 `NoopSearchProvider()` 无参调用与「恒为『理解你的输入』」的断言都不受影响
（那条断言只在不带库时成立，而它测的正是不带库的情形）。

`base.SearchRequest` 新增两个字段以承载这件事：
`kb: KbScope | None`（含 `kb_id` 与 `owner_id`）与
`wants_external` 把 `has_kb` 算进去 —— 因为向量化确实要访问外部网络，
「关掉联网」关的是**公开检索**，不是**一切网络请求**。

### D9 错误码复用 4002 / 4005，不新增

⚠️ **这一条修正了上一轮口头方案**（当时说的是新增 `4003 文档不合规`）。

- 文档格式 / 体积不合规 → **`4002 UPLOAD_INVALID`**，调用时**显式传文案**。
  `4002` 的语义本来就是「上传文件不合规」，只有 `DEFAULT_MESSAGES` 里那条默认文案
  是头像场景写的。新增一个码会让前端多一个分支，而两者对用户是同一件事。
- 知识库 / 文档不存在**或**不属于当前用户 → **`4005 RESOURCE_NOT_FOUND`**，
  用现成的 `resource_not_found()` 构造器。它的注释正是为这个场景写的。

### D10 原文件落盘，与向量库目录分开，都不进静态挂载

上传的原文件保留在 `uploads/kb/{user_id}/{doc_id}{ext}`。理由：
解析失败后要能重试、以后要做预览 / 下载时不必回头改数据模型。

不放在 `uploads/avatars` 那一层：那里是**静态挂载**出去的（头像要能被 `<image>` 直接引用），
而文档是用户私有内容，绝不能被匿名 URL 取到。`backend/uploads/` 下再开一层 `kb/` 即可。

向量库落在 `backend/vectorstore`（配置项 `VECTORSTORE_DIR`），**不在 uploads 下**：
那是 Chroma 的数据库目录，混进用户上传目录会让「清空上传」这类操作产生连带伤害。

### D11 文件名由客户端显式提供，并且只用来做**准入**

服务端判扩展名必须拿到**原始文件名**（`机器学习导论.pdf`），
而 `Taro.uploadFile` 只会把临时路径的最后一段当 multipart 的 filename
（微信端是随机临时名），所以**原始文件名走一个独立的表单字段**，不依赖 multipart filename。

与头像「只信魔数、不看扩展名」的取舍不同，这里**必须**信客户端给的文件名，因为：
`.txt` / `.md` 根本没有魔数；`.docx` 与 `.zip` 是同一个魔数（`PK\x03\x04`）。
文件名只用于**准入判定**（决定收不收、走哪个加载器），
内容是否真的是那种格式由**解析器自己**验证 —— 冒充的 `.pdf` 会在解析阶段
变成 `failed`，不会变成一个「已就绪但内容乱码」的文档。

### D12 前端文件选择器拆成两半，与头像同构

`Taro.chooseMessageFile` 只支持微信端（类型声明里写着 `@supported weapp`），
H5 没有。按 `utils/avatar.ts` 已确立的写法拆：

- `utils/document-picker.ts`：两个分支各取一个文件，**产出一致的
  `{ path, size, name }`**，含取消判定（复用 `isPickCancel` 的判据）与本地体积预检；
- 微信端：`Taro.chooseMessageFile({count: 1, type: 'file', extension: [...]})`，
  文件名与体积都能直接拿到；
- H5：DOM `<input type="file" accept="...">` → `URL.createObjectURL(file)` 作为
  `Taro.uploadFile` 的 `filePath`，文件名与体积从 `File` 对象拿。

页面里不出现任何 `isH5()` 判断。

### D13 出题请求带 `kb_id`，在**建任务之前**校验归属

`POST /quiz/generate` 增加可选 `kb_id`。`submit_quiz_request()` 在
`create_task` **之前**查库并校验归属（越权 / 不存在 → 4005），理由与
`TavilySearchProvider.__init__` 里校验 key 相同：用户该直接看到「这个库不能用」，
而不是拿到一个 task_id、等几秒后看到一个注定失败的任务。

### D14 「从知识库出题」的学习需求由前端构造

`user_input` 有 8 字下限（`MIN_INPUT_LEN`），而原型第 8 屏没有输入框 ——
用户点一下按钮就要出题，知识库名可能只有 4 个字。所以该页提交
`学习「{库名}」中的内容`（≥10 字），它同时充当知识库检索的查询语义。
**不放宽 `MIN_INPUT_LEN`** —— 那条下限服务的是所有入口，为一个页面放宽它
会把校验的边界搞模糊。

### D15 加载器自写，**不**引入 `langchain-community`

原计划用 `PyPDFLoader` / `Docx2txtLoader` / `TextLoader`。装依赖时核对发现：
这三个类都在 **`langchain-community`** 里，而它**不在**本项目的依赖树上，
也不被任何已装包依赖（实测 `importlib.util.find_spec("langchain_community")` → `None`）。
要拿到它们就得再拖进一个体量不小的包，而它们做的事只是
`pypdf.PdfReader` 逐页 `extract_text()` / `docx2txt.process()` / `read_text()`。

**现成件在这两件关键事上还不合用**，而这两件恰好是本层必须守住的：

| 需求 | 现成件的行为 | 后果 |
|---|---|---|
| GBK 编码的 `.txt`（Windows「另存为」的默认编码） | `TextLoader` 只按给定编码硬解，不做兜底 | `UnicodeDecodeError` → 用户看到「这份文件一直解析失败」，而文件本身完全正常 |
| 只有图、没有文字层的扫描件 PDF | `PyPDFLoader` 不校验抽取结果是否为空 | 得到一份「解析成功」但一条也检索不到的空知识库，界面上一切正常 |

所以自己写（`app/llm/kb/loaders.py`，约一百行）：
编码按 `utf-8-sig → utf-8 → gb18030` 依次尝试；抽取结果 `strip()` 后为空即抛
`DocumentParseError`；所有解析库异常归一成同一种，调用方（解析线程）只捕一种。
依赖上**只多 `pypdf` + `docx2txt` 两个**（已在 requirements 里），不引入社区包。

**代价**：以后要支持新格式得自己加一个加载器，不能靠换 loader 类。
考虑到准入清单本来就只收四种格式，这个代价可以接受。
`tests/test_kb_loaders.py` 里的 `.pdf` / `.docx` 样本是**按规范手工构造**的最小合法文件
（避免为测试引入 reportlab），交给真库解析 —— 这样「选对了库但用错了 API」才会暴露。

**实现时补的一条**：`str(DocumentParseError)` 会原样进
`knowledge_documents.error_message`（也就是**给用户看**），所以第三方异常的原文不能进它 ——
日志里记 `BadZipFile: File is not a zip file`，用户看到的是
「这份文件没能解析成功，它可能已损坏或加密」。

### D16 上传接口带可选 `kb_id`，不传则落到「默认库」

原型的「新建知识库」是独立一屏、本期不做，但**入口有三个**（卷轴工坊、大厅「上传文档」、
「我的」），其中大厅那个完全不知道任何库名或库 id。

所以 `POST /kb/documents` 的 `kb_id` 是**可选表单字段**：给了就落到那个库（校验归属），
不给就 `get_or_create_default_base()` —— 一个按 `KB_DEFAULT_NAME`「查找或创建」的库，
改名在详情页。这条路必须是 find-or-create：每次上传都新建的话，用户点三次上传
就会看到三个「我的知识库」。

删除走 `DELETE /kb/documents/{doc_id}`（用冗余的 `documents.user_id` 判归属，
不为拿 `kb_id` 去 JOIN）。越权与不存在同样返回 4005，与其它知识库接口逐位一致。

### D17 「未就绪的库不允许出题」由**前端**承担

原型 05·5 的批注写着「列表展示解析状态，未就绪的库不允许出题」。
后端**不**在 `POST /quiz/generate` 上拒绝「库存在但没有已就绪文档」的请求：

- 取材料已经能区分 `empty_base` 与「没命中」（spec 要求），出题会照常完成，
  只是没有知识库依据 —— 这比「用户等了几秒才被告知库是空的」更符合
  「降级优先于失败」的既有取向；
- 判据已经通过 `GET /kb` 的 `ready_count` 给了前端，按钮置灰是**一次查询就能做对**
  的事；后端再拦一道只会多一个需要对齐的分支。

前端那一组任务里落实（并登记进 `copy.ts`）。

### D18 知识库路由**无条件注册**，不挂功能开关

`auth.dev_router` 是「两个条件同时满足才挂载」的，但知识库这八个端点反过来 ——
一律挂上。理由是两者挂开关的目的不同：

- 调试通道挂开关是为了**让攻击面消失**：一个免密登录端点只要存在就是风险，
  404 是它唯一安全的形态；
- `KNOWLEDGE_BASE_ENABLED` 管的是**代价**，不是权限。它省下的是
  `import chromadb`（实测 1.31s）与那 198 MB —— 而 `store.py` 里对
  `langchain_chroma` 是**惰性导入**，所以开关关着的时候这些端点的常驻成本是零。

按开关注册反而制造一个更糟的失败形态：关掉开关时前端拿到 404，
与「路径写错了」长得一模一样；而「未配向量化凭据」这种情况本来就有一条更准的返回
（上传后文档落到 `failed`，文案说明服务暂不可用）。开关的真实作用面因此是
「要不要让用户看见这个功能」，那一层由此前端的入口与 `copy.ts` 承担。

### D19 上传与重试的响应是「调用前的快照」，终态只由轮询给出

`POST /kb/documents` 与 `POST /kb/documents/{id}/reparse` 返回的 `status`
**不一定**是终态，实测分别是 `pending` 与 `parsing`：

- 上传路径：`_envelope()` 读的是请求会话里那个 ORM 对象，而解析线程写在
  **另一个连接**上（`kb_service` 模块头的「两条职责链」），快照不会跟着变；
- 重试路径：服务层先 `mark_parsing()` + `commit()`，`parsing` 是**故意**写进去的 ——
  重试是用户的一次明确动作，界面该马上有反应，而不是先退回「等待解析」。

这不是缺陷，而是这个接口的语义本身：**响应只承诺「尚未就绪」，终态一律走
`GET /kb/{kb_id}`**。前端因此不需要为「上传响应里恰好是 `ready`」写一条分支 ——
那条分支在真实环境里永远不会走到（解析必然在后台），只在测试的同步解析下出现。
`test_kb_api.py` 把这条契约分两半钉住：响应断言「未就绪」，
再轮询断言「已就绪 + 有片段」。

### D20 系统提示词也要跟着改 —— 不然模型不知道第三个工具存在

这一条是**计划外发现的**：8.6 原本只列了 `agent.py` + `base.py`，但系统提示词的第一节
写着「**你有两个工具**」并逐一列举。它不会报错，只会让结果**静默变差** ——
模型看不到 `kb_search` 的名字，就永远不会调它；而它不调的时候，带库的请求
与不带库的请求在模型眼里毫无区别，于是「用我自己的资料出题」这个诉求
只是名义上接上了线。

改法与理由：

- 标题改成中性（「你可以用到这些工具」），不再声称总数 —— 工具数是**请求级**的
  （联网开关 + 有没有带库），在提示词里写死一个数字迟早会说错；
- 另起一段说明「若【学习需求】里提到 `kb_search`，它也在你可用的工具里，
  用法与边界在那一节说明；**没提到就说明这次没有，不要去调它**」。
  让「不存在的能力」与「这次没有的能力」在提示词层面区分开 ——
  后者会让模型去调一个未绑定的工具，白烧一轮预算；
- Human 消息里的库说明包含**范围**（只有这一个库）与**冲突取向**（与公开来源冲突时以它为准），
  两者都是模型自己权衡不出来的：它不知道这个库的边界，也不知道我们的优先级。

⚠️ 提示词是**行为契约**的一部分，`test_search_agent_kb.py` 里两条用例
（`test_messages_mention_kb_search_only_when_a_base_is_bound`、
`test_human_message_explains_the_kb_scope_and_priority`）把它钉住 ——
以后改这几段文案时用例会先响。

## Risks / Trade-offs

- [本机**没有 `DASHSCOPE_API_KEY`**，建库链的向量化调用无法真实端到端验证]
  → 测试里 embedding 一律注入假实现（与「LLM 一律 mock」同一条红线）；
  真跑端到端时如实报告「embedding 未真实调用」。**不声称建库链已验证**。
  ✅ **2026-09-24 已消解**：用户配好 key 后，最小真实调用（3 次调用全返 1024 维，
  语义区分度 `cos=0.8308` vs `0.5092`）与全链路（真实 embedding → Chroma 落盘 →
  真实检索命中 → 真实 LLM 出题）**均已实测通过**；读数与证据见 `tasks.md` 14.4 / 14.6。
  ⚠️ **单测仍走替身** —— 这是刻意的，不因风险消解而改（单测不许发真实外部请求）。
- [`EMBEDDING_BATCH_SIZE=10` 是保守取值，上游真实上限未实测]
  → 批量小只是慢，批量超限是直接失败，所以宁可慢。
  ✅ **2026-09-24 已实测**：上限**恰为 10**（n=10 通过，n=11 起返 `400 it should not be
  larger than 10`）⇒ 默认值贴住上限，**只能调小不能调大**，已同步三处注释。
- [chromadb 会拖入 `onnxruntime` / `grpcio` / `kubernetes` / `opentelemetry-*`，装完数百 MB]
  → 已与用户确认接受。安装放后台执行，并把实测到的体积与耗时记进当日日志。
  这些依赖只在导入 `chromadb` 时才加载，不开启该功能时无运行期成本。
- [Taro H5 下 `Taro.uploadFile` 传 objectURL 是否可用，未实测]
  → 这是本次唯一「写了但可能不工作」的前端分支。实现后必须在浏览器里真传一次文件，
  不能只看类型检查通过。
  ✅ **2026-09-24 已实测可用**，且这条风险的必要性被印证 —— 真浏览器一跑就暴露两个
  「`tsc` 与双端构建全绿却必现」的 bug：① Taro H5 `uploadFile` 默认 `withCredentials: true`，
  撞上后端 `allow_origins=["*"] + allow_credentials=False` 的 CORS 预检 ⇒ **H5 上传永远失败**
  （既有头像上传走同一个 `upload()`，同样中招）；② `kb-parsing` 漏了挂载首帧请求 ⇒
  轮询死锁，界面永远转圈而**后端请求数为 0**。两者均已修（见 tasks.md 14.5）。
- [知识库片段进 Prompt 会挤占 token 预算] → 复用既有的
  `ReferenceCaps`（单条 600 字符、总量 12000 字符、最多 6 条），
  不为知识库单独放宽 —— 放宽的那一条会直接把 `quiz_max_tokens=4096` 挤爆。
- [模型可能在有知识库时仍然去联网，反之亦然] → 这是 Agentic 路由的**本意**，
  不拦截；但要保证日志里能看出「这次用了哪几个工具」（既有的调用记录已覆盖）。
- [解析线程池与出题线程池并存，极端并发下线程数翻倍]
  → 解析池固定小规模（2 个 worker）并**不排队**（提交即丢弃已满的任务并标记失败），
  理由：解析可以失败重试，不值得为它撑大常驻线程。
- [用户在解析中途删除文档] → 删除时先置状态、再删向量与文件；
  解析完成回写前复查文档是否仍存在，避免把已删除的文档写回库。

## Migration Plan

1. **依赖与配置**：`requirements.txt` 增 6 个包（含版本兼容性注释）；
   `.env.example` 增配置项（`KNOWLEDGE_BASE_ENABLED=false` 打头）；`.gitignore` 增
   `backend/vectorstore/`（`backend/uploads/` 原本就整体忽略，kb 原文件目录已被它覆盖）。
2. **DDL**：新增 `backend/sql/07_knowledge_base.sql`（幂等建表），
   业务库与测试库都要执行。
3. **后端 TDD**：先写测试跑红 → 实现 → 跑绿。顺序上先做「知识库自身」
   （存储 / 服务 / 接口），再做「接进取材链」（三处既有文件的改动）。
4. **回归**：`llm/search/` 的既有测试必须**一行不改**全绿 —— 这是「默认关 ⇒ 行为不变」
   唯一的证据。任何需要改既有测试的地方，都要在提交信息里写明为什么。
5. **前端**：`services/kb.ts` → `utils/document-picker.ts` → 六个页面 → 入口。
6. **闸门**：pytest（带 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 与 `--basetemp`）+
   `tsc --noEmit` + `scan_secrets.py` + H5/WeApp 双构建。
7. **实跑**：起后端 → 浏览器实测「上传 → 解析 → 从库出题」整条路，
   并单独验证 H5 的文件选择分支。

**回滚**：功能默认关闭（`KNOWLEDGE_BASE_ENABLED=false`），把开关关掉即回到今天的全部行为；
数据层是新增两张表与两个新目录，删除它们不影响任何既有表。

## 与项目硬约束 / 原型的对照

- **后端 TDD**：`store` 的隔离过滤、`splitter` 的分块边界、状态机迁移、
  文件准入判定都是可先写测试的纯逻辑；接口层用 `TestClient` + `db_session`。
  向量化与 Chroma 在测试中注入假实现。
- **零视觉漂移**：本次**不修改任何既有页面**，新增页面独立成目录。
  四类入口的对账要给实跑证据（三个入口都能走到知识库页）。
- **密钥**：`DASHSCOPE_API_KEY` 只进根 `.env`；`.env.example` 留空占位；
  提交前跑 `tools/scan_secrets.py`。向量库目录与原文件目录都进 `.gitignore`，
  避免把用户资料提交进公开仓库。
- **接口信封**：全部走既有的 `ok()` / `AppError`，不新增响应形状；
  前端只在 `services/kb.ts` 里解包（沿用 `request()`）。
- **同步文档与共享用例**：`shared/scoring-cases.json` 与本能力无关（不涉及评分）；
  `docs/` 三份文档要更新（需求分析里「文档输入」从 P1 提前、方案设计补 RAG 选型落地、
  开发计划补页面与接口清单）。
- **文案与实现冲突时改文案**：`as_reference()` 对知识库来源的展示、进度第一步的名称
  都由后端下发，前端只渲染（沿用既有约定）。
- **交付页面连入口**：三个入口（卷轴工坊 tab、大厅「上传文档」、我的）与六个页面同批交付。

**与原型的有意偏离（需登记进 `frontend/src/constants/copy.ts` 文件头）**：

| 原型 | 本次做法 | 理由 |
|---|---|---|
| 第 8 屏题量选项含「10 题」「自定义」 | 只提供 ≤5 的选项 | 后端 `MAX_QUESTIONS=5` 是硬上限，用户已明确本期不放宽 |
| 第 8 屏有「题型」控件 | 不渲染 | 后端无题型控制面，加了就是画一个兑现不了的控件 |
| 第 7 屏有「出题范围：仅第 1-4 章」 | 不渲染 | 需要文档结构解析，本期不做（见 Non-Goals） |
| 第 3 屏「前端按 8 秒间隔轮询」 | 默认 2 秒 | 8 秒粒度下用户要空等两轮才看到状态变化；轮询间隔与「规避 60 秒请求上限」无关，那个上限约束的是单次请求时长 |
| 第 3 屏「解析必须分阶段可见」 | 只给一个「解析中」态（阶段进度是前端的不确定动画） | 后端只在数据库里存四态（spec 的显式状态机），**不新增 stage 列**：一个「解析到第几步」的字段只在一次解析内有效，为它加列 + 加迁移的收益远小于把「正在解析」说清楚。失败时给的是**原因**（`error_message`），那才是用户真正需要的诊断 |
| 第 5 屏批注「未就绪的库不允许出题」 | 后端不拦，由前端按 `ready_count` 置灰按钮 | 见 D17 |
| 第 4 屏「网页 / 视频链接」 | 本期不做 | 网页已由「用户给的链接必读」覆盖；视频见 proposal 的 Non-goals |
| 第 6 屏「新建知识库」独立页 | 本期不做 | 用户已选定范围（核心闭环 6 屏）；库名由上传流程里的默认库承载，改名在详情页 |

## Open Questions

无。本机缺 `DASHSCOPE_API_KEY` 是**已知的验证缺口**（见 Risks 第 1 条），
不是待决问题 —— 已与用户确认按「测试 mock + 如实报告」推进。
