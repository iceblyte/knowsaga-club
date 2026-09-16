# 《知拾冒险社》MVP 开发计划

> 本文档是 `需求分析文档.md` 与 `方案设计文档.md` 的落地执行版，配合 `prototype/` 的 UI 原型使用。
> 所有与原始文档不一致之处，均已在 §2「文档纠偏」中列出并说明原因。
> 状态：**待人工确认后开工**

---

## 1. 已锁定的决策

以下 11 条为人工确认后的最终口径，开发过程中不再变更：

| # | 决策项 | 结论 |
|---|---|---|
| 1 | 页面范围 | **仅 01 核心闭环 + 02 挑战副本 + 03 冒险日志（部分）**，共 20 屏 |
| 2 | 联网检索 | **预留 Provider 抽象层，MVP 走纯模型出题**；后续改一个开关即可开启 |
| 3 | 用户体系 | **纯前端展示，不做真实用户数据**；等级/连击/历史为静态示例值 |
| 4 | 后端持久化 | **不做**，后端无状态（任务表为进程内内存 + TTL） |
| 5 | 生成接口形态 | **异步任务 + 轮询**（对应原型「三步进度可见 / 8s 后出取消入口」） |
| 6 | 分享海报 | **MVP 不做 Canvas 海报**；按钮保留原型位置与样式，改接微信原生转发 |
| 7 | 答错经验值 | **答错 +0，不扣分**（按原型，与需求文档 §2 的「扣除」口径不同） |
| 8 | 历史冒险日志 | **不做**该功能 |
| 9 | 大模型 | **统一 `deepseek-flash`**（`deepseek-chat` 已退役） |
| 10 | 底部标签栏 | **保留完整 5 个 tab**；未开发的 3 个进入统一「即将开放」空态页 |
| 11 | 尺寸换算 | **rpx = 原型 px × 2.259**（原型机身 332px → 真机 750rpx） |
| 12 | 多选部分正确给分 | **固定给 50%**（即 60 × 50% = **30 XP**），与原型 02 显示的 `+30 XP` 完全一致 |
| 13 | `deepseek-flash` 思考模式 | **显式关闭** `thinking: {"type":"disabled"}`（默认开启会导致 `content` 为空、且 `tool_choice` 报 400） |

---

## 2. 文档纠偏（3 处，必须先于编码修正）

### 2.1 模型名退役（阻断级）

方案设计 §7.1 / §7.2 / §7.5 指定 `deepseek-chat`（首选）与 `deepseek-reasoner`（预留）。
经核对 DeepSeek 官方文档（api-docs.deepseek.com，2026-09 抓取），当前可用模型仅为：

- `deepseek-flash` —— 通用档；旧名 `deepseek-v4-flash` 仍作为别名接受
- `deepseek-v4-pro` —— 强推理档；官方 2026-09-14 公告继续提供

官方文档已完全不再列出 `deepseek-chat` / `deepseek-reasoner`。**按原文书写会导致每一次出题请求都失败。**

**处理**：`.env` 中 `DEEPSEEK_MODEL=deepseek-flash`，`DEEPSEEK_MODEL_PRO=deepseek-v4-pro` 作预留。已同步修正 `.env.example`。

### 2.2 `with_structured_output()` 不能使用 `json_schema` 模式

`langchain-openai` 的 `with_structured_output()` 提供三种 method：`function_calling` / `json_mode` / `json_schema`。
注意 1.6.2 的**默认值是 `json_schema`**（不是 `function_calling`）——
不显式传 `method` 就必然失败，所以调用处一律经 `build_structured_llm()` 补齐。
其中 `json_schema` 依赖 OpenAI 的 strict structured outputs（`response_format: {type:"json_schema", strict:true}`），
而 DeepSeek 的 `response_format` **仅支持 `{"type":"json_object"}`**，不支持 `json_schema`。

**处理**：
- 主链使用 `method="json_mode"`（`response_format={"type":"json_object"}`）—— 它的实测一次通过率最高，见 §2.4.2
- 失败时自动降级 `method="function_calling"`（DeepSeek 原生支持工具调用，最多 128 个 function、支持并行调用）
- 两通道**交替**尝试而非顺序撞（理由见 `quiz_chain._attempt_plan`）
- 若后续要开 strict 模式，需 `DEEPSEEK_USE_BETA=true` 把 base_url 切到 `https://api.deepseek.com/beta`（官方标注为不稳定特性）

### 2.3 React 版本

`@tarojs/react@4.2.1` 的 peerDependencies 为 `{ react: "^18" }`（实测 npm 元数据），
而 React 最新稳定版为 19.3.0。**方案设计写的 React 18 是正确的**，锁定 `react@18.3.1` + `react-dom@18.3.1`。

### 2.4 官方额外提示（已纳入设计）

- DeepSeek JSON Output 官方明确说明「**偶发返回空内容**」→ 方案设计 §7.4 的「一级校验：空响应检查」升级为**必需项**，且必须配重试。
- 官方要求使用 JSON Output 时，**prompt 中必须出现 "json" 字样并提供 JSON 示例** → 方案设计 §8.3 的 Prompt 已满足，编码时不得删减。
- 标准端点 `max_tokens` 上限 4096，需保守设置防止结构体被截断。

### 2.4.1 思考模式必须显式关闭（实测发现，**阻断级**）

用真实 Key 对 `deepseek-flash` 实测得到 4 组结果：

| 测试 | 请求配置 | 实测结果 |
|---|---|---|
| A | 不传 `thinking` + `max_tokens=16` | ❌ `content=''`，16 个 token **全部消耗在 `reasoning_tokens`** |
| B | 不传 `thinking` + `tools` + 强制 `tool_choice` | ❌ **HTTP 400**：`Thinking mode does not support this tool_choice` |
| C | `thinking:{"type":"disabled"}` + 强制 `tool_choice` | ✅ 完美返回结构化题目，1.0s |
| D | `thinking:{"type":"disabled"}` + `response_format:json_object` | ✅ 正常返回 JSON，0.95s |
| E | 不传 `thinking` + `response_format:{"type":"json_schema","strict":true}` | ❌ **HTTP 400**：`This response_format type is unavailable now`（印证 §2.2） |

