# Tasks

> 后端每一组都是「先写测试跑红 → 写实现跑绿」。第 0 组是**前置探查**，不产出生产代码 ——
> 它验的是本次最危险的几个假设，假设不成立就要回头改 `design.md`，而不是硬着头皮写下去。

## 0. 前置探查：打通上游（最危险的假设先验）

- [x] 0.1 在 `backend/requirements.txt` 加 `langchain-tavily==0.2.18`（按文件头既有风格注明实测日期与选它的理由），
  在 `backend/.venv` 内安装；验证：① `pip check` 干净；② `python -c "import langchain_tavily"` 通过；
  ③ **`langchain` 与 `langchain-core` 的版本没有被改动**（本次唯一的依赖风险，改了就回退）
  → **已完成**：`pip check` 无破损、import OK；`langchain` 1.4.0 / `langchain-core` 1.6.3 /
  `langgraph` 1.2.11 / `requests` 2.34.2 **全部未被改动**（新增 9 个包都是 `aiohttp` 支的传递依赖）
- [x] 0.2 写一次性探查脚本 `backend/scripts/probe_tavily_tools.py`（不接进出题链），在真实 key 下验证六件事：
  ① DeepSeek `build_chat_model("quiz").bind_tools([TavilySearch, TavilyExtract])` 能返回带 `tool_calls` 的
  `AIMessage`（思考模式已关，不受影响）；② `tavily_search` 真实命中并打印**单条 `content` 的字符数与是否含
  `<chunk n>` 标记**；③ `tavily_extract` 对真实 URL 返回 `raw_content`，打印**单页字符数**与
  **返回体里到底有没有 `title`**；④ 0 命中时的返回形态（是抛异常还是空数组）；⑤ HTTP 错误时的返回形态
  （确认是 `{"error": ...}` 还是异常）；⑥ 同一中文主题在 `country="china"` 与不设 country 下的命中差异。
  **把六条结论原样记进 `docs/MVP开发计划.md`** —— ②③⑤ 三条会直接决定第 5 组的截断常量与错误判定
  → **已完成**：六条结论全部实测拿到，已记进 `docs/MVP开发计划.md` 与 `design.md` 的
  「前置探查结论」。脚本支持 `--only N,M` 补测与 `--out` 自写 UTF-8 报告
  （**不要用 PowerShell 的 `*>`**，会让中文标题产生不可逆乱码）
- [x] 0.3 验证 D12 的前提：读 `_utilities.py` 确认 `requests.post` 未设 timeout 的结论仍然成立
  （已在 design 里记录，此处只需确认版本没变）；验证方式：`git grep -n "requests.post" backend/.venv/Lib/site-packages/langchain_tavily/_utilities.py`
  ⚠️ 若 0.2 与 0.3 的结论与 `design.md` 的 Context 表有任何出入，**先改 design 再继续**
  → **已完成**：`requests.post(f"{base_url}/search", json=params, headers=headers)` 确实无 `timeout`
  （异步路径更显式：`ClientTimeout(total=None)`）。**0.2 有三处与 design 出入，已按本条要求先改 design**：
  extract **有** `title`、`content` 无 `<chunk n>` 只有 `[...]`、单页可达 **74,801** 字符（新增 D14）

## 1. 配置

- [x] 1.1 在 `backend/tests/test_config_search.py` 写测试：断言 `Settings()` 的
  `search_tool_timeout_seconds == 8`、`search_max_results == 5`、`search_snippet_max_chars`、
  **`search_page_max_chars`**（D14 新增：单页正文上限，实测单页可达 7.5 万字符）、
  `search_agent_max_rounds == 3`、`search_agent_max_tool_calls == 4`、`search_agent_budget_seconds == 20`、
  `search_country_default == "china"`、`search_country_default_en is None`，
  且都能被环境变量覆盖（`monkeypatch.setenv` + `get_settings.cache_clear()`）。跑该文件必须**红**
- [x] 1.2 在 `backend/app/core/config.py` 的「联网检索」段补上以上配置项（含注释：超时独立于出题 30s 的理由、
  三个上限为什么必须有、`search_page_max_chars` 为什么必须远小于 `quiz_max_tokens`、
  `search_country_default` 设 `None` 即完全关掉地区偏好）。跑 1.1 转**绿**
