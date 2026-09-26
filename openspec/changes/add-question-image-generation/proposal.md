# Proposal

## Why

出题链目前只产出文字。刷英语单词、学动植物 / 历史 / 地理这类内容时，一张与题目相关的
实物图能显著降低记忆成本 —— 而模型的生图能力已经可用（百炼 `z-image-turbo`），
缺的只是「把它接进出题链并且不把出题拖垮」这件事。

## What Changes

- **出题入参**：`POST /quiz/generate` 增 `generate_images`（默认 `false`）。勾选后本次出题会
  为每道题生成一张配图，失败只丢图、题目照常返回。
- **生图链**（`app/llm/image/`）：题目 → 生图 Prompt（只用知识点 + 题干主题词，**禁选项 / 答案**，
  画面禁出现文字）→ 百炼 `z-image-turbo` 同步接口 → 下载图片 → 上传腾讯云 COS → 得到永久 URL。
  每题一次调用、有界线程池并发、单张超时 + 总预算，任一环节失败即降级。
  （模型于 2026-09-26 由 `qwen-image-2.0` 换为 `z-image-turbo`，理由与实测见 design D15。）
- **契约**：`Question` 增 `image_url`（可空）。轮询结果、确认页、答题页、复习关卡、历史详情
  五处因此自动带上，不必各接一套。`questions` 表增一列 `image_url VARCHAR(512) NULL`。
- **配额**：新增 `image_quota_usage(user_id, biz_date, used_count)`，**每人每天默认 20 张**，
  按业务日 + 用户原子扣减；额度不足时在**建任务之前**拦下并给友好提示（用户不必等十几秒才知道没图）。
  失败张数退回。
- **能力下发**：`GET /health` 增 `image_generation_enabled`，作为前端开关显隐的唯一事实来源。
- **前端**：生成设置页与大厅各增「生成配图」入口；答题页与历史详情按 `image_url` 渲染配图。
- **进度**：生图并入既有「生成闯关题目」步骤的详情（不新增第四步），形如
  「已生成 5 道题 · 正在配图 3 / 5」。

## Capabilities

### New Capabilities

- `question-images`：题目配图的生成、存储、配额与降级规则。

### Modified Capabilities

（无。本变更不修改任何既有规格基线 —— 出题依据与取材规则的约束不变，
配图只增不减，且不含资料语义。）

## Impact

- **后端**：`core/config.py`（配置组）、`db/tables.py`、`sql/08_question_image.sql`、
  `llm/output_schemas.py`（`Question.image_url`）、`services/{quiz_repository,quiz_service,
  review_service,scroll_service}.py`、`llm/image/`（新包 3 文件）、
  `services/image_quota_service.py`（新）、`api/v1/routes/{quiz,health}.py`。
- **前端**：`types/api.ts`、`services/quiz.ts`、`store/useAppStore.ts`、`app.ts`、
  `pages/{hall,kb-generate,quiz,profile/scroll-detail}/`、`constants/copy.ts`。
- **配置**：`requirements.txt` 增 `cos-python-sdk-v5`；`.env.example` 增占位（COS 四项留空待填）。
- **文档**：`docs/方案设计文档.md` 增一节；`.env.example` 注释。
- 无既有接口签名破坏（新字段可空 / 可选）；无数据迁移（加列 + 建表，`apply_sql.py` 幂等执行）。

## Non-goals（不做什么）

- **不做异步生图与补图**：没有「事后把缺的图补回来」的任务，本次没生出来就是没有。
- **不做用户可选尺寸 / 模型 / 风格**：尺寸与模型由 `.env` 决定（默认 512×512），前端不给选项。
- **不做图床清理与生命周期管理**：COS 里对象不过期、不回收，本变更不建回收机制。
- **不把生图做成必选路径**：开关默认关，关着时链路与现在**逐字节一致**。
- 不改动任何取材 / 出题 / 评分 / 复盘逻辑，也不把配图内容纳入"事实依据"范畴。

## 追加变更 IV（2026-09-26）：由 AI 挑选需要配图的题目

**Why**：配图**逐张计费**，而「每道题都配」里相当一部分是浪费 —— 抽象概念、
纯逻辑与文字表述类题目画出来对理解没有增益（2026-09-26 的人眼验收里，
这类题被画成花、枫叶、灯泡）。改为在生图**之前**先让模型判断哪几道**值得配图**，
只给挑中的题花钱。

**What changes**：

- 生图段前新增一步判断题：`llm/image/selector.py` + `prompts/image_select_prompt.py`。
- **判断失败时回退成「全部配图」**，而不是「全部不配」—— 判断是省钱手段，
  不是功能前提；关掉 `IMAGE_SELECT_ENABLED` 即回到接入本功能之前的行为。
- 判断的输入只有题干 / 题型 / 知识点，不含选项、答案与解析（与提示词构建同一条纪律）。
- 前端两处文案从「每题配图」改为「智能配图 / 自动挑选配图」，
  并说明「不是每道题都有图」。

**Impact 增量**：`services/quiz_service.py`（判断 → 筛选 → 生图，含收尾文案）、
`llm/image/__init__.py`（新增 `REASON_NO_NEED`）、`llm/output_schemas.py`
（新增 `ImageSelectionDraft`）、`core/config.py`（`IMAGE_SELECT_*` 两个新键）、
`frontend/src/{constants/copy.ts,types/api.ts}`（文案与注释）。
无接口签名破坏、无数据迁移、无新增外部依赖（复用出题那个 DeepSeek）。