**结论**：`deepseek-flash` **默认开启思考模式**，必须显式传 `thinking: {"type":"disabled"}`。否则：
1. 出题链走 `with_structured_output(method="function_calling")` 时会因为强制 `tool_choice` 直接 400 失败（该通道现在是降级通道，但降级路径同样必须能跑通）；
2. 即便不失败，`content` 也可能为空、推理 token 挤占 `max_tokens` 造成结构截断。

**处理**：`.env` 中 `DEEPSEEK_THINKING=false`；`langchain_factory.py` 需通过 `extra_body={"thinking":{"type":"disabled"}}` 或 `model_kwargs` 透传给 `ChatOpenAI`，并写入单测断言。

### 2.4.2 结构化输出主通道：实测后从 `function_calling` 调换为 `json_mode`

**发现过程**：Phase 1.14 的真实 API 抽验（连续 10 次出题）最终 10/10 可渲染，
但其中 **4 次首轮 `function_calling` 就失败**，报错完全一致：

```
questions.N.knowledge_point  Field required
questions.N.difficulty       Field required
```

即模型在工具调用通道下**系统性地省略每道题的 `knowledge_point`/`difficulty`**
（它会把知识点放在顶层的 `knowledge_points` 里，但不在每道题里重复）。

**量化**：写了 `backend/scripts/compare_output_methods.py`（测量工具，不进 pytest）对比两通道：

| 通道 | 一次通过率（count=6） | 失败形态 |
|---|---|---|
| `function_calling` | **4/6 = 67%** | 空响应 ×2 |
| `json_mode` | **6/6 = 100%** | — |

**处理**：把 `STRUCTURED_OUTPUT_PRIMARY` 调换为 `json_mode`，
`STRUCTURED_OUTPUT_FALLBACK` 设为 `function_calling`。三个理由：

1. 首轮通过率直接决定用户的等待时长与 API 成本 —— 67% 意味着三分之一的请求要多跑一轮；
2. 两者的失效原因**不同**，所以降级通道要保留而不是删掉：若上游某天不再支持
   `response_format=json_object`，只有换通道能救；
3. `json_mode` 的代价（prompt 必须含 "json" 字样与 JSON 示例）已经满足 —— 见 §2.4 第二条。

同时 `tests/test_llm_fallback.py` 增加了 `test_default_channel_is_json_mode` 作为**回归护栏**：
默认值不设断言的话，日后「顺手改回 `function_calling`」不会让任何测试变红。

### 2.5 依赖版本锁定（均为实测最新稳定版）

| 层 | 依赖 | 版本 |
|---|---|---|
| 前端 | Taro | 4.2.1 |
| | React / React DOM | 18.3.1 |
| | Zustand | 5.0.15 |
| | TypeScript | 5.x |
| 后端 | Python | 3.12.4 |
| | FastAPI | 0.141.1 |
| | Pydantic | 2.13.5 |
| | langchain / langchain-core | 1.4.0 / 1.6.3 |
| | langchain-openai | 1.6.2 |
| | pydantic-settings | 2.15.0 |
| | uvicorn | 0.53.0 |
| | pytest / pytest-asyncio | 9.1.1 / 1.4.0 |

---

## 3. 交付范围

### 3.1 本期实现的 20 屏

**01 核心闭环（6 屏，全做）**
1. 启动页 · 卷轴展开（法阵 1.8s 匀速旋转、精灵浮空、文案分阶段）
2. 社团大厅 · 空态（卷轴输入框、0/200 计数、推荐 chip、召唤副本按钮）
3. 社团大厅 · 已输入（8 字激活按钮、`AI 将联网补充` chip 动态切换）
4. 副本召唤中（三步状态卡 + 进度条 + 8s 后取消入口 + 轮询）
5. 副本确认页（标题/摘要/题型构成 3+1+1/知识点 chip）
6. 通关结算（XP 与金币 0.8s 递增动画、正确率环延后 0.3s 绘制）

**02 挑战副本（9 屏，全做）**
7. 单选题 · 未作答（选项等权重、按钮禁用态）
8. 单选题 · 答对（正确项变绿、讲解卡展开、`答对` 印章）
9. 单选题 · 答错（所选标红 + 正确答案标绿、`正确答案 C` 印章）
10. 多选题 · 待提交（选中变蓝、按钮提示已选数量）
11. 多选题 · 部分正确（按比例给分、`部分正确` 金色印章）
12. 判断题 · 未作答（大尺寸对错卡、选项键用 ✓/✗ 而非字母）
13. 讲解折叠态（默认展开、折叠后保留一行摘要）
14. 退出确认（`要离开这个副本吗？` 弹层 + 进度保留文案）
15. 最后一题 · 提交中（提交与报告生成合并、进度 76%）

**03 冒险日志（8 屏中做 5 屏）**
16. 冒险日志 · 主视图（正确率环 + 三小卡 + 百分位条）
17. 三句话总结（三句 + 掌握/薄弱知识点 chip）
18. 复习建议（三条带按钮的可执行建议）
19. 报告生成失败（保留答题数据 + 重新生成）
20. 网络异常（全局断网降级态）

### 3.2 本期不做（含被裁剪的原型屏）

