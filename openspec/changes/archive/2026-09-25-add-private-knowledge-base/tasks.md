# Tasks

## 1. 依赖与配置

- [x] 1.1 `backend/requirements.txt` 增 6 个包（`chromadb` / `langchain-chroma` / `langchain-text-splitters` / `pypdf` / `docx2txt` / `dashscope`），每项写明用途与版本兼容性核对结论；装进 `backend/.venv`，记录实测体积与耗时
- [x] 1.2 `backend/app/core/config.py` 的 `Settings` 增 `knowledge_base_enabled`（默认 `False`）等字段与派生属性，配套单测钉住「默认关闭」与 `has_embedding_key` 的判定
- [x] 1.3 `.env.example` 增知识库配置段（全部带注释，开关默认 `false`），`.gitignore` 增 `backend/vectorstore/` 与 `backend/uploads/kb/`；跑 `python tools/scan_secrets.py` 确认新模板不含真密钥

## 2. 数据表

- [x] 2.1 写 `backend/sql/07_knowledge_base.sql`：`knowledge_bases` + `knowledge_documents` 两张表（幂等建表，带索引与注释），字段含解析状态、片段数、失败原因
- [x] 2.2 用 `scripts/apply_sql.py` 在**业务库与测试库**各执行一次，并用 `SHOW COLUMNS` 复核两表结构与索引

## 3. 向量化与分块（先测后写）

- [x] 3.1 写 `backend/tests/test_kb_embedding.py`：批量切分（超过 batch 上限时分多次调用）、`embed_documents` 用 `document`、`embed_query` 用 `query`、上游异常向上抛 —— 跑红
- [x] 3.2 实现 `backend/app/llm/kb/embedding.py`（`Embeddings` 适配器 + 批量上限 + 维度固定），上述测试跑绿
- [x] 3.3 写 `backend/tests/test_kb_splitter.py`：空文本、超长单段、中英混排、片段元数据（序号 / 文档标识）—— 跑红
- [x] 3.4 实现 `backend/app/llm/kb/splitter.py`（`RecursiveCharacterTextSplitter` + 中文分隔符），测试跑绿

## 4. 文档加载与上传准入（先测后写）

- [x] 4.1 写 `backend/tests/test_kb_loaders.py`：四种扩展名各自的加载器选择、大小写与多点文件名、不支持的扩展名被拒、抽取结果全空白时判失败 —— 跑红
- [x] 4.2 实现 `backend/app/llm/kb/loaders.py`（`pypdf` / `docx2txt` 直连 + 编码兜底 + 扩展名准入），测试跑绿
      ⚠️ **偏离原计划**：原写「`PyPDFLoader` / `Docx2txtLoader` / `TextLoader` 三者」，
      但那三个类都在 `langchain-community` 里而它不在依赖树上，且不做编码兜底、
      不校验空抽取结果 —— 改为自写（design D15）。

## 5. 向量库存储层（先测后写）

- [x] 5.1 写 `backend/tests/test_kb_store.py`：写入后能按 `kb_id` 检索到、**跨用户与跨库都检不到**、按文档删除后不再命中、删库清空 —— 跑红（用临时目录 + 假 embedding）
- [x] 5.2 实现 `backend/app/llm/kb/store.py`（collection 命名、元数据写入、唯一的「带隔离过滤的检索」函数、按文档/按库删除），测试跑绿
      ⚠️ 实测两处与文档不符，已按实测写：`Chroma.delete()` **只收 `ids` 不收 `filter`**，
      按元数据删除要走 `where=` 或先 `get(where=)` 取 id 再删；空 `add_texts` 会抛
      `ValueError`（上层「一个片段都没切出来」须判解析失败，不能在这里炸 500）。
      ⚠️ 另修一个真 bug：重新解析时片段数变少会**残留旧片段**（`add_texts` 是 upsert）
      ⇒ 写入前先按 `doc_id` 清空该文档的旧向量。

## 6. 知识库数据层与服务（先测后写）