- [x] 1.3 在 `.env.example` 的 `TAVILY_API_KEY` 行补申请地址与用途说明，并补上 1.2 新增的可调项占位
  （**只写占位，不写任何真实密钥**）；验证：`git diff .env.example` 里不含形如 `tvly-` 的串

## 2. Provider 契约演进

- [x] 2.1 在 `backend/tests/test_search_provider.py` 写测试：① `SearchRequest` 的字段与默认值；
  ② `initial_step(request)` 三态 —— 有链接 → 「读取你给的网页」；无链接 + 意愿开 → 「联网检索知识」；
  无链接 + 意愿关 → 「理解你的输入」；③ `NoopSearchProvider.gather()` → `degraded=True` 且 `results=()`
  且**不发出任何外部请求**；④ `NoopSearchProvider` 的 `initial_step` 同样遵守三态。跑必须**红**
  → **已完成，但 ④ 按 design 冲突点 14 改写**：④ 的原始要求会让 Noop 显示「联网检索知识」
  而它一次网络都不碰（文案与实现冲突 + 会打破已交付的 `test_quiz_api` 用例）。
  改为：三态由 `build_initial_step(request, can_search_web=…, can_read_pages=…)` 判定，
  **能力算在内**；Noop 无能力 ⇒ 恒为「理解你的输入」。文件共 28 个用例，含
  「`step_name` 已废弃」「`degraded` 是派生属性」「`first_step` 不报「命中 0 条」」等契约断言
- [x] 2.2 改 `backend/app/llm/search/base.py`：加 `SearchRequest`；`SearchProvider` 协议由
  `step_name` 属性 + `search()` 改为 `initial_step()` + `gather()`；`SearchOutcome` 加追溯字段
  （已用轮次 / 工具调用次数 / 是否触顶 / 结束原因）；`SearchResult` 加 `kind`（`snippet`/`page`）与
  `source`（`user`/`web`），并把资料注入上限常量集中在这里。改 `noop.py` 适配新契约。
  跑 2.1 转**绿**
  → **已完成**：新增 `ReferenceCaps`（`from_settings` 单一取值入口）+ `truncate()`；
  追溯字段为 `rounds_used` / `tool_calls_used` / `end_reason`（`limit_hit` 直接从
  `end_reason` 派生，上限名就在字符串里）；`degraded` 改为派生属性
- [x] 2.3 改 `backend/app/services/quiz_service.py` 对 Provider 的两处调用（`_initial_steps` 改用
  `initial_step(request)`，`provider.search(...)` 改用 `provider.gather(request)`），
  先让现有测试全绿（这一步只换契约不改行为）；跑 `pytest backend/tests/test_quiz_service.py` 必须**绿**
  → **已完成**：⚠️ `tests/test_quiz_service.py` **不存在**（原任务写错了路径），实际看护这些行为的是
  `tests/test_quiz_api.py`。新增 `_build_search_request()` 作为第 7 组要接管的接缝
  （当前 `urls=()`、`use_search` 用默认值）。另修一处隐患：原来在出题后把第一步 detail
  硬改成「已提炼 N 个核心概念」，会把「命中 N 条资料」盖掉 → 改用 `outcome.first_step()` 的 detail


## 3. 官方工具的装配（实例级参数）

- [x] 3.1 在 `backend/tests/test_search_tools.py`（新建）写测试，**全部 mock 不联网**：
  ① 未配 key 时工厂拒绝构造且抛明确错误（上游无 key 会在**构造期**抛，必须在我们的工厂里先拦）；
  ② `country` 判定：输入中文 → `"china"`；输入英文 → `settings.search_country_default_en`；
  两处配置都设 `None` → 构造出的工具 `country` 为 `None`；③ `max_results` 来自
  `settings.search_max_results` 而不是模型；④ `include_answer` / `include_raw_content` / `include_images` /
  `auto_parameters` / `exact_match` 一律为假或 `None`；⑤ extract 工具 `format="markdown"`、
  `chunks_per_source` 有值；⑥ 工具实例名分别是 `tavily_search` / `tavily_extract`；
  ⑦ **两个工具实例不跨请求共享**（连续两次不同语种的请求拿到不同的 `country`）。跑必须**红**
  → **已完成**：另加两条 —— ⑧ `handle_tool_error is False`（否则 0 命中会变成一段像正文的字符串，
  见 design D6 第 2 条）；⑨ `looks_chinese` 的中英混排边界（阈值故意定得低，理由写在
  `app/utils/lang.py`）。共 10 个用例