| 原型屏 | 原因 |
|---|---|
| 03 · 分享海报 / 海报生成中 | 需 AppID + AppSecret 调 `getwxacodeunlimit`，已确认 MVP 不做 |
| 03 · 历史冒险日志 | 已确认不做该功能 |
| 04 冒险者档案（9 屏） | P1，含错题本/知识树/数据看板，超出本期范围 |
| 05 卷轴工坊（8 屏） | P1，含 PDF/网页/视频解析与 RAG 私有库 |
| 06 公会社交（6 屏） | P2 |
| 07 会员与设置（8 屏） | P3 |

> 底部标签栏这 5 个入口**全部保留原型的图标与高亮样式**；点击未实现的 `卷轴工坊 / 公会社交 / 我的` 进入一个共用空态页，复用设计规范的「状态图标 + 一句解释 + 一个明确动作」结构，配拾拾精灵。

---

## 4. 目录结构

```text
knowsaga-club/
├─ .env                      # 本地密钥（已 gitignore）
├─ .env.example              # 模板（入库）
├─ docs/
│  ├─ 需求分析文档.md
│  ├─ 方案设计文档.md
│  └─ MVP开发计划.md          # 本文档
├─ prototype/                # UI 原型（唯一视觉来源）
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/v1/routes/{health,quiz,report,tasks}.py
│  │  ├─ core/{config,logging,exceptions,response}.py
│  │  ├─ models/{quiz,report,common}.py        # Pydantic v2 领域模型
│  │  ├─ services/{quiz_service,report_service,scoring_service,task_service}.py
│  │  ├─ prompts/{quiz_prompt,report_prompt}.py # 版本化 v1
│  │  ├─ llm/
│  │  │  ├─ langchain_factory.py   # ChatOpenAI 工厂：模型/温度/超时/重试
│  │  │  ├─ output_schemas.py      # 结构化输出 Schema
│  │  │  ├─ quiz_chain.py
│  │  │  ├─ report_chain.py
│  │  │  └─ search/{base,noop,bocha,tavily}.py  # Provider 抽象层（MVP 只启用 noop）
│  │  └─ utils/{text_cleaner,content_filter,id_generator}.py
│  ├─ tests/
│  │  ├─ conftest.py
│  │  ├─ test_health_api.py
│  │  ├─ test_quiz_api.py
│  │  ├─ test_report_api.py
│  │  ├─ test_scoring_service.py
│  │  ├─ test_quiz_schema.py
│  │  ├─ test_prompt_contract.py
│  │  ├─ test_text_cleaner.py
│  │  ├─ test_content_filter.py
│  │  ├─ test_task_service.py
│  │  ├─ test_llm_fallback.py
│  │  └─ fixtures/                 # 题库/报告 JSON 固定样本
│  └─ requirements.txt
└─ frontend/
   ├─ config/{index.ts,dev.ts,prod.ts}
   ├─ src/
   │  ├─ app.config.ts             # pages + tabBar（5 tab）
   │  ├─ app.tsx / app.scss
   │  ├─ assets/sprites/           # 拾拾/墨墨/铜宝/学者 头像位图
   │  ├─ styles/{tokens.scss,mixins.scss}
   │  ├─ services/{request.ts,quiz.ts,report.ts}
   │  ├─ store/{useQuizStore.ts,useAppStore.ts}
   │  ├─ components/               # NavBar/Btn/Card/Slip/Stamp/OptionItem/…
   │  ├─ constants/{theme.ts,copy.ts,mock.ts}
   │  └─ pages/
   │     ├─ index/                 # 启动页 + 社团大厅
   │     ├─ summon/                # 副本召唤中
   │     ├─ confirm/               # 副本确认页
   │     ├─ quiz/                  # 挑战副本
   │     ├─ settle/                # 通关结算
   │     ├─ report/                # 冒险日志主视图 + 总结 + 建议
   │     ├─ exception/             # 报告失败 / 网络异常
   │     └─ coming-soon/           # 未开发 tab 的统一空态
   ├─ project.config.json
   └─ package.json
```

---

## 5. 分阶段开发步骤

### Phase 0 · 工程骨架与素材（交付物：可编译空壳）

| 步骤 | 内容 | 验收标准 |
|---|---|---|
| 0.1 | 建 `backend/` 工程：`main.py` + `core/config.py`（pydantic-settings 读根目录 `.env`）+ `core/logging.py` + `core/exceptions.py` + `core/response.py`（统一 `{code,message,data}`） | `uvicorn` 起得来 |
| 0.2 | 建 `GET /api/v1/health` | `curl` 返回 `{"code":0,"message":"ok","data":{"status":"healthy"}}` |
| 0.3 | `taro init` 建 `frontend/`（React + TS 模板），锁定依赖版本 | `npm run build:weapp` 产出 `dist/` |
| 0.4 | 从 `prototype/*.html` 抽出 4 个内联 SVG 精灵（拾拾 / 墨墨 / 铜宝 / 学者头像），导出 PNG @2x/@3x 到 `src/assets/sprites/` | 图片在微信开发者工具中正常显示 |
| 0.5 | 落地 `styles/tokens.scss`：按 2.259 倍换算全部设计 token（见 §6） | 与原型逐项对照无偏差 |
| 0.6 | `app.config.ts` 配置 5 个 tab 与页面路由 | tabbar 视觉与原型 01 一致 |

### Phase 1 · 后端 AI 出题链（**严格 TDD**，交付物：可稳定出题的接口）

**先写测试，再写实现。每个模块的测试必须先跑出红灯。**