- [x] 6.1 写 `backend/tests/test_kb_repository.py`：建库 / 列库 / 取库（含归属过滤）/ 文档增删查 / 计数 —— 跑红
- [x] 6.2 实现 `backend/app/services/kb_repository.py`，测试跑绿（20 项）
- [x] 6.3 写 `backend/tests/test_kb_service.py`：上传（准入 / 落盘 / 建记录）、异步解析的状态迁移（`pending→parsing→ready`、失败路径）、删除的连带性、向量化不可用时判失败而非「已就绪」—— 跑红
- [x] 6.4 实现 `backend/app/services/kb_service.py`（含独立解析线程池，2 个 worker，池满即失败）与 `backend/app/services/kb_tasks.py` 的注册/收尾，测试跑绿（41 项）
      ⚠️ **顺手修了一个既有缺陷**：`exceptions.upload_invalid()` 只收 `detail`（**只写日志、
      不返回给前端**），所以任何「显式传文案」的写法都会静默落空，用户拿到的是
      `DEFAULT_MESSAGES` 里那条**给头像写的**文案（「头像不合规，请换一张图片」）。
      已改为 `upload_invalid(message=None, detail=None)`，并保留 `detail=` 的既有调用点
      （`utils/image_check.py`）行为不变。
      ⚠️ **加载器文案分了两层**：解析库抛出的第三方异常原文（`BadZipFile: File is not a
      zip file`）**不再进** `DocumentParseError` —— 那个消息会原样落到
      `knowledge_documents.error_message`（给用户看）。改为日志记细节、用户看
      「这份文件没能解析成功，它可能已损坏或加密」。
      ⚠️ **新增 `app/models/common.py`**：`UtcDatetime` 原本长在 `models/archive.py`，
      知识库也要用它，但「知识库 import 档案」是方向错误的依赖，故上提一层。
      ⚠️ 测试侧教训（已写进 `_doc_row` 的 docstring）：解析线程写在**另一个连接**，
      而 `db_session` 的身份映射里还留着上传时那个对象 —— `expire_on_commit=False`
      加「无活动事务时 rollback 不触发过期」，`session.get()` 会**命中缓存不发查询**，
      于是断言读到上传那一刻的 `pending`。读后台写入必须**另起会话**。


## 7. 知识库接口（先测后写）

- [x] 7.1 写 `backend/tests/test_kb_api.py`：建库 / 列表 / 详情（含文档）/ 改名 / 删库 / 上传 / 重试 / 删文档；**越权与不存在返回同一个 4005**；格式与体积不合规返回 4002 且文案不是「头像」—— 跑红（33 项）
- [x] 7.2 实现 `backend/app/api/v1/routes/kb.py` 并注册进 `app/api/v1/router.py`，测试跑绿
      ⚠️ **路由无条件注册**，不像 `auth.dev_router` 那样挂在开关上 —— 理由写在 `router.py` 的
      注释里（开关管的是 chromadb 的加载代价，不是端点存不存在），并记进 design D18。
      ⚠️ 顺手清掉两处笔误：`_parse_kb_id()` 里重复的局部导入，以及一段自相矛盾的
      docstring（原文先写「不必报 4000」又写「按 4000 拒绝」，实际口径是非数字 → 4000）。
      ⚠️ 测试侧一条**实测出来的契约**（已写进用例 docstring）：上传/重试的响应是
      **调用前的快照**（取的是请求会话里那个对象，而解析线程写在另一个连接上），
      所以它给的是 `pending` / `parsing`，终态只能由 `GET /kb/{kb_id}` 轮询得到。
      一开始断言成 `ready` 的两条用例因此失败 —— 那是断言错了，不是实现错了。

## 8. 接进取材链（三处既有文件，默认关 ⇒ 行为不变）