- [x] 3.2 新建 `backend/app/llm/search/tavily_tools.py`：`build_tavily_tools(request, settings)` 返回
  `(search_tool, extract_tool)`；key 显式从 `Settings` 传入（**不依赖环境变量**，与项目「Settings 注入」风格一致）。
  跑 3.1 转**绿**
  → **已完成**。新增 `app/utils/lang.py`（`cjk_ratio` / `looks_chinese`，纯函数）。
  两个上游事实在此处落地：extract 的 `forbidden_params` 只含
  `include_usage / include_favicon / format`，`extract_depth / include_images / query` 是调用级；
  `chunks_per_source` 只存在于 `TavilyExtract`（`TavilySearch` **没有**这个字段，design D2 表格已核）


## 4. 模型自主取材的有界循环

- [x] 4.1 在 `backend/tests/test_search_agent.py`（新建）写测试，注入**按脚本返回 `tool_calls` 的假模型**
  与**假工具**（不联网）：① 模型只调用了被绑定的两个工具之一 → 循环正常收尾；
  ② 模型返回不带 `tool_calls` 的消息 → 立即收尾，不浪费轮次；③ 轮次上限触顶 → 停止并发出一条
  含上限名的 warning 日志；④ 工具调用次数上限触顶 → 同上；⑤ 假时钟越过总时长上限 →
  **不再发起新调用**并带着已有资料收尾（`degraded` 按有无资料判定）；
  ⑥ `on_progress` 回调在每次工具调用前后被调用，且回调文案含动作与数量。跑必须**红**
- [x] 4.2 新建 `backend/app/llm/search/agent.py` 实现有界循环（`bind_tools` + 显式 `for round`，
  **不设 `tool_choice`**），接上 4.1 的全部上限与回调。跑 4.1 转**绿**
- [x] 4.3 在 `backend/tests/test_search_agent.py` 追加：① 单次工具调用超过 `search_tool_timeout_seconds`
  被放弃（注入一个 `sleep` 的假工具），取材继续；② 全部调用都超时 → `degraded=True` 且不抛异常；
  ③ 超时后线程池**没有**无限增长（断言池的 `max_workers` 是有界常量）。跑必须**红**
- [x] 4.4 实现外层超时（模块级有界线程池 + `future.result(timeout=...)`），在代码注释里写明
  「上游 `requests.post` 无 timeout」这个原因与 D12 的残余风险。跑 4.3 转**绿**
- [x] 4.5 在 `backend/tests/test_search_agent.py` 追加：**用户给出的链接必定被读**——
  ① 输入含链接且假模型一次 `tool_calls` 都不返回 → 仍调用了一次 extract（服务端兜底）；
  ② 假模型自己调了同一批 URL 的 extract → 不与兜底结果重复（按 URL 去重）；
  ③ 含链接时 `use_search=False` → 不调用 search，但仍调用 extract。跑必须**红**
- [x] 4.6 在 `agent.py` 实现链接兜底提取与去重。跑 4.5 转**绿**

## 5. 结果采集与清洗