| 步骤 | 内容 | 验收标准（pytest） |
|---|---|---|
| 1.1 | `test_text_cleaner.py`：长度上下限、空白归一、控制字符剔除、中英混排 | 先红后绿 |
| 1.2 | `test_content_filter.py`：敏感词命中、边界词、白名单、命中后的错误码 | 先红后绿 |
| 1.3 | `test_quiz_schema.py`：`Quiz/Question/Option` 的字段完整性、`type` 枚举、`answer` 必须在 `options` 的 key 集合内、单选答案唯一、判断题选项固定 2 项、题量 3–5 | 先红后绿 |
| 1.4 | `test_prompt_contract.py`：断言 Prompt **含 "json" 字样**、含 JSON 结构示例、含题量与题型比例约束、含「禁止 Markdown/代码块」约束 | 先红后绿 |
| 1.5 | `utils/` 三个模块实现（text_cleaner / content_filter / id_generator） | 通过 |
| 1.6 | `models/` + `llm/output_schemas.py`（Pydantic v2） | 通过 |
| 1.7 | `llm/langchain_factory.py`：`ChatOpenAI(model=deepseek-flash, base_url, api_key, temperature, top_p, timeout, max_retries)`，从 `.env` 读取 | 单测用 mock，不发真实请求 |
| 1.8 | `llm/search/base.py` 定义 `SearchProvider` 协议 + `NoopSearchProvider`（返回空结果并标记 `degraded=true`） | 单测通过 |
| 1.9 | `prompts/quiz_prompt.py`：`quiz_prompt_v1`（严格按方案设计 §8.3，仅补足 "json" 关键词与 JSON 示例） | 契约测试通过 |
| 1.10 | `llm/quiz_chain.py`：`with_structured_output(QuizStructured, method=主通道)`，失败切降级通道（默认 `json_mode` ⇄ `function_calling`） | 单测覆盖两条分支 |
| 1.11 | `test_llm_fallback.py`：模拟空响应 / Schema 映射失败 / 字段缺失 / 连续失败，验证五级兜底 | 先红后绿 |
| 1.12 | `services/quiz_service.py` + `services/task_service.py`（内存任务表 + TTL 清理 + 取消） | `test_task_service.py` 通过 |
| 1.13 | `test_quiz_api.py`：`POST /quiz/generate` 返回 task_id；`GET /tasks/{id}` 轮询到 succeeded 返回完整 Quiz；非法输入返回 4001；生成失败返回 5001 | 先红后绿 |
| 1.14 | **真实 API 抽验**：连续出题 10 次 | 结构稳定，≥80% 可直接渲染（方案设计 §13 Phase 1 验收） |

### Phase 2 · 前端闯关页（01 + 02，交付物：可完整答题的 15 屏）

| 步骤 | 内容 | 验收标准 |
|---|---|---|
| 2.1 | `services/request.ts`：Taro.request 封装（超时、统一响应码解包、错误归一） | 断网时抛出可识别错误 |
| 2.2 | `store/useQuizStore.ts`（Zustand）：题库/当前题号/作答记录/XP/进度/折叠态 | 单测（纯函数部分） |
| 2.3 | `components/` 基础件：NavBar / Btn / Card / Slip / Stamp / ProgressBar / Bar / Pill / Chip / DotMark / Li / Badge / RankRing / Mask / Sheet / ScrollBox / Field / OptionItem / Sprite / TabBar | 逐个与原型截图对照 |
| 2.4 | 启动页：法阵 SVG 旋转 1.8s 匀速 + 精灵 `floaty` + 文案分阶段 + 45% 进度条 | 冷启动无白屏 |
| 2.5 | 社团大厅：卷轴输入框（自动增高、0/200、`8 字` 激活按钮）+ 推荐 chip + 冒险者卡（静态示例数据） | 与原型 01 空态/已输入态一致 |
| 2.6 | 副本召唤中：三步状态卡 + 进度条 + 轮询 `GET /tasks/{id}` + 8s 后出「取消」+ 失败重试 | 真实反映后端进度 |
| 2.7 | 副本确认页：标题/摘要/题型构成（3 单选 1 多选 1 判断）/知识点 chip | 数据来自真实题库 |
| 2.8 | 挑战副本：三题型渲染 + 选项四态（默认/已选/答对/答错）+ 本地即时判题 + 讲解卡（默认展开/可折叠）+ 顶部进度条与 `+N XP` + 退出确认弹层 + 最后一题提交中 | 与原型 02 九屏逐屏一致 |
| 2.9 | 通关结算：XP/金币 0.8s 递增动画 + 正确率环 0.3s 延后绘制 | 与原型 01 第 6 屏一致 |

### Phase 3 · 报告页（03，交付物：复盘闭环 5 屏）

| 步骤 | 内容 | 验收标准 |
|---|---|---|
| 3.1 | `services/report.ts` + `POST /report/generate` 异步任务 + 轮询 | 后端联调通过 |
| 3.2 | `services/scoring_service.py`：正确率、XP、金币、掌握/薄弱知识点聚合 | `test_scoring_service.py` 全绿 |
| 3.3 | `prompts/report_prompt.py`：`report_prompt_v1`（严格按方案设计 §8.6） | 契约测试通过 |
| 3.4 | 冒险日志主视图：正确率环 + 答对/答错/平均用时三卡 + 百分位条 | 与原型 03 第 1 屏一致 |
| 3.5 | 三句话总结页 + 复习建议页 | 与原型 03 第 2/3 屏一致 |
| 3.6 | 异常态两屏：报告生成失败、网络异常 | 与原型 03 第 6/7 屏一致 |
| 3.7 | 主视图底部按钮接 `useShareAppMessage` 微信原生转发 | 转发带自定义标题与路径 |

### Phase 4 · 端到端联调与异常加固

| 步骤 | 内容 | 验收标准 |
|---|---|---|
| 4.1 | 主链路联调：输入 → 召唤 → 确认 → 答题 → 结算 → 报告 | 全流程无阻断 |
| 4.2 | 异常矩阵：AI 空响应 / 结构非法 / 超时取消 / 断网 / 后端 5xx | 每项都有明确文案与重试动作 |
| 4.3 | 微信开发者工具真机预览 + 底部安全区适配 | iOS/Android 均正常 |
| 4.4 | 全量 `pytest` + 覆盖率报告 | 后端服务层覆盖率 ≥ 85% |

### Phase 5 · 交付