- [x] 8.1 写 `backend/tests/test_kb_tool.py`：`kb_search` 工具的返回形状（`results` 列表）与失败形态（返回错误体而非抛异常）—— 跑红
- [x] 8.2 实现 `backend/app/llm/kb/tools.py`（`StructuredTool`，名字与描述要让模型知道「只在用户自己的资料里找」），测试跑绿
- [x] 8.3 写 `backend/tests/test_search_collector_kb.py`：kb 工具的返回被采集、`.docx` 之外的伪来源不混入、**并补一条「未登记进白名单 ⇒ 命中数为 0」的回归用例** —— 跑红
- [x] 8.4 改 `backend/app/llm/search/collector.py`：把 kb 工具名加进 `_KNOWN_TOOLS`、加 `_collect_kb()`、`_source_for()` 认伪 URL，测试跑绿
- [x] 8.5 写 `backend/tests/test_search_agent_kb.py`：带库时 kb 工具进 `offered`、`use_search=false` 时仍可用、kb 调用受同一套次数/时长上限约束、`kb_search` 的进度文案 —— 跑红
- [x] 8.6 改 `backend/app/llm/search/agent.py` 与 `base.py`：`SearchRequest` 增 `kb` 与 `has_kb`、`wants_external` 计入 kb、`build_initial_step` 增 `can_search_kb`、`run_search_agent` 增可注入的 `kb_tool`、`_describe`/`_call_count`/`_timeout_for` 补 kb 分支，测试跑绿
- [x] 8.7 写 `backend/tests/test_search_provider_kb.py`：Noop Provider 在带库时仍走一轮、不带库时行为与今天逐位一致、`initial_step` 在带库时是「检索你的知识库」—— 跑红
- [x] 8.8 改 `backend/app/llm/search/noop.py` 与 `__init__.py` 的 provider 工厂（把 settings 传进 Noop），测试跑绿
- [x] 8.9 跑 `backend/tests/test_search_*.py` 全量：**既有用例必须一行不改全绿**，作为「默认关 ⇒ 行为不变」的证据；`as_reference()` 对非 kb 来源的输出格式逐字未变

  ⚠️ 偏离登记（计划外的一处改动 + 一处拆分）：
  - **`app/prompts/search_prompt.py` 也被改了**，原计划 8.6 只写 `agent.py` + `base.py`。
    理由：系统提示词里写着「**你有两个工具**」，而带库时实际会绑三个 —— 那句会让模型
    完全不去想 `kb_search`（它只能按提示词判断有什么可用）。现在改成「你可以用到这些工具」，
    并另起一段说明「若【学习需求】里提到 `kb_search`，它也在可用集合里；没提到就别调」。
    Human 消息侧补了库的作用域（只有这一个库）与**冲突取向**（以你的资料为准）。
  - **Noop 那两条用例拆到独立文件**（`test_search_provider_kb.py`）：原计划放在
    `test_search_agent_kb.py`。理由：那份文件测的是**循环的形状**（注入 llm + 工具替身），
    而 Noop 是一个 **Provider**（要验 `initial_step`、工厂接线、无参调用的兼容性）——
    两件事的夹具与关注点不同，混在一起会让「既有契约逐位不变」这条证据变模糊。
  - 合计 4 份新测试文件 / 49 条用例跑绿，`test_search_*.py` 全量 **181 passed**。

## 9. 出题链接入（先测后写）

- [x] 9.1 写 `backend/tests/test_quiz_kb.py`：`POST /quiz/generate` 带 `kb_id` 时知识库作用域被带进 `SearchRequest`、库不存在或越权在建任务**之前**返 4005、不带 `kb_id` 时请求与今天完全一致 —— 跑红
- [x] 9.2 改 `backend/app/services/quiz_service.py`（`submit_quiz_request` 增 `kb_id`、`_build_search_request` 增 `kb`）与 `backend/app/api/v1/routes/quiz.py`（请求体增 `kb_id`），测试跑绿

## 10. 前端接口层与工具