- [x] 5.1 在 `backend/tests/test_search_collector.py`（新建）写测试，用**真实的上游返回形状**（0.2 的结论）：
  ① search 结果映射到 `SearchResult(title, url, snippet, kind="snippet", source=...)`；
  ② extract 结果映射且 `kind="page"`，**标题取值顺序（D6 第 3 条的四级链）** —— 响应里的 `title` →
  `raw_content` 的 markdown 标题行 → URL 的 host → 空字符串（**四种输入各一例**）；
  ③ 含 `error` 键的返回（值是**异常对象**）**不算命中**且记日志；
  ④ `str` 形态的返回（0 命中时 `ToolException` 被 `handle_tool_error` 转成的错误文本）**不算命中**，
  不做任何解析；另需覆盖 `handle_tool_error=False` 时**抛出的 `ToolException` 同样不算命中**；
  ⑤ `content` 含 `[...]`（真实形态）与 `<chunk 1> [...] <chunk 2>`（防御性形态）→ snippet 里两者都不留；
  ⑥ 同 URL 先 search 后 extract → 只保留一条且 `kind="page"`；
  ⑦ 单条 snippet 超 `search_snippet_max_chars` 被截断、**整页超 `search_page_max_chars` 被截断**、
  总量超上限被截断；
  ⑧ **未知返回形状**（缺 `results` 键、`results` 不是列表）→ 只 warning 不抛异常。跑必须**红**
- [x] 5.2 新建 `backend/app/llm/search/collector.py` 实现采集与清洗，截断常量**复用 2.2 的同一组常量**。
  跑 5.1 转**绿**
- [x] 5.3 在 `backend/tests/test_search_provider.py` 追加 `first_step()` 判定测试：
  `degraded=True` → 「理解你的输入」；`degraded=False` 且命中 ≥1 → 名称与 `initial_step` 一致、
  详情含命中条数与整页数量；**`degraded=False` 但 `results=()` → 必须按降级呈现**
  （与现有实现冲突的一条，见 `design.md` 冲突点 6）。跑必须**红**
  → **已在第 2 组提前完成**（契约改动必然连带改它，拆开写只会改两遍）。
  按冲突点 14 落地为：**名称不变、只改详情**。0 命中时详情分两种 ——
  `end_reason == "disabled"`（压根没去取）→「已提炼 N 个核心概念」；
  去取了但没取到 →「未取到可用资料，已提炼 N 个核心概念」。**任何分支都不出现「命中 0 条」**。
  用例：`test_first_step_reports_page_count_and_never_claims_zero_hits`、
  `test_first_step_says_so_when_external_access_failed`
- [x] 5.4 改 `base.py` 的 `first_step()`：把「0 命中」并入降级分支，并补整页数量。跑 5.3 转**绿**
  → **已在第 2 组完成**（同上）。另外「0 命中即降级」现在由 `degraded` 派生属性保证 ——
  它不再是能被人为设错的独立字段

- [x] 5.5 在 `backend/tests/test_search_agent.py` 追加 `get_search_provider` 分支测试：开关关 →
  `NoopSearchProvider`；开关开 + `provider='tavily'` + 有 key → 真实 Provider；
  开关开 + `provider='bocha'` → 抛 5000 且 message 含「尚未接入」；开关开 + 未知名字 → 抛 5000 且含「未知」；
  开关开 + `tavily` 但 key 为空 → 抛 5000（**不静默降级**）。跑必须**红**
- [x] 5.6 改 `backend/app/llm/search/__init__.py`：把 `tavily` 登记进 `_PROVIDERS`，`_PLANNED` 只留 `bocha`，
  并修正「未知 Provider」文案里的可选值列表（`_PLANNED` 与「未知」两个分支的文案**别合**）。跑 5.5 转**绿**

## 6. 资料快照落库

- [x] 6.1 新建 `backend/sql/04_quiz_search_reference.sql`：给 `quizzes` 加
  `search_state VARCHAR(16) NOT NULL DEFAULT 'off'` 与 `references JSON NULL`；
  执行 `python backend/scripts/apply_sql.py backend/sql/04_quiz_search_reference.sql`，
  再用 `DESCRIBE quizzes` 确认两列存在且旧行不受影响
- [x] 6.2 改 `backend/app/db/tables.py` 的 `QuizRecord` 加对应两个映射字段；跑
  `pytest backend/tests/test_db_mapping.py` 确认与 DDL 一致