| 步骤 | 内容 |
|---|---|
| 5.1 | `README.md`：环境准备、`.env` 填写、后端启动、前端构建、开发者工具导入 |
| 5.2 | 后端测试报告 + API 契约说明（FastAPI 自带 `/docs`） |
| 5.3 | 遗留清单：海报 / 历史日志 / P1–P3 的接入点标注 |

---

## 6. UI 还原规范

### 6.1 尺寸换算规则

原型机身宽 **332px**，真机设计宽 **750rpx**（375pt）。

```
rpx = 原型 px × 2.2590        (750 ÷ 332)
```

已换算的关键值（`tokens.scss` 会逐行注释原型原值）：

| 用途 | 原型 px | 真机 rpx | pt |
|---|---|---|---|
| tiny · 辅助说明 / 时间戳 | 11 | 24 | 12 |
| sub · 次级文字 | 11.5 | 26 | 13 |
| body · 讲解正文 | 12.5 | 28 | 14 |
| stem · 题干 | 13.5 | 30 | 15 |
| 按钮 / 卡片标题 | 15 | 34 | 17 |
| 启动页标题 / 结算标题 | 20–22 | 46–50 | 23–25 |
| 行高 | 1.55–1.85（**保留无单位倍数，不换算**） | — | — |

### 6.2 设计 token（唯一视觉来源）

```scss
// 纸与墨
$board:    #F1E8D0;  // 纸板底
$paper:    #FEFCF6;  // 纸面
$paper2:   #F5EDD8;  // 次级纸面 / 压痕
$paper3:   #EADFC4;  // 深压痕 / 分隔
$line:     #C9B48D;  // 纸上的线
$ink:      #2A2018;  // 墨 · 正文
$ink2:     #6B5A45;  // 淡墨
$ink3:     #9A8870;  // 更淡墨

// 功能色
$seal:     #A63A2E;  // 朱砂 · 印章与错误
$magic:    #2F6BD8;  // 魔法蓝 · 主操作
$magic-d:  #1F4694;  // 按钮底边
$magic-l:  #DCE9FB;  // 蓝浅底 · 选中
$gold:     #C8912A;  // 黄铜 · XP
$gold-d:   #9C6E15;  // 黄铜深 · 数字
$ok:       #2F7D4F;  // 正确 / 通过
$rare:     #6D4BC4;  // 稀有 / 连击
```

### 6.3 材质层级（不可混用）

| 层级 | 类 | 圆角 | 用途 |
|---|---|---|---|
| L0 裸内容 | — | — | 直接落在纸上，不装盒 |
| L1 纸面 | `.card` | 6px → **14rpx** | 阅读区域，内侧 1px 描边，**无外投影** |
| L2 纸片 | `.slip` | 3px → **7rpx** | 离散物件，硬投影 `2px 3px 0` + 1px 描边 |
| L3 印章 | `.stamp` | 2px → **5rpx** | 朱砂、微旋转 **-2.2deg**、双线框 |

> 卡片状态变体：`plain / parch / blue / ok / bad / gold / rare`，全部只改底色与内描边，不改圆角与投影。
> 注意：设计规范正文写「卡片圆角 16px、按钮底边 4px」，但实际原型 CSS 为 `6px` / `3px`。**以原型渲染视觉为准**。

### 6.4 按钮规范

- 圆角 7px → **16rpx**，底部实边 3px → **7rpx** 的深色边（`$magic-d` / `$gold-d` / `#1F5A38`）
- 按下：底边归零 + 整体下移 7rpx，模拟物理按键
- 一屏内只出现一个主按钮（`.btn`），次级用 `.btn.ghost`
- 禁用：`.btn.dis`，底色 `$paper3` + 文案替换为进行中态
- 最小热区 **≥ 44pt ≈ 100rpx**

### 6.5 答题选项四态

| 状态 | 底色 | 描边 | 键位底色 |
|---|---|---|---|
| 默认 | `$paper2` | inset 1px `rgba(150,120,72,.30)` | `$paper` |
| 已选 | `#DCE9FB` | inset 1.5px `$magic` | `$magic` + 米白字 |
| 答对 | `#DFF0E4` | inset 1.5px `$ok` | `$ok` + 米白字 |
| 答错 | `#F7E3DF` | inset 1.5px `$bad` | `$bad` + 米白字 |

题号键位为 **4px 圆角方块**（不是圆形）。

### 6.6 动效纪律（全站只有 6 个 keyframe）

`floaty`（精灵浮动 3.6s）· `twinkle`（星光 2.4s）· `spin` / `spin-r`（法阵 16s / 24s）· `shake`（答题反馈 0.45s）· `drift`（鸢鸢飘行，本期不用）

**静态场景一律不动**；`prefers-reduced-motion` 下全部关闭。

### 6.7 字体

中文不引网络字体（主包 2MB 上限），个性靠字重/字距/行高。
数字与拉丁用 **Baloo 2**（500/600/700/800），在 Taro 中通过 `@font-face` + 本地 woff2 子集引入，仅打包数字与字母字形以控制体积。

---

## 7. 接口契约

统一响应：成功 `{code:0, message:"ok", data:{}}`，失败 `{code:4xxx/5xxx, message:"...", data:null}`。

### 7.1 健康检查

`GET /api/v1/health` → `data: {status, version, model, search_enabled}`

### 7.2 创建出题任务

`POST /api/v1/quiz/generate`

```json
{ "user_input": "我想学习什么是 RAG，以及它和传统搜索有什么区别",
  "question_count": 5,
  "difficulty": "mixed" }
```

→ `data: { "task_id": "task_xxx", "status": "pending", "poll_interval_ms": 1200, "estimated_seconds": 12 }`

### 7.3 轮询任务状态（quiz 与 report 共用）

`GET /api/v1/tasks/{task_id}`