- [x] 10.1 `frontend/src/types/api.ts` 增知识库相关类型，`frontend/src/constants/copy.ts` 增知识库文案段与**原型偏离登记**（题量上限 / 题型 / 出题范围 / 轮询间隔）
- [x] 10.2 写 `frontend/src/services/kb.ts`（八个接口，走既有 `request()` 与 `upload()`），`tsc --noEmit` 通过
- [x] 10.3 写 `frontend/src/utils/document-picker.ts`（微信端 `chooseMessageFile` / H5 `input[type=file]` 两分支产出一致结构，含取消判定与本地体积预检），`tsc --noEmit` 通过

## 11. 前端页面（六屏）

- [x] 11.1 `pages/workshop/kb-list/index`（我的知识库）+ 四个配套文件
- [x] 11.2 `pages/workshop/kb-detail/index`（知识库详情：文档列表 + 删除 + 从本库出题）
- [x] 11.3 `pages/workshop/kb-upload/index`（上传文档：选择文件 + 最近上传 + 上传中态）
- [x] 11.4 `pages/workshop/kb-parsing/index`（文档解析中：分阶段展示 + 轮询 + 失败态可重试）
- [x] 11.5 `pages/workshop/kb-source/index`（选择输入方式：四种输入源平铺，本期只开放「文档」与「一句话」）
- [x] 11.6 `pages/workshop/kb-generate/index`（从知识库出题：来源 / 题量 ≤5 / 难度 / 联网开关 + 生成）

## 12. 入口（页面必须有路到达）

- [x] 12.1 `frontend/src/app.config.ts` 注册六个新路由，逐个确认同名目录的四件套都存在（缺一个会让 build 直接失败）
- [x] 12.2 卷轴工坊页 `pages/workshop/index` 增「知识库」入口
- [x] 12.3 大厅 `pages/hall/index` 的「上传文档」chip 从占位 toast 接到真实页面
      ⚠️ 实测口径：这三枚 chip **只在输入框非空时渲染**（空态那一行是「热门问题」），
      所以验它必须先往输入框打字 —— 空态页面上根本搜不到「上传文档」这个字符串。
- [x] 12.4 「我的」`pages/mine/index` 增知识库入口

## 13. 文档同步

- [x] 13.1 `docs/需求分析文档.md`：把「文档输入」从 P1 移到本期范围，补知识库的需求条目
- [x] 13.2 `docs/方案设计文档.md`：补 RAG 选型落地（框架 / 向量库 / embedding / 分块 / 隔离粒度）与接口清单
- [x] 13.3 `docs/MVP开发计划.md`：补页面与接口清单、新增配置项、以及本次的原型偏离登记

## 14. 全量闸门与实跑验证

- [x] 14.1 跑 `pytest`（带 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 与 `--basetemp`）全量，记录 passed 数与覆盖率
      **实测：1172 passed / 0 failed（1 warning，anyio 弃用告警），428.36s；覆盖率 93%（TOTAL 4812 stmts / 333 miss）。**
      ⚠️ 第一轮全量跑出 **3 条红**，全在 `tests/test_db_mapping.py`：加了两张知识库表后
      那里的表数量（10→12）、表名集合、外键数（14→17）三处期望值没同步。那是**过期断言**，
      不是实现缺陷 —— 已补上两张表与三条 FK，并把 `knowledge_bases` / `knowledge_documents`
      加进索引断言与 `created_at/updated_at` 参数化列表。修完 22 passed。
      ⚠️ 教训：先前那次 306 passed 是**子集**（quiz/kb/search/users），根本没跑到
      `test_db_mapping.py` ⇒ **只有全量才算闸门**。
- [x] 14.2 跑 `tsc --noEmit` 与 `tools/scan_secrets.py`，两者都零失败
      **实测：`tsc --noEmit --skipLibCheck` EXIT=0（输出为空）；`scan_secrets.py` EXIT=0。**