- [x] 6.3 在 `backend/tests/test_search_grounding.py`（新建）写落库测试：用 `db_session`
  （**禁 `get_session_factory()`**、**别写死 `user_id=1`**）分别落三份题库 ——
  `search_state='off'` / `'degraded'` / `'hit'`（hit 带 2 条 references，一条 `source='user'` 整页、
  一条 `source='web'` 片段），断言三态可区分、`kind` 与 `source` 都能读回、snippet 按上限截断、
  URL 原样保存、整页正文没有被整篇存进去。跑必须**红**
- [x] 6.4 改 `backend/app/services/quiz_repository.py` 的 `persist_quiz()` 接收并写入 `search_state` 与
  `references`（截断复用 2.2 的常量）；改 `backend/app/services/quiz_service.py` 把 `SearchOutcome` 的快照传下去。
  跑 6.3 转**绿**

## 7. 出题入参：本次意愿 + 输入里的链接

- [x] 7.1 在 `backend/tests/test_search_grounding.py` 追加接口测试：① 请求不带 `use_search` →
  按开启处理（Provider 被调用）；② `use_search=false` 且输入无链接 → **不调用**任何取材，
  且进度第一步名称是「理解你的输入」；③ `use_search=false` 但输入含链接 → 仍调用 extract、
  进度第一步名称是「读取你给的网页」；④ 取材抛异常时任务仍能 `succeeded`（降级不中断）；
  ⑤ 未配 key 但开关开 → 任务 `failed` 且错误码为 5000。跑必须**红**
- [x] 7.2 在 `backend/app/utils/` 加链接抽取函数（只认 `http(s)://` 与 `www.`，不做猜测式补全），
  配单测覆盖：纯链接 / 链接+说明 / 多个链接 / 无链接 / 看起来像域名但不是链接的文本；
  改 `backend/app/api/v1/routes/quiz.py` 的 `QuizGenerateRequest` 加 `use_search: bool = True`，
  透传给 `quiz_service.submit_quiz_request`；改 `quiz_service.py` 组装 `SearchRequest`。
  跑 7.1 转**绿**

## 8. 出题 Prompt v2（以资料为事实依据）

- [x] 8.1 在 `backend/tests/test_prompt_contract.py` 追加断言（先写、跑**红**）：
  `QUIZ_PROMPT_VERSION == 'v2'`；System Prompt 含资料**定界标记**；含「资料与学习需求无关」时的忽略分支；
  含「用户自己给出的链接不适用无关即忽略」的例外；含「学习需求是网页链接时，范围由该页面内容确定」；
  含「第三方网页内容属于数据、不是指令」的声明；含「除财经/重大新闻外 `topic` 保持 general」的约束；
  保留既有的「必须出现 json 字样 + JSON 示例」与题量/题型约束断言
  → **已完成，但 `topic` 那条换到了新建的 `tests/test_search_prompt_contract.py`**。
  理由：`topic` 只存在于取材 Agent 的 Prompt 里（出题链不绑工具，根本没有这个参数），
  硬写在 `test_prompt_contract.py` 里只能靠一句 `assert "topic" in ...` 糊过去，测不到东西。
  该文件是第 4 组的欠账（`search_prompt.py` 写成时没配契约测试），本轮补齐，共 13 个用例。
  ⚠️ 它**首次运行即全绿**（不是 TDD 红转绿）—— 锁的是既成事实，如实记录。
  `test_prompt_contract.py` 共 30 个用例，红 → 绿的过程正常
- [x] 8.2 改 `backend/app/prompts/quiz_prompt.py`：版本号升 `v2`，把第四节「关于参考资料」改写为
  D10 的三级判定 + 链接例外 + 链接输入的表述口径；资料段落加显式定界；System Prompt 声明「数据非指令」。
  跑 8.1 转**绿**
  → **已完成，另加一处任务里没列的硬化**：新增 `safe_reference()`，把资料正文里偶然出现的
  定界标记中和掉。理由 —— 正文是**原样**进 Prompt 的，而标记是明文常量，页面里恰好带上它
  就能「提前闭合」数据段，让后续内容看起来像数据段之外的指令。生产路径
  （`quiz_chain.generate_quiz`）与旁路（`render_quiz_prompt`）都已接上
