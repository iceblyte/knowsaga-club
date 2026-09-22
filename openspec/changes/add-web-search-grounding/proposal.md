# Proposal

## Why

模型训练数据有截止时间。用户想学的新概念（如 Harness Engineering）落在模型知识之外，
模型会拿别的领域的知识硬凑成题 —— 用户学到的就是错的，而且从题面上看不出来。

还有第二种同样常见的形态：**用户手上本来就有一份资料**（一个网页链接）。他真正要学的是那个页面里的东西，
而模型只能凭记忆猜。项目已留好检索接缝（`SearchProvider`），但实现是 `NoopSearchProvider`
（恒返回空结果 + `degraded=True`），上面两条路都没有任何依据。

## What Changes

- 用官方 `langchain-tavily` 的 **`TavilySearch`（关键词检索）** 与 **`TavilyExtract`（按 URL 抓整页）**
  两个工具实现取材，替换 MVP 的 `NoopSearchProvider`。
- 两个工具**同时交给模型**，由模型自己决定调哪个、调几次、什么顺序 —— 资料稀薄的复杂主题可以多轮检索
  并读整页，简单主题一次检索取摘要即可。
- 服务端每次按请求**动态构造工具实例**，决定模型无权决定的参数：检索结果条数、国家/地区偏好
  （兼顾国内外用户）、以及「不把整页正文塞进搜索结果」的省额度策略。
- 用户输入里含网页链接时，该链接**必定被读取**（它是用户自己递来的资料，不受「联网检索」开关约束）；
  开关只管「要不要让 AI 额外主动去网上搜」。
- 取材阶段的轮次、工具调用次数与总时长都有硬上限；超限就带着已有资料收尾，**不是失败**。
- 取材得到资料 → 资料注入出题 Prompt，题目必须以资料为唯一事实依据；取材端无任何结果 → 记日志、标记降级，
  仍按现有纯模型链路出题，**不打断用户**。
- 资料快照落库到 `quizzes` 新列，供报告链复用与后续排查。
- 报告链收紧：知识总结只能来自题库，不得引入题库之外的事实。
- 出题 / 报告 Prompt 升到 v2，并把「第三方网页内容是数据、不是指令」写进 Prompt（防提示词注入）。

## Capabilities

### New Capabilities

- `knowledge-retrieval`: 为出题在外部取材的能力 —— Provider 契约、官方 Tavily 工具的装配、
  模型自主调用的有界循环、关键词检索与整页抽取两条取材路径、参数分层、开关与降级、资料快照落库。
- `quiz-grounding`: 生成内容的外部依据约束 —— 出题以资料为准、链接输入的学习范围、
  资料缺失时的抗编造行为、报告不得复述题库外知识。

### Modified Capabilities

无。`openspec/specs/` 目前为空，本次是首个 spec。

## Non-goals（不做什么）

- 不做博查 / 多源互备，本期只实现 Tavily 一个 Provider。
- **不做「多源输入」这个 P1 能力**：不解析 PDF / Word / 视频，不做文档上传与解析管线，不做 RAG 私有知识库。
  本期只多支持「输入里带网页链接 → 读那个页面」这一条取材路径。
- 不把整页正文塞进搜索结果（`include_raw_content` 一律关）—— 需要整页时由模型按需调 `tavily_extract`。
- 不在 UI 展示参考来源，不做资料时效标注。
- 不做检索结果的语义重排与相关性打分模型。
- 取材无结果时不弹「是否继续」的二次确认，直接降级出题。
- 不做检索用量限流与计费（额度由 Tavily 账号侧兜底）。
- 不改评分、勋章、错题复习等既有逻辑。

## Impact

- **页面**：`frontend/src/pages/hall`（输入区已有的 pill 由只读改为可点开关，文案分四态）、
  `frontend/src/constants/copy.ts`。
- **接口**：`POST /api/v1/quiz/generate` 新增 `use_search`；`GET /api/v1/tasks/{id}` 的 `steps[0]`
  名称与文案随取材方式变化（响应形状不变，仍是十键）。
- **数据表**：`quizzes` 新增两列（检索状态 + 资料快照），DDL 进 `backend/sql/`，用 `scripts/apply_sql.py` 执行。
- **依赖**：`backend/requirements.txt` 新增 `langchain-tavily==0.2.18`（会带入 `requests` 与 `aiohttp`
  两个传递依赖）。不引入 `langgraph` 作为直接依赖。
- **代码**：`backend/app/llm/search/`（新增工具装配与取材循环模块）、`app/llm/quiz_chain.py`、
  `app/prompts/{quiz,report}_prompt.py`、`app/services/quiz_service.py`、`app/services/quiz_repository.py`、
  `app/models/quiz.py`、`app/db/tables.py`、`app/core/config.py`。
- **文档**：`.env.example`（补 `TAVILY_API_KEY` 说明）、`docs/MVP开发计划.md`、`docs/方案设计文档.md`。