- [x] 14.3 H5 与 WeApp 双端构建，记录产物大小
      ⚠️ **顺序有讲究**：两个平台共用 `frontend/dist`，后构建的覆盖先前的。本轮在
      「WeApp 构建之后」又改了两处前端代码 ⇒ WeApp 产物作废，**必须重跑**，否则记的是旧产物。
      **实测（含全部改动）：WeApp 145 文件 / 620,029 B（0.59 MB），`kb-*` 四件套 ×6 页 = 24 个产物，
      无 `index.html`（确诊是 weapp 产物）；H5 `index.html` + `js/` + `css/`，js 路径 4.3 MiB，
      仅有 asset-size 体积告警、无错误。最终让 H5 作为最后一次构建，`dist` 停在 H5。**
- [x] 14.4 起后端，浏览器实测「上传文档 → 解析完成 → 从知识库出题」整条链路，量 DOM 与接口响应作证据
      **第一轮（无 key）**：实测到「解析」为止且为失败态（原因见 14.6），当时「解析完成 → 出题」
      那半条本地做不到。已取证据：`OPTIONS` + `POST /api/v1/kb/documents` 200 → 落库
      `knowledge_bases(id=1,user_id=22,"我的知识库")` + `knowledge_documents(id=1,ext=md,size_bytes=1981,status=failed,error_code=embedding_unavailable)`
      → 磁盘 `backend/uploads/kb/22/1.md`(1981 B) → `GET /api/v1/kb/1` 200 → 页面渲染失败态。
      另实测四态文案与闸门：列表「共 1 个知识库 / 1 份文档 · 0 份已就绪 / 等待」；
      详情「尚未就绪 / 1 份文档 · 0 个知识块 / 解析失败 · 知识库服务暂时不可用，请稍后再试」；
      出题页题量**只有 3 题 / 5 题**、主按钮 `disabled === true` 且带拦截说明。
      **第二轮（配好 `DASHSCOPE_API_KEY` 后，整条链路全部走通）**：
      · 上传新文档 → `OPTIONS` + `POST /kb/documents` 200 → 落库 `doc=2`(1890 B, ext=md)
      · 后端日志：`知识库写入：user=22 kb=1 doc=2 chunks=2` → `知识库解析完成：doc=2 chunks=2`
      · `backend/vectorstore/` 由不存在到落盘：`chroma.sqlite3` 212,992 B +
        HNSW `data_level0.bin` 423,600 B / `header.bin` / `length.bin`
      · DB 终态：`status='ready'`、`error_code=''`、`chunk_count=2`
      · UI **首次渲染 ready 态**：「文档已就绪 / 这份文档可以用了 / 已切分 2 个知识块 / 去出题」；
        详情页顶部由「尚未就绪」翻成「已就绪」，文档行「2 块 · 1.8 KB · 已就绪」，出题闸门提示消失
      · 出题链：`POST /quiz/generate` 200 → 真实 `POST https://api.deepseek.com/chat/completions` 200
        → `知识库检索：user=22 kb=1 top_k=4 命中=2`（共 2 次）→
        `取材结束：provider=tavily reason=done rounds=2 calls=2 hits=2` →
        `出题链：第 1 次尝试（json_mode）成功，题量 5`
      · 产物《咖啡豆烘焙入门闯关》：3 单选 + 1 多选 + 1 判断，覆盖知识点 5 条
        （烘焙阶段与一爆 / 烘焙度分类 / 发展阶段与风味平衡 / 养豆与排气 / 常见误区辨析）
        —— 逐条对应测试文档的章节标题，证明**知识库内容真的进了出题链**
      · 首题逐字来自文档：「咖啡豆烘焙过程中，一爆通常发生在哪个温度区间？」
        正确项 `C 约 196°C 到 205°C`（原文即「一爆通常发生在 196°C 到 205°C」）
      · 独立复核（不经 HTTP，直接调 `llm/kb/store`）：`count_chunks(user=22,kb=1)=2`、
        `stored_embedding_dim(22)=1024`、`count_chunks(user=1)=0`（跨用户隔离）、
        `kb_id=999` 检索命中 0（跨库隔离）；真实检索「烘焙的三个阶段」→ chunk_0 距离 0.1425、
        「养豆一般要多久」→ chunk_1 距离 0.5533
      · 浏览器控制台除一条 `apple-mobile-web-app-capable` 弃用告警外**零错误**