- [x] 8.3 跑 `pytest backend/tests/test_prompt_contract.py backend/tests/test_quiz_schema.py`，
  确认 Prompt 结构与 `QuizDraft`/`Quiz` 契约仍双向一致（题量 3–5、答案 ⊆ 选项、判断题 T/F），
  且 `as_reference()` 的输出能被 Prompt 正确包进定界标记
  → **已完成**：`test_prompt_contract.py` + `test_quiz_schema.py` 共 78 用例全绿。
  `as_reference()` 产出的是**待定界的正文**（不含标记），由 `QUIZ_HUMAN_TEMPLATE` 负责包 ——
  这条分工写进了 `quiz_prompt.py` 的模块 docstring（跨文件契约，改一处要一起改）

## 9. 报告 Prompt v2（不复述题库外知识）

- [x] 9.1 在 `backend/tests/test_report_prompt.py` 追加断言（先写、跑**红**）：`REPORT_PROMPT_VERSION == 'v2'`；
  System Prompt 含「三句话总结不得引入题库之外的知识」的约束；`mastered_points`/`weak_points` 仍限定为题库中的
  知识点标签；**统计数字字段名仍不出现在 Prompt 里**（既有契约不许被破坏）；**第三方原文不进入报告 Prompt**
- [x] 9.2 改 `backend/app/prompts/report_prompt.py`：版本号升 `v2`，在「三、内容要求」补来源受限约束，
  保持 `POINTS_MAX` / `ADVICE_COUNT` 与 `models/report.py` 的数值一致。跑 9.1 转**绿**
- [x] 9.3 确认报告链的「重新生成」路径读的是 `quizzes.references` 快照而不是重新取材
  （写法：在 `report_service` 加一条测试，断言重生成时取材函数**未被调用**）
  → **已完成**：9.1/9.2 两条红灯（版本号 + 来源受限）→ 转绿，其余 4 条存量断言本来就绿。
  9.3 写在 `tests/test_report_api.py`，**两条**：① 运行时探针 —— 把
  `quiz_service.get_search_provider` 换成「一被调用就断言失败」，再走完
  首次生成 + `force=true` 重新生成；② 静态兜底 —— `report_service` 源码里不许出现
  `get_search_provider` / `.gather(` / `SearchProvider` / `SearchRequest` 任何一个
  （运行时那条只覆盖跑到的分支，这条覆盖没跑到的）

## 10. 前端：大厅 pill 与入参透传

- [x] 10.1 改 `frontend/src/store/useAppStore.ts`：加 `useSearch: boolean`（默认 `true`，**内存态，不加 persist**）
  与 `setUseSearch`，注释说明「这是本次召唤的意愿，与后端能力 `searchEnabled` 是两件事」
- [x] 10.2 加前端链接判定纯函数（与 7.2 后端抽取规则**同源**：同一组正则形态），
  放 `frontend/src/utils/` 下与其他工具函数同处；配单测覆盖与 7.2 相同的五个用例
- [x] 10.3 改 `frontend/src/types/api.ts` 的 `QuizGeneratePayload` 加 `use_search?: boolean`；
  改 `frontend/src/pages/summon/index.tsx` 建任务时从 store 读 `useSearch` 随请求下发。
  验证：`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck` 0 error
- [x] 10.4 改 `frontend/src/pages/hall/index.tsx`：把输入框下方 `.between` 行里那只 pill 由只读改为可点开关，
  按 D8 的**四态表**实现（能力 × 意愿 × 是否含链接）；能力关时点击提示「后端未配置联网检索」且不改意愿。
  **不新增元素、不改 `index.scss`**；文案集中进 `frontend/src/constants/copy.ts`
- [x] 10.5 证据：起后端 `:8000` + 构建 H5（**h5 必须是最后一次构建**，否则 `dist` 是 weapp 产物）
  并实跑大厅页，用 `getComputedStyle` / `getBoundingClientRect` 读取 `.between` 行与 pill 的尺寸，
  **与改动前的值逐字段一致**；四态都量（含「输入含链接」的两态，因为那两句文案更长）。
  固定 `search_enabled=true`，只对比同一渲染分支