```json
{ "task_id": "task_xxx",
  "task_type": "quiz",
  "status": "running",
  "progress": 62,
  "steps": [
    { "key": "retrieve", "name": "理解你的输入", "status": "done", "detail": "已提炼 3 个核心概念" },
    { "key": "generate", "name": "生成闯关题目", "status": "running", "detail": "正在生成第 4 / 5 题" },
    { "key": "validate", "name": "校验题目结构", "status": "pending", "detail": "等待中" }
  ],
  "quiz": null,
  "error": null }
```

`status` 枚举：`pending | running | succeeded | failed | cancelled`
- 联网检索关闭时，第一步 `key=retrieve` 的名称由后端的 `SearchProvider` 决定：
  `NoopSearchProvider` 返回「理解你的输入 / 已提炼 N 个核心概念」，真实 Provider 返回「联网检索知识 / 已完成 · 命中 N 条资料」。**前端不做判断，直接渲染后端给的 name/detail**，这样后续开启联网无需改前端。

### 7.4 取消任务

`POST /api/v1/tasks/{task_id}/cancel` → `data: {status:"cancelled"}`

### 7.5 创建报告任务

`POST /api/v1/report/generate` —— 请求体同方案设计 §9.1（`topic` / `questions` / `answer_records`）
→ `data: { task_id, status, poll_interval_ms }`，轮询仍走 `GET /api/v1/tasks/{task_id}`，`task_type="report"`，成功后 `report` 字段返回结构化报告。

> **为什么不单独做「提交单题答案」接口**：沿用方案设计 §9.2 的结论 —— 前端本地即时判题，全部答完后一次性提交。

### 7.6 错误码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 4000 | 参数校验失败 |
| 4001 | 输入内容不合规（过短 / 过长 / 命中敏感词） |
| 4004 | 任务不存在或已过期 |
| 4090 | 任务不可取消（已结束） |
| 5000 | 服务内部错误 |
| 5001 | AI 生成失败（已重试仍失败） |
| 5030 | AI 服务超时 |
| 5031 | 上游配额或限流 |

---

## 8. 数据契约

### 8.1 Quiz

```json
{ "quiz_id": "quiz_xxx", "title": "RAG 入门闯关",
  "summary": "围绕 RAG 基础概念与应用场景生成的题库",
  "source_type": "text", "user_input": "原始输入",
  "question_stats": { "single": 3, "multiple": 1, "judge": 1 },
  "knowledge_points": ["RAG 基本定义", "向量检索", "与搜索引擎的边界", "应用场景"],
  "questions": [] }
```

> `question_stats` 与 `knowledge_points` 为**后端派生字段**，用于直接驱动原型 01「副本确认页」的题型构成与知识点 chip，前端不做二次计算。

### 8.2 Question

```json
{ "id": "q1", "type": "single|multiple|judge", "stem": "题干",
  "options": [{ "key": "A", "text": "选项A" }],
  "answer": ["A"], "explanation": "详细讲解",
  "knowledge_point": "知识点标签", "difficulty": "easy|medium|hard" }
```

### 8.3 AnswerRecord

```json
{ "question_id": "q1", "selected_answers": ["A"], "is_correct": true, "duration_ms": 3200 }
```

### 8.4 Report

```json
{ "accuracy": 80, "total": 5, "correct_count": 4, "wrong_count": 1,
  "avg_duration_ms": 8400, "xp_gained": 180, "coins_gained": 32, "percentile": 72,
  "mastered_points": [], "weak_points": [],
  "three_line_summary": ["", "", ""], "advice": [], "share_quote": "" }
```

> `accuracy / total / correct_count / wrong_count / avg_duration_ms / xp_gained / coins_gained` 由 `scoring_service` **确定性计算**；
> `percentile` 因无用户数据，由正确率派生（作为静态换算，§9.4）；
> 其余字段由 AI 报告链生成，服务层做字段完整性兜底。

---

## 9. 评分与奖励规则（待你最终确认）

原型里的数值不完全自洽（03 主视图 `+180 XP / +32 金币`，而历史日志里两个 80% 的局面分别是 `+180 XP` 与 `+175 XP`），故需明确一套确定性的规则：

### 9.1 单题经验值

| 题型 | 满分 XP | 规则 |
|---|---|---|
| 单选 single | 40 | 选对得 40，选错 0 |
| 多选 multiple | 60 | 完全选对得 60；**部分正确固定给 50% = 30 XP**；**有任何错选则 0**；全不选 0 |
| 判断 judge | 20 | 选对得 20，选错 0 |

**多选判定顺序**（必须按此顺序，否则会出现「错选也给分」的漏洞）：

```
1. 若 selected 中存在不属于 answer 的选项  → 0 XP（错选一票否决）
2. 否则若 selected == answer              → 60 XP（完全正确）
3. 否则若 selected ⊂ answer 且非空        → 30 XP（部分正确，固定 50%）
4. 否则（selected 为空）                   → 0 XP
```

**答错一律 +0，绝不扣分**（已确认）。部分正确固定 50% 的口径（已确认）与原型 02「部分正确」屏显示的 `+30 XP` 完全一致。

> 已锁定的口径：**固定 50%**（不按正确项比例）。示例：3 项正确答案中选对 2 项 → `+30 XP`，与原型一致。

### 9.2 单局总经验值

`XP = Σ 各题得分`。取原型 01 通关结算的组合（5 题全对）= `40×3 + 60 + 20 = 200`；答对 4 题得 `180`（少拿一道单选）—— 与原型 `+180 XP` 吻合。

### 9.3 金币

`coins = floor(XP × 0.18)` → `180 XP → 32 金币`，与原型 03 完全一致。

### 9.4 百分位

无真实用户池，用正确率做单调映射并固定种子，保证同一份答题结果每次都得到同一个百分位：

```
percentile = clamp(round(accuracy × 0.9), 5, 95)
```