- [x] 14.5 单独验证 H5 的文件选择分支（`Taro.uploadFile` + objectURL），并如实记录是否可用
      **可用，且本轮在这里挖出并修掉两个真 bug（都不在单测覆盖范围内）：**
      1. **上传必失败（CORS）**：Taro H5 的 `uploadFile` 把 `withCredentials` 默认成 `true`，
         而后端是 `allow_origins=["*"] + allow_credentials=False` —— 带凭证的响应不允许回
         `Allow-Origin: *`，浏览器在预检就拒（`OPTIONS` 返 200 也没用）。现象是控制台一句 CORS、
         界面回落「上传没成功，请重试」。**这不是本次新引入的**：现有头像上传走同一个
         `upload()`，H5 侧同样中招。修法是在 `sendUpload` 显式传 `withCredentials: false`
         （登录态走 `Authorization: Bearer`，不依赖 cookie，所以语义正确、且只影响 H5）。
      2. **解析页死锁**：`kb-parsing` 的轮询挂在 `shouldPoll` 上，而它要求 `page === 'ready'`，
         那个状态只有 `load()` 自己会写 —— 而页面**没有任何一处做首次加载**。于是 `load()`
         永不执行，界面永远停在初始 loading（看着就是个正常转圈），后端请求数为 0。
         修法是补一个挂载即 `void load()` 的 effect。
      **判据**：文件选择器真的弹出、`MD / .tmp_kb_sample.md / 1.9 KB` 正确（本地 1981 B 核对一致）、
      上传后 URL 跳到 `kb-parsing?kb_id=1&doc_id=1`、后端出现 `POST /kb/documents 200`。
      另证：`convertObjectUrlToBlob` 用 XHR GET 读 `blob:` URL 可行；multipart 的 filename 会
      退化成 `file-<时间戳>`（无扩展名）—— 这正是 design D11 要显式传表单字段 `filename` 的原因。
- [x] 14.6 如实记录验证缺口：本机无 `DASHSCOPE_API_KEY`，向量化与 Chroma 的真实调用未端到端验证
      **（该缺口已于同日第二轮闭合；下面保留第一轮原始记录作为对照）**
      第一轮（无 key）：`.env` 里既没有 `DASHSCOPE_API_KEY`，也没有 `KNOWLEDGE_BASE_ENABLED`（默认 `False`）。
      后端日志给出 `知识库解析失败：doc=1 code=embedding_unavailable detail=AppError('[5000] 私有知识库
      还没配置向量化凭据（DASHSCOPE_API_KEY）…')`，DB 里落成 `status=failed / error_code=embedding_unavailable`，
      而给用户的 `error_message` 是不泄漏内部细节的「知识库服务暂时不可用，请稍后再试」。
      ⇒ 当时的**真缺口**：embedding 的真实 HTTP 调用、Chroma 真实读写与检索、「解析完成 → 从知识库出题」
      这半条链路**一律未端到端验证**；相关单测用的是假 embedding 替身，
      所以「单测全绿」不能推出「真 embedding 可用」。
      **第二轮（用户填好 key 后）逐条闭合**：
      1. 先做**最小真实调用**（不经业务链路）：2 条 `document` + 1 条 `query` 全部返回 1024 维，
         批量(2) 1.14s / 单查询 0.24s；语义自检 `cos(「细胞呼吸有哪几个阶段」, 细胞呼吸段)=0.8308`
         > `cos(同查询, 光合作用段)=0.5092` ⇒ key 有效、向量有区分度
      2. 再走**全链路**：真实 embedding → Chroma 落盘 → 真实检索命中 → 真实 LLM 出题（证据见 14.4）
      3. **子集单测仍用假 embedding 替身**，这是刻意的（与「LLM 一律 mock」同一条红线），
         所以本轮结论只能来自上面两步真实调用，**不能由单测得出**
      ⇒ 仍未验证的项（如实留着）：
      · **多份文档并发解析**：`KB_PARSE_WORKERS=2`（池满即把新文档判失败）只在单测里覆盖，
        没有在真环境同时上传多份大文档压过；
      · **`.pdf` / `.docx` / `.txt` 三种真实文件**：本轮只跑了 `.md`，
        另外三种格式的真实文件解析（`pypdf` / `docx2txt` 的实际行为）未亲测。