## 11. 端到端验证（真实检索 + 真实链接）

- [x] 11.1 在根 `.env` 填入 `TAVILY_API_KEY`（**用户提供**）并置 `KNOWLEDGE_SEARCH_ENABLED=true`、
  `KNOWLEDGE_SEARCH_PROVIDER=tavily`；验证 `GET /api/v1/health` 返回 `search_enabled: true`
- [x] 11.2 用 `POST /api/v1/quiz/generate` 对一个**模型训练数据之外的新概念**（如 `Harness Engineering`）出题，
  读 `GET /tasks/{id}` 确认：进度第一步为「联网检索知识 · 命中 N 条资料」（N ≥ 1）、任务成功；
  再查库确认 `quizzes.search_state='hit'` 且 `references` 有内容
- [x] 11.3 中文主题抽验（本次最大的未知数，见 design D3）：用一个**中文**新概念主题重复 11.2，
  记录命中条数与题目质量，结论写进 `docs/MVP开发计划.md`。命中率明显不足时，如实记录并给出
  「是否要另立变更接第二个 Provider」的建议
- [x] 11.4 链接路径：对一个真实网页链接出题，确认 ① 进度第一步为「读取你给的网页」；
  ② 库中该条 `references` 里有一条 `source='user'`、`kind='page'`；③ 题目内容与该页面一致
- [x] 11.5 组合与反例：① 链接 + `use_search=true` → 链接与检索都在；
  ② 链接 + `use_search=false` → 只读链接、不检索；③ 纯文本 + `use_search=false` → 进度为「理解你的输入」
  且任务仍成功；④ 把 `TAVILY_API_KEY` 临时置空后出题 → 任务仍成功、库中 `search_state='degraded'`、
  日志有一条可诊断的失败原因；⑤ 给一个必然读不到的链接（如 `https://example.invalid/x`）→ 降级且不假装读过
- [x] 11.6 抽验题目内容：逐题核对题干 / 答案 / 讲解是否与该次 `references` 中的资料一致，
  **不再出现其他领域的同名概念**（这是本次改动要解决的核心问题）

**第 11 组结论（2026-09-22 实测，完整记录见 `docs/MVP开发计划.md` §12.4）**

- 脚本 `backend/scripts/verify_search_chain.py`，6 个用例 16 条断言，**最终 16/16 通过**。
- 首轮 **15 通过 / 1 失败**，失败的正是 11.4（`link` 用例）：用户贴的链接**一条都没读到**。
  查日志定位到**两个独立原因**，都已修：
  1. 模型把 `search_depth` 选成 `fast`，与实例级 `country` 互斥 → Tavily **400**，4 次调用全废
     → **把 `search_depth` 钉死在实例上**（`tavily_tools.py`，`basic`）；
  2. `tavily_extract` 取整页正文（实测 7.4 万字符）却与 search 共用 8s 超时
     → **新增 `SEARCH_EXTRACT_TIMEOUT_SECONDS=15`** + `agent.py::_timeout_for()` 按工具分派。
- 11.3 的答案：中文主题**命中 10 条**（英文 5 条）—— Tavily 对中文新概念够用，
  **不需要**另立变更接第二个 Provider。
- ⚠️ **11.5④ 的预期被实测推翻**：空 `TAVILY_API_KEY` 时不是「任务成功 + `degraded`」，
  而是 `POST /quiz/generate` **直接 500 / `code=5000`**（构造期 `require_tavily_key()` 抛）。
  这是 design D13 的明确选择（配置错 → 报错，不能静默降级成不联网）。
  真正会走到 `degraded` 的是「key 有效但这次取不到」——`bad_link` 用例即此形态。

## 12. 文档同步

- [x] 12.1 改 `docs/MVP开发计划.md`：§4 决策表第 2 条由「MVP 纯模型出题」改为「已接入 Tavily
  （关键词检索 + 按 URL 抓整页），开关按次生效」；§7.3 补 `use_search`、链接取材与降级时的进度文案；
  §12.1 第 11 条改为「tavily 已接入、bocha 仍未接入」；追加第 0 组与 11.3 的探查/抽验结论