`accuracy=80` → `72`，与原型「超过社团里 72% 的冒险者」一致。此值**明确标注为演示数据**，代码中留 `PercentileProvider` 接口，后续接真实统计只换实现。

### 9.5 静态演示数据（不做真实用户数据，已确认）

以下取自原型，写死在 `constants/mock.ts`，并在文件头注释标注「演示数据」：

| 位置 | 值 |
|---|---|
| 大厅冒险者卡 | `Lv.3 见习冒险者` / `1280 / 2000 XP` / `连续 4 天` / 进度 64% |
| 复习建议第 2 条 | `3 天后自动提醒复习` / `已加入复习计划` |
| 报告复习建议第 3 条 | `建议接着学「RAG 的落地实践」` |

> 其中**本局**的 XP、金币、正确率、用时是真实计算的，只有跨局的身份数据是演示值。

---

## 10. TDD 测试清单（后端）

| 测试文件 | 覆盖点 |
|---|---|
| `test_health_api.py` | 200、响应结构、model 字段 |
| `test_text_cleaner.py` | 长度边界、空白归一、控制字符、超长截断 |
| `test_content_filter.py` | 命中/未命中、白名单、命中后错误码 4001 |
| `test_quiz_schema.py` | 字段完整性、type 枚举、answer ⊆ options.keys、单选唯一解、判断 2 选项、题量 3–5 |
| `test_prompt_contract.py` | Prompt 含 "json" 关键词、含 JSON 示例、题量/题型比例、禁 Markdown |
| `test_task_service.py` | 创建/查询/取消/TTL 过期/重复取消 |
| `test_llm_fallback.py` | 空响应、schema 映射失败、字段缺失、重试后成功、彻底失败 → 5001 |
| `test_quiz_api.py` | 建任务、轮询至成功、非法输入 4000/4001、任务不存在 4004、生成失败 5001 |
| `test_scoring_service.py` | 全对/全错/多选部分/多选含错选/判断题、XP、金币、正确率、百分位 |
| `test_report_api.py` | 建任务、轮询、报告字段完整性、AI 失败降级为确定性模板报告 |

策略：**LLM 调用一律 mock**（不发真实请求），保证测试确定性与速度；真实 API 抽验放在 Phase 1.14 作为独立脚本，不进 pytest。

### 10.1 Phase 1 完成情况（实测）

| 测试文件 | 用例数 | 状态 |
|---|---|---|
| `test_health_api.py` | 5 | ✅ |
| `test_text_cleaner.py` | 21 | ✅ |
| `test_content_filter.py` | 14 | ✅ |
| `test_quiz_schema.py` | 42 | ✅ |
| `test_prompt_contract.py` | 24 | ✅ |
| `test_task_service.py` | 22 | ✅ |
| `test_llm_fallback.py` | 19 | ✅ |
| `test_quiz_api.py` | 23 | ✅ |
| **合计** | **170** | **全绿** |

覆盖率（`--cov=app`）：**总计 90%**；服务层 `task_service` 98% / `quiz_service` 95%，**高于 §5 Phase 4.4 要求的 85%**。

> `langchain_factory.py` 覆盖率 28% 是**刻意**的：它的正确性只能靠真实 API 验证（参数名、`extra_body`、`tool_choice` 兼容性都是实测结论），断言「参数被传对」只是把实现抄一遍。它由 Phase 1.14 的真实抽验负责。
> `test_llm_fallback.py` 从 17 增至 19，是 §2.4.2 调换主通道时补的回归护栏（默认值断言 + 阶梯首项断言）。
> `report` 相关模块尚未实现，Phase 3 补齐。

### 10.2 Phase 1.14 真实 API 抽验（实测）

`.venv/Scripts/python.exe scripts/verify_quiz_chain.py`，连续 10 次真实出题：

| 指标 | 结果 |
|---|---|
| 界面可渲染率 | **10/10 = 100%**（判据：题量 3–5、每题 4 选项、答案 ⊆ 选项、有解析） |
| 题型构成 | 3 单选 · 1 多选 · 1 判断，10/10 全中 |
| 平均耗时 | 7.5s / 次（含首轮失败后的降级重试） |
| 首轮通过率 | 6/10 —— 这是 §2.4.2 调换主通道的直接动因 |

---

## 11. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| DeepSeek JSON Output 偶发空响应（官方已知问题） | 出题失败 | 两通道交替兜底（`json_mode` ⇄ `function_calling`，共 2 + `QUIZ_MAX_RETRIES` 次）+ 总时间预算 50s，见 §12.1 |
| `function_calling` 通道**系统性省略嵌套字段**（实测 67% 首轮通过） | 1/3 的请求要多跑一轮，耗时与成本翻倍 | 主通道调换为 `json_mode`（实测 100%），并加默认值回归护栏，见 §2.4.2 |
| DeepSeek 出题耗时超过小程序 60s 上限 | 请求失败 | 异步任务 + 轮询（已确定） |
| 兜底阶梯本身耗时堆积（timeout × 次数） | 用户长时间空等 | `QUIZ_GENERATION_BUDGET_SECONDS`（默认 50s）越过即停，不再发起剩余尝试 |
| `max_tokens` 上限 4096 导致 JSON 截断 | 结构不完整 | 保守设置 + 截断检测 + 命中时降题量重试 |
| AI 返回结构非法 | 前端崩溃 | 服务层强制 Pydantic 校验，脏数据绝不外传，失败即 5001 |
| Taro 跨端样式差异（无 `box-shadow: inset` 部分支持） | 视觉偏差 | 关键描边改用 `border` 方案做等价替代，逐屏比对截图 |
| 小程序主包 2MB 上限（Baloo 2 字体） | 包体超限 | 字体子集化，仅保留数字与拉丁字形 |
| 微信 `<image>` 对「只有 viewBox」的 SVG 尺寸推导无保证 | 标签栏图标不显示或错位 | 标签栏图标改用 81×81 PNG（`scripts/rasterize_tab_icons.py` 离线光栅化），见 §12.2 |
| 多个 `npm install` 并发抢同一 `node_modules` | 安装互相锁死、长时间不推进 | 只允许单进程安装；`.npm-install.log` 落盘便于观察 |