## 15. 提交后补验：多份文档并发解析

- [x] 15.1 写探针脚本，用**真后端 + 真 embedding + 真 Chroma** 补掉 14.6 列的第一项缺口
      **实测（`threading.Barrier` 让 6 份文档同时进上传接口，每份约 16000 字 / 35 片段）**：
      2 份进了解析（刚好等于 `KB_PARSE_WORKERS=2`）、4 份**即时**被判 `pool_busy` 失败
      —— 池满即拒、不排队，与 spec 一致；随后对那 4 份串行 `reparse`，**4/4 全部恢复成 `ready`**。
      另证：`KB_PARSE_WORKERS=2` 的语义是「同时最多 2 份在解析」，不是「最多排 2 个」。
      ⚠️ 探针用**新的 `device_id`** 起一个干净账号，不碰既有数据。
- [x] 15.2 修掉并发暴露出的真 bug：chromadb 客户端在并发构造下互相拆台
      **症状**：那 2 份**进了解析**的文档双双失败，`store_failed`，异常分别是
      `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'` 与
      `KeyError: '<vectorstore 路径>'` —— 单份串行上传时从不出现，所以单测与 14.4 的第二轮
      （只有 1 份文档）都发现不了。
      **根因**：`app/llm/kb/store.py` 的 `_open()` 每次调用都新建
      `Chroma(persist_directory=...)`；而 chromadb 的 system 是**按路径缓存的进程级单例**，
      两条线程同时构造时会各自重建、把对方的 system 释放掉。**这是 chromadb 的已知语义，
      不是我们传错参**。
      **修法**：进程级共享客户端 `_shared_client(settings)`（按路径做键 + 双检锁，
      `chromadb.PersistentClient(path=...)`），`_open()` 改为传 `client=` 而不是
      `persist_directory=`（两者在 `langchain_chroma` 里互斥）。
      **验证**：用同一个并发探针重跑 —— 2 份 `ready` / 各 35 片段、0 条 ERROR 日志；
      `tests/test_kb_store.py` + `tests/test_kb_service.py` 全绿。
      ⚠️ 教训（已进 `store.py` 模块头）：**涉及进程级单例的取值组合约束，只有真并发才验得出来** ——
      与「`country` × `search_depth` 互斥」那条是同一类：单测各自都绿，端到端才暴露。
- [x] 15.3 ⚠️ **本变更未落地的一处 design 承诺**（如实登记，已由后继变更兑现）：
      design **D7** 写着「`can_search_kb` 取决于配置里 `KNOWLEDGE_BASE_ENABLED` 是否为真」，
      而本变更交付时 `build_kb_tool()` **不读这个开关** —— 开关只在 `config.py` 里声明、
      由 `kb/__init__.py` 的惰性导入「顺带」管住了 chromadb 的加载代价，
      **取材链与前端入口两侧都没有读它**。
      D18 说「开关的真实作用面是『要不要让用户看见这个功能』，那一层由此前端的入口与
      `copy.ts` 承担」—— 而四个入口当时是**无条件显示**的。
      ⇒ 这两处由后继变更补齐，不在本变更内顺手改（避免让已通过的闸门失效）。
      ✅ **已于 2026-09-25 由 `openspec/changes/wire-knowledge-base-flag/` 兑现**：
      `build_kb_tool()` 开关关掉时返回 `None`、`GET /health` 下发该开关、
      前端四处入口与工坊卡片文案按它切换；并已用浏览器实测两条态（见该变更 `tasks.md`）。