- [x] 12.2 改 `docs/方案设计文档.md`：按该文档既有先例（§2.1 的修订块）在 §2.3 加修订说明
  （联网搜索与「按给定 URL 抓单页」已前置，**文档解析与爬虫仍未前置**），§5.4 补
  「取材走官方 langchain-tavily 的两个工具 + 手写有界循环」。验证：文档里不再有与实现矛盾的表述
- [x] 12.3 区分度检查：全仓搜一遍「不引入 LangChain 搜索工具」「MVP 纯模型出题」「只保留可切换的接口」
  这类旧表述，确认没有残留（`backend/app/llm/search/base.py` 的模块 docstring 里就有一段，
  它描述的是 MVP 决策，本次必须重写）
- [x] 12.4 改 `docs/OpenSpec使用教程.md`：§6 的 `validate --all --strict` 改为 `--all` 并补「别加
  `--strict`」的说明，§5 新增「需求强度词（MUST / SHOULD）」小节（判定表 + 两个坑），§8 速查卡同步。
  **本轮规划期已完成**（冲突点 13）
- [x] 12.5 改 `openspec/config.yaml` 的 `rules.specs`：固化强度判定判据、正文行要求、
  纯说明不写成 Requirement、`--strict` 的工具局限共 5 条。已验证 YAML 可解析、
  `openspec instructions specs --json` 会将其注入。**本轮规划期已完成**（冲突点 13）

## 13. 全量闸门

- [x] 13.1 后端全量：`CODEBUDDY_SAFE_DELETE_ENABLED=0 python -m pytest`（后端目录内执行），
  要求全绿且 `--cov=app` 覆盖率不低于改动前的 93%。注意：退出码 1 但点号全满且无 `failed/error` 摘要
  是收尾清 tmp 撞 safe-delete，不是测试失败
- [x] 13.2 前端类型：`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck`（在 `frontend/` 内执行）→ **0 error**
- [x] 13.3 密钥扫描：`python tools/scan_secrets.py` → 干净；确认 `git status` 里没有 `.env`；
  并确认**没有第三方网页正文**被写进任何被跟踪的文件（含测试 fixture —— fixture 要用手工构造的假数据）
- [x] 13.4 双平台构建：`npm run build:h5` 与 `npm run build:weapp` **都通过**
  （`Conflicting order` 的 message 前缀不算失败，真判据是同段日志有 `✔ Compiled successfully`）
- [x] 13.5 把 11.3 / 11.4 / 11.6 的抽验结论与 13.1–13.3 的结果摘要追加进 `docs/MVP开发计划.md` 的遗留/结论区
- [x] 13.6 规格自检：`openspec validate --all` → 两份 spec **0 警告**。若实现期间改过 spec，
  重跑本条；⚠️ 不要加 `--strict`（它把 RFC 2119 的英文惯例警告判为失败，且无忽略开关，见冲突点 13）

**第 13 组结果（2026-09-22）**

| 项 | 命令 | 结果 |
|---|---|---|
| 13.1 | `pytest -q --cov=app` | **917 通过、0 失败、覆盖率 93%**（不低于改动前基线） |
| 13.2 | `tsc --noEmit --skipLibCheck` | **0 error** |
| 13.3 | `python tools/scan_secrets.py` | **干净**（exit 0，读取 365 个文件）；`git check-ignore` 确认 `.env` 被忽略 |
| 13.4 | `build:weapp` + `build:h5` | **两者 exit 0、日志均含 `Compiled successfully`、`Error:` 0 行** |
| 13.5 | —— | 已写入 `docs/MVP开发计划.md` §12.3 修订 + **§12.4**（新增） |
| 13.6 | `openspec validate --all` | **1 passed, 0 failed**（未加 `--strict`） |

> 说明（13.3 的第三项）：新增测试 fixture 全部是**手工构造的假数据**（假 URL `example.com`、
> 假标题、截断的正文片段），没有任何第三方网页正文被写进被跟踪的文件 ——
> 已按文件逐一核对行数（无 >300 字符的长行）。