---

## 12. 确认记录

已于 **2026-09-16** 人工确认全部 3 项：

| # | 事项 | 结论 |
|---|---|---|
| 1 | 多选部分正确的给分 | **固定给 50%**（30 XP），与原型 02 显示一致 → 已写入 §9.1 |
| 2 | `.env` 的 `DEEPSEEK_API_KEY` | 已填写；连通性验证已完成（见 §2.4.1 实测结论表） |
| 3 | Phase 0–5 顺序与验收标准 | **认可**，特别是 Phase 1 的「先写测试跑红、再写实现跑绿」 |

**开工前的连通性验证结果（已完成）**

| 验证项 | 结果 |
|---|---|
| `GET /models` | ✅ 200，仅返回 `deepseek-flash` 与 `deepseek-v4-pro`（证实 `deepseek-chat` 已退役） |
| 基础对话 | ✅ 0.35–0.6s |
| function calling + 强制 `tool_choice` | ✅ 1.0s，返回结构完整的题目对象 |
| `response_format: json_object` | ✅ 0.95s，JSON 可正常解析 |
| `response_format: json_schema` | ❌ 400 `This response_format type is unavailable now`（已按 §2.2 规避） |
| 思考模式默认状态 | ⚠️ **默认开启**，必须显式关闭（已按 §2.4.1 处理） |

---

### 12.1 开工后的工程判定（编码期结论，追加记录）

| # | 事项 | 结论与理由 |
|---|---|---|
| 4 | 兜底阶梯的**顺序** | 两个通道**交替**（主 → 降级 → 主 → 降级），而不是「主通道连撞 3 次再降级」。理由：空响应是瞬时的（换不换通道成功概率相同），而通道不兼容只有换通道能救 —— 交替在最坏情况下不亏、在最好情况下快得多。总次数 = `2 + QUIZ_MAX_RETRIES` |
| 5 | 兜底阶梯的**时间上限** | 新增 `QUIZ_GENERATION_BUDGET_SECONDS`（默认 50s）。理由：单次 `timeout(30s)` 叠加 HTTP 重试后，最坏情况远超用户愿意等待的长度；越过预算即停止剩余尝试。注意第一次尝试**永远放行**，否则 0 会变成「永远失败」的死路 |
| 6 | 「确定性模板」兜底**只属于报告链** | 方案设计 §13 描述的第五级「确定性模板」在**出题链不实现**。理由：报告是对已知数据（正确率 / XP / 金币）的复述，模板降级后仍是真话；而题库是纯生成内容，模板拼出来的题本质是编造学习材料，用户无法分辨 —— 比直接报错更有害。出题链停在 5001，把重试选择交回用户 |
| 7 | 生成失败的**返回落点** | 轮询端点以 HTTP 200 + `status="failed"` + `error={code:5001, message}` 返回，而不是把轮询请求本身变成 502。理由：轮询请求本身是成功的；§7.3 专门为它留了 `status` 与 `error` 字段，若改用 HTTP 状态码表达，这两个字段就失去意义。**前端判 `error.code`，不判 HTTP 状态码** |
| 8 | 轮询响应体**形状固定 10 键** | `task_id / task_type / status / progress / steps / quiz / report / error / created_at / updated_at`，含 `report`（Phase 3 用）且无值的字段给 `null` 而非省略。理由：前端只写一套解析逻辑；省略键会逼前端到处写 `?.`，漏一处就是线上白屏 |
| 9 | `QuizDraft` 与 `Quiz` **分开定义** | `with_structured_output` 用 `QuizDraft`（只含模型该产出的字段），不用 `Quiz`。理由：不逼模型回显 `user_input`（浪费 token 且可能被改写），也不让它生成服务端才有权决定的 `quiz_id` |
| 10 | 标签栏图标**改用 PNG** | 微信 `image` 官方支持 SVG，但同时列出「不支持百分比单位 / 不支持 `<style>` / `scaleToFill` 下 WebView 居中」三条限制；抽出的图标只有 `viewBox` 没有 `width/height`，尺寸推导属文档未兜底行为。标签栏是固定 81×81 的位图场景，改为 PNG 一次性消除不确定性。光栅化脚本只用 Python 标准库（不引入原生依赖），矢量副本仍保留在 `assets/icons/svg/` |
| 11 | 检索 Provider 只落地 `base` + `noop` | 方案设计的目录里列了 `bocha` / `tavily`，但它们是 P1 范围。**不写空壳文件**（既无法测试，也会让人误以为已支持）；改为在 `get_search_provider` 里对这两个名字显式报「尚未接入」。开关打开但 Provider 未实现时**报错而非静默降级成不联网** —— 静默降级最糟：配置明明打开，用户却以为在联网 |
| 12 | 出题主通道**由 `function_calling` 调换为 `json_mode`** | 实测量化：`json_mode` 一次通过 6/6，`function_calling` 4/6（失败形态为「模型系统性省略每题的 `knowledge_point`/`difficulty`」，偶尔是空响应）。降级通道保留 `function_calling` 而非删除 —— 两者失效原因不同，上游若不再支持 `response_format=json_object` 时只有换通道能救。量化脚本 `backend/scripts/compare_output_methods.py` 不进 pytest。详见 §2.4.2 |

---

**当前状态：Phase 0 已完成；Phase 1 已完成（1.1–1.14，170 个测试全绿、总覆盖率 90%，真实 API 抽验 10/10 可渲染）。**每个 Phase 完成后向用户汇报验收结果。
