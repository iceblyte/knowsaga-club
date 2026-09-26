# Tasks

> 顺序即依赖顺序。后端每条都拆成「写测试跑红」与「写实现跑绿」两步（项目硬约束）。
> 跑后端测试的环境变量：`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--basetemp=../.tmp_pt_base`。
>
> ⚠️ **本文件已于 2026-09-25 按实证结果复核过一遍**（此前只有第 3、4 节被勾选，
> 代码其实早已落地）。复核方式：逐条按「文件 + 标记」实查，并把**任务文本里写错的
> 测试文件名改成实际落点**（错误的行保留原文 + 加「更正」说明，方便对照）。
> 唯一的实证例外见 8.5。

## 1. 配置与依赖

- [x] 1.1 `backend/app/core/config.py`：新增「题目配图」配置组 ——
      `image_generation_enabled: bool = False`、`image_model: str = "z-image-turbo"`
      （**2026-09-26 由 `qwen-image-2.0` 换掉**，见 design D15）、
      `image_size: str = "512*512"`、`image_max_workers: int = 2`
      （**2026-09-26 由 3 下调**，见 design D17）、
      `image_timeout_seconds: int = 20`、`image_budget_seconds: int = 45`、
      `image_daily_quota: int = 20`、`image_download_max_bytes: int = 8 * 1024 * 1024`、
      `cos_secret_id / cos_secret_key / cos_region / cos_bucket / cos_public_base_url`（均 `""`）；
      以及派生属性 `has_image_credentials` 与 `image_generation_available`
      （= 开关 && dashscope key 非空 && COS 五项关键项齐全）
      —— 已逐项查实（16 个标记全中）。
- [x] 1.2 `backend/tests/test_config_image.py`（新）：断言默认值、断言
      `image_generation_available` 在「缺 key / 缺 COS / 开关关」三种情形下均为 `False`、
      开关与凭据齐备时为 `True`
- [x] 1.3 `backend/requirements.txt` 增 `cos-python-sdk-v5`，并装进 `backend/.venv`
- [x] 1.4 `.env.example` 增配图配置块：开关与参数带注释（**注释只写已实现语义**），
      COS 五项留空占位并注明「从腾讯云控制台获取」。
      ⚠️ 顺带查实：**`.env` 里目前既没有 `IMAGE_GENERATION_ENABLED`、也没有 COS 五个键**
      （只有 `DASHSCOPE_API_KEY` 已填）⇒ 能力开关实际为 `off`，这是 8.5 只能走 fallback 的原因。

## 2. 数据层

- [x] 2.1 `backend/sql/08_question_image.sql`：`questions` 加 `image_url VARCHAR(512) NULL`；
      新建 `image_quota_usage`（`user_id` + `biz_date` 联合主键、`used_count`、
      外键指 `users.id` `ON DELETE CASCADE`）；**幂等**（`information_schema` 判断 + 预处理语句）
- [x] 2.2 `backend/app/db/tables.py`：`QuestionRecord.image_url` + 新模型 `ImageQuotaUsage`，
      并加进 `ALL_TABLES`
- [x] 2.3 `backend/tests/test_db_mapping.py`：同步表数 / 外键数期望值，并加
      `image_quota_usage` 的逐列断言
- [x] 2.4 用 `backend/scripts/apply_sql.py` 把 08 应用到**业务库 + 测试库**，并跑 2.3 的测试
      —— **实证**（本轮直接查两个库的 `information_schema`）：
      业务库 `knowsaga_club` 与测试库 `knowsaga_club_test` 均为
      `questions.image_url=1`、`image_quota_usage=1`。

## 3. 生图服务 `app/llm/image/`（TDD）

- [x] 3.1 写测试跑红：`backend/tests/test_image_prompt.py` —— 只用知识点 + 主题词、
      不含选项文字 / 答案 / 解析、画面禁文字约束存在、超长题干被截断
- [x] 3.2 写测试跑红：`backend/tests/test_image_client.py` —— 上游用替身：
      正常返回解析出图 URL、`n=1`、关掉 `prompt_extend`、超时抛错、
      上游报错抛错、响应结构异常抛错
- [x] 3.3 写测试跑红：`backend/tests/test_image_store.py` —— COS 用替身：
      上传成功返回永久 URL、下载非图片 / 超限被拒、上传异常上抛
- [x] 3.4 写实现：`backend/app/llm/image/prompt.py`（题目 → Prompt）
- [x] 3.5 写实现：`backend/app/llm/image/client.py`（`MultiModalConversation.call` 同步调用，
      有界线程池 + 单张超时 + 响应解析 + 图片下载校验）
- [x] 3.6 写实现：`backend/app/llm/image/store.py`（`cos-python-sdk-v5` `put_object` + 永久 URL）
- [x] 3.7 写测试跑红：`backend/tests/test_image_generate.py` —— 并发编排
      `generate_for_questions`：**绝不抛异常**、部分失败降级、总预算超时后放弃剩余、
      全部失败返回全空
- [x] 3.8 写实现：`backend/app/llm/image/__init__.py` 导出编排函数，三条规则按 design D8 落地
- [x] 3.9 跑焦点测试：`pytest tests/test_image_*.py` 全绿

## 4. 配额服务（TDD）

- [x] 4.1 写测试跑红：`backend/tests/test_image_quota.py` —— `reserve` 正常 / 超额抛错、
      原子性（同一用户并发 reserve 不超发）、`settle` 退还失败张数、
      `release` 全额退还、跨日按业务时区重置
- [x] 4.2 写实现：`backend/app/services/image_quota_service.py`（`INSERT ... ON DUPLICATE KEY UPDATE`；
      三个入口 `reserve` / `settle` / `release`；超额抛 `AppError`）
- [x] 4.3 跑焦点测试：`pytest tests/test_image_quota.py` 全绿（22 passed）

> ⚠️ **4.2 有一处对初稿的修正，已登记在 `design.md` D6.1 / D6.2**：
> ① 超额的错误码取 **`4290`**（→ HTTP 429）而非这里初稿写的 `4001` ——
> 本项目 `exceptions.py` 的码表把 4001 定义为「输入内容不合规」，用它会污染那张表；
> 且前端 `ERROR_FALLBACK_TEXT` 未登记 4290，友好文案能原样透出。
> ② 原子性**不能**靠 `ON DUPLICATE KEY UPDATE` 的受影响行数判超额 ——
> 实测「新插入」与「被 `IF` 钳住」都返回 1，无法区分。实现改为
> 「无条件自增 → 同事务回读 → 超额则原样减回再拒绝」。
> ③ 退还写成 `IF(used_count >= N, used_count - N, 0)`，
> **不能**用 `GREATEST` —— 实测 MySQL 先算减法再算 GREATEST，UNSIGNED 下溢照样报 1690。


## 5. 接链（TDD）

> **更正（2026-09-25）**：5.1 / 5.3 / 5.7 / 5.11 原本点名的测试文件
> （`test_quiz_model.py` / `test_quiz_repository.py` / `test_review_service.py` /
> `test_scroll_api.py`）在本仓库**并不存在**。实际落点如下，已按真实位置勾选：
> - 契约（`Question.image_url` 默认值、`draft_to_quiz` 强制清空）与仓储（落库 / 回读 / 截断）
>   ⇒ `backend/tests/test_quiz_image_flow.py`（「一、契约」与「二、仓储」两节）
> - API 入参（默认 false、开关关时传 true 被拒 4001、超额 4290 且 `create_task` 调用次数为 0）
>   ⇒ 同在 `backend/tests/test_quiz_image_flow.py`
> - 复习副本带图 ⇒ `test_quiz_image_flow.py::test_review_copy_carries_the_original_image`（单测级）
> - 卷轴详情带图 ⇒ **本轮新增** `test_scrolls_api.py::test_scroll_detail_carries_the_question_image`
>   （API 级；原任务文本写的 `test_scroll_api.py` 实为 `test_scrolls_api.py`）

- [x] 5.1 写测试跑红：`Question.image_url` 默认 `None`、且 `draft_to_quiz`
      **强制清空**模型给的 `image_url` ⇒ 落点更正为 `test_quiz_image_flow.py`
      （`test_question_image_url_defaults_to_none` /
      `test_draft_to_quiz_strips_model_supplied_image_url`）
- [x] 5.2 写实现：`backend/app/models/quiz.py` 的 `Question` 加 `image_url: str | None = None`；
      `backend/app/llm/output_schemas.py` 的 `draft_to_quiz` 清空该字段
- [x] 5.3 写测试跑红：`image_url` 落库与回读（带图 / 不带图两种）
      ⇒ 落点更正为 `test_quiz_image_flow.py::test_persist_quiz_writes_and_reads_back_image_url`
- [x] 5.4 写实现：`backend/app/services/quiz_repository.py` 的 `persist_quiz` 与 `build_quiz`
      带上 `image_url`（含 512 长度截断）
- [x] 5.5 写测试跑红：`backend/tests/test_quiz_image_flow.py`（新）—— 勾选时落库前插入生图段
      （生图用替身）、生图失败题目照常成功、进度 detail 含配图读数、配额预检在建任务之前失败
- [x] 5.6 写实现：`backend/app/services/quiz_service.py` —— `submit_quiz_request` 增
      `generate_images` 与配额预检；`run_quiz_generation` 在落库前插入生图段并推 detail
- [x] 5.7 写测试跑红：`generate_images` 入参（默认 false、开关关时传 true 被拒）
      ⇒ 落点更正为 `test_quiz_image_flow.py`（`...defaults_to_false` /
      开关关时 4001 的用例 / `4290` 预检用例）
- [x] 5.8 写实现：`backend/app/api/v1/routes/quiz.py` 增 `generate_images` 字段并透传
- [x] 5.9 写测试跑红：`backend/tests/test_health_api.py`（既有）加
      `image_generation_enabled` 字段与「如实下发」用例（基线必为 `False`）
- [x] 5.10 写实现：`backend/app/api/v1/routes/health.py` 下发 `image_generation_enabled`
- [x] 5.11 写测试跑红：「配图随题目带出」断言 ⇒ 见上方「更正」。
      **其中卷轴详情是本轮补的 API 级锁定用例**：`scroll_service` 里
      `Quiz → ScrollQuestionItem` 是**逐字段手抄**的映射，漏抄不报错、只表现为
      「答题有图、回看没图」；新用例只给第一题配图，断言第一题透出、第二题为 `null`，
      并做过**变异验证**（删掉服务端那行透传 ⇒ 用例变红；还原 ⇒ 绿）。
- [x] 5.12 写实现：`backend/app/services/review_service.py` 的 `_copy_of` 与
      `backend/app/services/scroll_service.py` 的详情带上图
- [x] 5.13 跑焦点测试：`pytest tests/test_quiz_*.py tests/test_health_api.py tests/test_scrolls_api.py tests/test_review_api.py` 全绿

## 6. 前端

- [x] 6.1 `frontend/src/types/api.ts`：`QuizQuestion` 加 `image_url?: string | null`；
      `QuizGeneratePayload` 加 `generate_images?: boolean`；
      `HealthInfo` 加 `image_generation_enabled: boolean`；
      `ScrollQuestionItem` 加 `image_url?: string | null`
- [x] 6.2 请求体加 `generate_images` ⇒ **更正**：字段落在
      `frontend/src/types/api.ts` 的 `QuizGeneratePayload`，由
      `frontend/src/pages/summon/index.tsx` 写入。
      `frontend/src/services/quiz.ts` 的 `createQuizTask` 是**泛型透传**
      （`data: payload`）⇒ 该文件里**不应**出现 `generate_images` 字面量，这是刻意的分层，不是遗漏。
- [x] 6.3 `frontend/src/store/useAppStore.ts`：加 `imageGenerationEnabled`（能力，默认 `false`）
      与 `generateImages`（意愿，默认 `false`）
- [x] 6.4 `frontend/src/app.ts`：启动探测回填 `setImageGenerationEnabled(...)`，失败不阻塞
- [x] 6.5 `frontend/src/constants/copy.ts` + `pages/workshop/kb-generate/index.tsx`：
      生成设置页增「生成配图」开关卡（按能力显隐）
- [x] 6.6 `frontend/src/pages/hall/index.tsx`：增第二枚 pill（按能力显隐，`flex: none` 防压扁），
      提交路径显式写入 `generateImages`
- [x] 6.7 `frontend/src/pages/quiz/index.tsx`：题干上方渲染配图（无图不占位）
- [x] 6.8 `frontend/src/pages/profile/scroll-detail/index.tsx`：回看时渲染配图
- [x] 6.9 `tsc --noEmit --skipLibCheck` EXIT=0；WeApp / H5 双端构建成功
      —— 本轮复跑 `TSC_EXIT=0`（无输出）。

## 7. 文档

- [x] 7.1 `docs/方案设计文档.md` 增「题目配图」一节（§15）：两阶段、配额、降级、开关语义
- [x] 7.2 `docs/MVP开发计划.md` ⇒ **更正**：实际**涉及且已改**（不是「无需改动」）——
      §7.1 health 增 `image_generation_enabled`、§7.2.3 新增 `generate_images` 入参契约、
      §7.6 错误表增 `4290`、§8.2 Question 示例增 `image_url`。
- [x] 7.3 `shared/scoring-cases.json`：确认与配图无关（评分不受影响）⇒ 不改，在此登记

## 8. 闸门与验收

- [x] 8.1 全量 `pytest`（**不是子集**，铁律 9）⇒ 退出码 0、零 F/E（按进度行数点号）。
      本轮在补了 5.11 那条用例后**重跑全量**：见文件末尾「终局读数」。
- [x] 8.2 `node node_modules/typescript/bin/tsc --noEmit --skipLibCheck` EXIT=0
- [x] 8.3 `python tools/scan_secrets.py` EXIT=0。
      ⚠️ 修掉一次**自造误报**：`client.py` 里为解释扫描规则而写的注释，原样照抄了
      「关键字 + 等号 + 标识符」的写法 ⇒ 注释自己被那条规则命中。
      改用散文描述、不出现该写法后转绿（与 `llm/search/tavily_tools.py` 同源坑）。
- [x] 8.4 真浏览器验收：H5 实跑（390×844）—— 大厅两枚 pill 的 `getBoundingClientRect`
      对比（既有 pill 未变形 94.7px 不变）、生成设置页开关出现、勾选后提交体含
      `generate_images: true` / 未勾选为 `false`、答题页配图渲染、**数后端请求**
      （挂载期 `/health`×1、`/users/me`×1、`/users/me/reminders/today`×2，无重复探测）。
      **且挖出并修掉 1 个真 bug**：Taro H5 的 `<Image mode="widthFix">` 宿主默认
      `height:240px; overflow:hidden` ⇒ 512×512 图底部被静默裁掉 68.1px；
      加 `height:auto` 后 A/B 实测 `clippedPx` 68.1 → 0（`quiz` 与 `scroll-detail` 两处）。
- [x] 8.5 真链路验证（凭据齐备时）⇒ **走本条自带的 fallback 分支交付**：
      `.env` 未填 COS 五项、`IMAGE_GENERATION_ENABLED` 亦未设（见 1.4），
      故 **①** 已用真浏览器反向验证「能力关掉时入口不出现」（把 `/health` 的
      `image_generation_enabled` 打成 `false`：大厅只剩 1 枚 pill、生成设置页无「题目配图」卡）；
      **②** 已提供自跑脚本 `backend/scripts/verify_image_chain.py`（凭据齐备后可直接跑）。
      ⚠️ **真链路（真实百炼生图 + 真实 COS 转存）本轮未验证** —— 无凭据，不做任何推测。
- [x] 8.6 `openspec validate --all --json`：0 failed（5 项：本变更 + 4 份规格基线）

---

## 复核副产物：本轮额外发现并修掉的 4 个问题（2026-09-25）

复核勾选状态时顺带撞出来的，都不是「实现有 bug」，而是**文档/注释写了假话**
（本项目铁律 10：注释会被当成契约读，比没注释更危险）：

1. **`.env.example` 的开关注释自相矛盾**。第 175 行写「关闭 ⇒ 带 `generate_images=true`
   的请求被拒」，第 178 行却写「关了开关直接打接口照样能出图」。
   实查：没有独立生图端点，唯一入口是 `POST /quiz/generate` + `generate_images=true`，
   开关关时该请求被 4001 拒（`test_submit_rejects_images_when_capability_is_off`）
   ⇒ 后一句是假的。已改写为：**不是权限位（无独立端点、不改变路由注册、不 403），
   但不能读成「关掉也能用」**。

2. **同一条错误说法扩散到 4 处**，一并改准：
   - `backend/app/api/v1/routes/health.py`（`image_generation_enabled` 上方注释）
   - `openspec/changes/add-question-image-generation/design.md` D7
     （原文还凭空提到「配额接口与生图接口」—— 这两个端点**根本不存在**）
   - `docs/方案设计文档.md` §15.5
   - `docs/MVP开发计划.md` §7.1（原文把三个开关一起写成「关掉时接口照样能调」）

3. **`tools/scan_secrets.py` 的一次自造误报**（见 8.3）：修 `client.py` 注释的写法。

4. **「能力开关」枚举过期 2 处**（与上面是不同性质，不是同一句错话的扩散）：
   - `backend/app/api/v1/routes/health.py` **文件级 docstring 第 4 条**只写了
     `data.knowledge_base_enabled`，新增配图后应有两个；
   - `frontend/src/services/quiz.ts` 的 `fetchHealth` 注释同样只列了
     `search_enabled` / `key_configured`。
   ⇒ 两处均已改准（补上 `image_generation_enabled` / `knowledge_base_enabled`）。
   这一步的代价已登记：因 `health.py` 属 `backend/app`（在 pytest 采集面内），
   改完必须**再跑一次全量**才有资格说「树是绿的」—— 这正是下面重跑的原因。

> 说明：`KNOWLEDGE_BASE_ENABLED` 那边同样写「不是权限位 / 端点无条件注册」——
> 那些是**对的**（`/kb/*` 八个端点确实无条件注册、关掉仍可调用），
> 与本功能语义不同，未改动。

---

## 终局读数（2026-09-25）

| 闸门 | 命令 | 读数 |
| --- | --- | --- |
| 全量后端测试 | `pytest -q --cov=app` | **1327 passed / 0 failed / 0 error**（退出码 `0`，0 skipped、0 xfail） |
| 类型检查 | `tsc --noEmit --skipLibCheck` | `EXIT=0`，无输出 |
| 凭证扫描 | `python tools/scan_secrets.py` | `EXIT=0`，459 文件**干净** |
| 规格校验 | `openspec validate --all --json` | 5 项 / **0 failed** |
| 双端构建 | `taro build --type weapp` / `--type h5` | 均 `EXIT=0`，`Compiled successfully`（25.46s / 29.85s）|
| 覆盖率 | 同第一条 | `TOTAL 5163 stmts / 343 miss / 93%` |

> **读数的交叉校验**（本项目纪律：不靠单一数字下结论）：`-q` 的末行汇总会被工具链丢掉
> （见 `.workbuddy/memory/REDLINES-toolchain.md`），所以改用两条互相独立的读数对齐 ——
> ① 进度行点号逐字符点清 = **1327 个 `.`**、0 个 `s` / `x` / `F` / `E`；
> ② 另跑 `pytest --collect-only -q` 独立数出 **53 文件 / 1327 条**。两者**逐位一致**。

> ⚠️ **本轮出现过一次「假故障」，已定位并排除**：中途有一轮全量出现
> 满屏 `E`（524 个）、退出码 1，但**与代码无关** —— 报错是 MySQL
> `(1684) Table 'knowsaga_club_test'.'knowledge_documents' … concurrent DDL statement`，
> 即 `conftest.py` 的 `create_all` 与另一个 pytest 进程撞了并发 DDL
> （推断是上一条 `TaskStop` 打断的进程尚未死透）。确认无残留进程 + 测试库
> 元数据锁数为 0 后重跑即全绿。**判据与处置已写进工具链红线**，避免下次误改代码。

> 未验证项只有一条：**8.5 的真链路**（缺 COS 凭据）。其余全部有命令读数或浏览器实测。

> **H5 构建的 2 条告警**（`WARNING in` / `ERROR in` 计数均为 0，构建成功，非阻塞）：
> `AssetsOverSizeLimitWarning`（`js/app.*.js` **246 KiB**，超 webpack 推荐上限 244 KiB）
> 与 `EntrypointsOverSizeLimitWarning`（入口合计 **357 KiB**）。**超出幅度 2 KiB。**
> ⚠️ **未做逐版本对比，所以不宣称这是否由本次改动引入** —— 只记录事实。

> **浏览器实测的证据形态**：全部是 **DOM 读数**（`getBoundingClientRect` 的宽高、
> `clippedPx`、请求体 JSON、后端请求计数），不是「看截图觉得没问题」。
> 原始截图与 DOM 快照留在 `.playwright-mcp/`（已被 `.gitignore` 忽略，未入库）——
> 仅作留痕，**其内容未经过人眼复核**。

---

## 追加变更：生图模型换成 `z-image-turbo`（2026-09-26）

> 触发：需求方指出「并发调用」与「单次最多 6 张」互斥，改用一个**天生只出 1 张**的模型
> （更便宜、更快）。设计决策见 `design.md` **D15**。

- [x] 15.1 **事实核证**：`z-image-turbo` 与 `qwen-image-2.0` 同属百炼
      `MultiModalConversation` 家族（`POST /services/aigc/multimodal-generation/generation`），
      `messages` 结构一致、图片同样在 `output.choices[0].message.content[0].image`
      ⇒ **不用改调用方式**，只改 `IMAGE_MODEL`。
      官方 `parameters` 只文档化 `size` / `prompt_extend` / `seed`；官方错误示例含
      `InvalidParameter: num_images_per_prompt must be 1` ⇒ **多传参数可能 400，不能靠猜**。
- [x] 15.2 **按红线 7 真跑一次端到端**：新增 `backend/scripts/probe_z_image_params.py`
      （手动专用、**会发真实请求**、不进 pytest 采集面）。四种组合全部 200：

      | 用例 | size | 结果 | 耗时 |
      | --- | --- | --- | --- |
      | 仅文档内参数 | 1024*1024 | **200** | 4.12s |
      | **加上我们正在发的 4 个参数**（`n`/`watermark`/`negative_prompt`/`result_format`） | 1024*1024 | **200** | 3.52s |
      | 仅文档内参数 | 512*512 | **200** | 1.42s |
      | **真实提示词**（`build_prompt` 产物，233 字符） | 512*512 | **200** | 1.44s |

      ⇒ 现有参数集**不必删**，换模型确实是配置级改动。
- [x] 15.3 **TDD**：先改断言跑红（`AssertionError: assert 'qwen-image-2.0' == 'z-image-turbo'`），
      再改 `config.py` 默认值跑绿。受影响的两个测试文件 + 其余 6 个配图测试文件
      **161 条全绿**。
- [x] 15.4 **同步 6 处**：`config.py` 注释 / `client.py` 模块头（原文整段是 qwen 专属事实）/
      `.env.example` / `docs/方案设计文档.md` §15.6 / `design.md`（D2 事实依据 + D12 第 5 行 +
      新增 D15）/ `proposal.md`。**任务 1.1 的原文也一并改**（它原样写了旧默认值）。
- [x] 15.5 **假契约排查（铁律 10）**：`IMAGE_NEGATIVE_PROMPT` 与 `IMAGE_WATERMARK`
      **不在 z-image 官方参数表内** ⇒ 四处（config / `.env.example` / 方案设计 §15.6 /
      design D15）统一改成「实测被上游**接受**（200），**是否被采用未验证**」，
      避免把死旋钮读成有效护栏。
      ⚠️ **本项当时还写了「真正的护栏在 `prompt.py` 的正向约束里」——那句话在 16.x 被推翻，
      已改口**（禁令写进正向提示词反而会被画出来）。
- [x] 15.6 **顺带查实**：`prompt_extend` 在两个模型上**默认值相反**
      （qwen-image-2.0 为 `true`、z-image-turbo 为 `false`）⇒ 代码已**显式传**，
      不依赖上游默认。
- [x] 15.7 **人眼验收已做，结论是不达标**（2026-09-26，见第 16 组）：
      新模型出图**三张全部带文字**，不是观感问题而是**泄题**。

### 追加变更的终局读数（2026-09-26）

| 闸门 | 读数 |
| --- | --- |
| 全量后端测试 | **1327 passed / 0 failed / 0 error**（0 skipped、0 xfail），覆盖率 `TOTAL 5163 stmts / 343 miss / 93%` |
| 交叉校验 | 进度行逐字符点数 **1327 个 `.`**；另跑 `--collect-only` 独立数出 **53 文件 / 1327 条** —— 两者**逐位一致** |
| 凭证扫描 | `scan_secrets.py` `EXIT=0`，**460 文件干净** |
| 规格校验 | `openspec validate --all --json` **5 项 / 0 failed** |
| 类型检查 / 双端构建 | **本轮前端零改动** ⇒ 沿用 2026-09-25 读数（`tsc EXIT=0`、weapp / h5 均成功）；**未重跑，也不宣称重跑过** |
| 探针脚本 | `probe_z_image_params.py` **不在 pytest 采集面内**（`testpaths=["tests"]`，实测采集结果不含 `scripts/`）|

> 读数对应的树 = `config.py` / `client.py` / `test_config_image.py` / `test_image_client.py` /
> `probe_z_image_params.py` 的改动。跑闸门期间只动过 `.workbuddy/memory/` 下的 `.md`
> （不在采集面内），不影响读数。

> ⚠️ **本轮另修掉一个与配图无关的潜伏 bug（必须记）**：`_submit_body` 写的是
> `int(utcnow().timestamp() * 1000)` —— `utcnow()` 是 **naive**，Python 的 `.timestamp()`
> 把它**当本地时间**解释，整串时间戳**早 8 小时**（实测差值正好 `28800` 秒）。
> 在**本地 00:00–08:00** 会把 `finished_at` 压回**前一天** ⇒ `test_streak_boundaries` 的
> 「昨天 / 前天」两条断言**刚好互换**（期望 2 得 1、期望 1 得 2），而白天跑全绿 ——
> 同一棵树**晚上绿、凌晨红**。已把 8 处（`test_attempt_api.py` 7 + `test_report_api.py` 1）
> 统一换成项目自带的 `timeutil.to_timestamp_ms()`（内部 `as_aware_utc` 把 naive 标成 UTC），
> 并在 `_submit_body` 的 docstring 写明「别改回去」。**纯测试侧**，生产链不受影响
> （前端发真 epoch ms、服务端走 `from_timestamp_ms`）。判据已写进
> `.workbuddy/memory/REDLINES-backend.md` 测试红线第 5 条。

> ⚠️ **操作教训**：本轮我曾**并发起第二轮全量 pytest**（第一轮仍在后台跑），
> 既撞了已知的并发 DDL 风险，又覆盖了日志 —— 导致那轮的 3 条 `FAILED` 混入了污染产物。
> **绝不可并发跑全量 pytest**；确认无残留进程 + 元数据锁为 0 后再起。

## 追加变更 II：提示词形态改造（2026-09-26，人眼验收驱动）

> 第 15 组的「未验证项 15.7」就是这一组要解决的事。**这不是新功能，是缺陷修复** ——
> 规格 `question-images` 要求「画面里不出现任何文字」，而第 15 组交付的实现
> **实际违反了它**：真链路跑通（3/3、回读 200）之后把图下载下来人眼看，
> **三张全部带文字**，包括题干、错字乱码，甚至我们提示词里的**指令原文**。

- [x] 16.1 **先改测试契约再改实现（TDD）**：删掉两条**守手段而非守结果**的断言 ——
      `test_prompt_forbids_text_in_image`（断言「不得出现任何文字」在提示词里）、
      `test_prompt_asks_for_neutral_illustration`（断言「不表达对错」在提示词里）——
      它们守的那个手段被实测证伪。换成形态断言：无换行/无编号、无元指令、
      题干整句不进（对 5 条样本参数化）、无疑问成分、主题必须被压成名词短语（6 组真实题干）。
      **跑红 16 条**（旧实现的输出把问题原样打印了出来）。
- [x] 16.2 **改实现**（`app/llm/image/prompt.py`，三处）：
      ① 主题短语化（`_first_cut_index` 在疑问/谓语词处切 + `_trim_particles` 剥悬空虚词；
         单字切词门槛 `_SINGLE_CHAR_CUT_MIN=6`，否则 `人工智能` 会被从 `能` 切开）；
      ② `build_prompt` 改单段逗号描述（`{主题}，{知识点}，{风格尾缀}`）
         —— 无编号、无冒号标签、**一句否定句都不写**；
      ③ 新增 `_derender_latin` 摘拉丁字母 token，带「摘完不够画就不摘」的保护。
      **37 条全绿**。
- [x] 16.3 **风格尾缀必须点明「静物」**：`静物摄影，主体居中，背景干净，纯色背景`。
      实测依据：尾缀为「写实摄影…自然光」时 z-image 把「光合作用」画成**人物特写**
      （旧实现的「不出现人脸特写」禁令被删掉后无人拦它）；换静物 ⇒ 同一题变**灯泡**。
      `静物` 本身排除人像 —— 这是**不用否定句**达成约束的办法。
- [x] 16.4 **人眼比对（5 轮 / 21 张图，全部真跑，串行避开 429）**：
      z-image+旧尾缀 → 咖啡豆 ✅ / TCP 大字 ❌ / 人像 ❌；qwen+旧尾缀 → 咖啡豆 / 花 / 花（0/3 文字）；
      z-image+静物 → 咖啡豆 ✅ / TCP 大字 ❌ / 灯泡；z-image+静物+**摘字母** →
      咖啡豆 ✅ / **四端接头** ✅ / 灯泡；qwen+静物+保留字母 → 咖啡豆 / **枫叶**。
      ⇒ **换模型解决不了**（qwen 的「没文字」是以彻底忽略主题为代价的）⇒ 保留 `z-image-turbo`。
- [x] 16.5 **摘字母的保护边界**（实测反例）：`Python 的 GIL` + `CPython 并发` 摘完只剩「并发」
      ⇒ 模型抓风格先验自由发挥，画出**一支口红**。⇒ 摘完中文 < 6 字整个不摘（`_MIN_KEPT_CHARS`）。
      **代价**：字母密集的题上「画面不出现文字」可能做不到 —— 如实登记为已知边界。
- [x] 16.6 **顺带修掉两个「隐性依赖本机 `.env`」的脆弱测试**（与提示词改动无关，
      都是第 15 组改 `.env` 的余波，在下一轮全量才爆出来）：
      ① `test_image_generate.py::test_budget_aborts_remaining` —— 依赖「池装得下 3 个任务」，
         而 `.env` 为避 429 把 `IMAGE_MAX_WORKERS` 改成了 2；
      ② `test_health_api.py::test_health_image_flag_tracks_credentials` —— 隐含假设
         「基线没有 COS 凭据」，而 `.env` 为做端到端验收真配上了。
      ⇒ 修法双管：`TEST_ENV` 补钉 `IMAGE_MAX_WORKERS`（= **代码默认值**，不写死数字）
      与 **COS 五项为空**（与
      `IMAGE_GENERATION_ENABLED` 同一套理由）+ 两条用例各自**显式声明前提**。
      已提炼为项目铁律 11。
- [x] 16.7 **文档同步**：`design.md` 新增 **D16**（本轮全部实测与取舍）、修正 D4 与 D15 里
      已被推翻的措辞；`config.py` / `client.py` 的注释改口（「真正的护栏是正向约束」
      → 「正向通道一个字都别提文字，抓手是提示词**形态**」）；`REDLINES-backend.md` 生图节重写。
- [x] 16.8 **终局验收**：真链路 `verify_image_chain.py` **3/3 / 回读 HTTP 200 / 零 429 / 7.2s**，
      人眼确认**三张全部无文字**（咖啡豆 / 四端接头 / 灯泡），COS 旧图已被覆盖。
      证据 `docs/image-chain-evidence-2026-09-26.txt`。
- [x] 16.9 **仍未验证 / 已知边界**（不宣称）：抽象概念题（TCP/RAG/HTTP）画面相关性有限，
      模型会挑随机静物；字母密集的题可能带字母；`negative_prompt` 对 z-image 是否生效仍未验证。
      ⇒ **换模型 / 改尾缀 / 改提示词结构之后必须重跑人眼验收**（单测只能断形态）。
      （本条是**登记项**，边界已如实写下即视为完成；同 18.12。）

### 追加变更 II 的闸门读数（2026-09-26）

| 闸门 | 读数 |
| --- | --- |
| 全量 pytest | **1350 passed / 0 failed / 0 error**（`EXIT=0`）。**双读数交叉校验**：进度行逐字符点数 **1350 个 `.`**；另跑 `--collect-only -q` 独立汇总 **53 文件 / 1350 条** —— 逐位一致。比第 15 组的 1327 多 23 条，正是 `test_image_prompt.py` 18 → 41 |
| 凭证扫描 | `scan_secrets.py` `EXIT=0` |
| 规格校验 | `openspec validate --all --json` **5 项 / 0 failed** |
| 真链路 | `verify_image_chain.py` `EXIT=0`，3 张全出 + 回读 `HTTP 200`，零 429 |
| 类型检查 / 双端构建 | **本轮前端零改动** ⇒ 沿用 2026-09-25 读数（`tsc EXIT=0`、weapp / h5 均成功）；**未重跑，也不宣称重跑过** |

> ⚠️ **全量跑了两次，两次都不是白跑**：第一次（8m3s）红了
> `test_health_api.py::test_health_image_flag_tracks_credentials` —— 与提示词改动无关，
> 是 `TEST_ENV` 没钉 COS 凭据导致本机 `.env` 漏进测试（任务 16.6 的第 ② 项）；
> 修完 `conftest.py` 后重跑（8m4s）才全绿。**这正是铁律 9 的又一次实证**：
> 改了 `conftest` 这种全局夹具，子集绿不算数，必须全量。

> 本组改的是 `app/llm/image/prompt.py`、`tests/test_image_prompt.py`、`tests/conftest.py`、
> `tests/test_image_generate.py`、`tests/test_health_api.py`，以及三份注释/文档。

---

### 追加变更 III：并发默认值 `3 → 2` + `.env.example` 补齐（2026-09-26）

由「检查 `.env` 与 `.env.example` 是否同步」触发，查出两件事（键集本来就同步，
**但模板的注释与本轮的实现改动脱节了**）：

- [x] 17.1 **`IMAGE_MAX_WORKERS` 默认值 `3 → 2`**（design **D17**）。起因是端到端抽验时
      配图成功率只有 2/3；实测「并发 3 必挂 1 个 429」（两次复现、指纹一致，且
      **两个模型同样中招** ⇒ 是账号级 RPS 配额，**不是模型问题**）、
      「并发 2 连跑 4 轮 8 张全过、零 429」。且 `client.py` **没有重试** ⇒ 撞 429 = 那题没图。
      ⇒ 默认值取**验证过的 2**，而不是当初拍脑袋、从未验证的 3。
      **TDD**：先改 `test_config_image.py` 断言 `== 2` 跑红（`assert 3 == 2`），再改
      `config.py` 跑绿。
- [x] 17.2 **同步面六处**：`config.py` 默认值与注释 / `.env.example` 模板值与注释 /
      `conftest.TEST_ENV` 钉值（注释里「运维取值」的措辞一并改为「代码默认值」）/
      `test_config_image.py` / design D3 表 + 新增 D17 / 方案设计 §15.6 配置表。
- [x] 17.3 **修掉 `.env.example` 里一处「假契约」**（铁律 10）：`IMAGE_NEGATIVE_PROMPT`
      的注释原写「……且**明确要求画面不出现文字**」，而这句约束**已被实测证伪、
      并已从 `prompt.py` 删除** ⇒ 注释在描述一个**不存在的实现**。改成如实口径：
      negative_prompt 拦不住文字（反例：里面就写了「文字, 汉字, 字母」，画面照样满屏），
      真抓手是提示词**形态**，且「画面有没有文字」**单测断言不了**、只能人眼看图。
- [x] 17.4 **补上 `.env.example` 里 `IMAGE_MAX_WORKERS` 缺失的 429 说明**：原来只有一句
      「并发生图的最大线程数。」，从模板**完全看不出**这个键与上游限流有关 ——
      照抄模板就会踩坑（这正是「注释该写而未写」的另一面）。
- [x] 17.5 **键集核对**：`.env` 与 `.env.example` **86 = 86**，零缺失零多余。
      其余 **17 处值差异全部正常**（凭据留空、开关默认关）—— **模板不该照抄本机值**。
- [x] 17.6 **闸门（全绿）**：全量 `pytest` **1350 passed / 0 failed / 0 error**（`EXIT=0`，8m10s；
      **双读数交叉校验一致** —— 进度行逐字符 **1350 个 `.`**，另跑 `--collect-only -q`
      得 **53 文件 / 1350 条**）/ `scan_secrets` **EXIT=0**（461 文件 / 0 命中）/
      `openspec validate --all` **5 项全有效 / 0 失败**。
      本轮**前端零改动** ⇒ `tsc` / 双端构建沿用 2026-09-25 读数，**未重跑、也不宣称重跑**。

> ⚠️ **仍未做**：429 的**指数退避重试**。降并发只是「贴着配额用」，配额一波动照样失败；
> 重试才是「上游忙 ⇒ 稍后重来」的正解，且能支撑更高的并发。**属独立行为变更，不在本次**。

## 追加变更 IV：AI 挑选配图题（2026-09-26，成本驱动）

> 起因：接入配图时的口径是「勾了就每道题都配」。配图**逐张计费**，而一套 5 道题里
> 往往 2–3 道是抽象概念 / 纯逻辑 / 文字表述题 —— 画出来对理解没有增益（人眼验收里
> 被画成花、枫叶、灯泡）。用户提出「由 AI 自主判断哪些题需要图，以省成本」。
> 决策与三种方案的取舍见 design **D18**。

- [x] 18.1 **判断放哪一步**（三选一，取第三个）：出题时顺带标注（零额外调用，
      但要改 `QuizDraft` 与出题 Prompt，同时引入「出题成功率」与「判断准确度」
      两个新风险）/ 服务端写死关键词规则（直接违背「AI 自主判断」）/
      **出题后单独判一次**（采用：零契约变更、独立可测、可独立降级）。
- [x] 18.2 **TDD 先红**：新建 `tests/test_image_select.py`（14 条），首跑
      `ImportError: cannot import name 'selector'` ⇒ 红。
- [x] 18.3 **实现判断器**：新增 `app/prompts/image_select_prompt.py`（正/反面准则 +
      上限 3 道 + json 示例放 System 里以避开模板解析）与 `app/llm/image/selector.py`；
      `output_schemas.ImageSelectionDraft.ids` **刻意不给默认值** —— 模型漏字段时必须
      撞校验错误并回退「全部配图」，而不是被解读成「一道都不需要」。
- [x] 18.4 **接入配图段**：`quiz_service._render_images` 改为「判断 → 筛选 → 生图」；
      收尾文案三种情形分开说（`REASON_NO_NEED` / `attempted == 0` / 实际张数），
      分母改用**选中数**而不是总题数；`llm/image/__init__.py` 新增 `REASON_NO_NEED`。
- [x] 18.5 **修掉一处同类兜底漏洞**（写用例时发现）：`_render_images` 的 docstring 写着
      「不抛异常」、且对生图段兜了一层 try，但**新加的判断那一步没有兜** ——
      正是「契约说不会抛 ≠ 真不会抛」。已补 try，兜底语义取 selector 自己的降级：
      **回退全部配图**。
- [x] 18.6 **把判断器纳入测试替身面（红线）**：`test_quiz_image_flow.py` 的 autouse 夹具
      原本只钉了出题链与生图段，而判断走的是 **DeepSeek 且本机 `.env` 的 Key 是真的** ——
      不钉就是每条用例真发一次模型请求。另在 `conftest.TEST_ENV` 补钉
      `IMAGE_SELECT_ENABLED`（第三个同源坑，见铁律 11）。
- [x] 18.7 **前端文案同步**（铁律 2 / 4）：`HALL_IMAGE_COPY.on`「每题配图」→「智能配图」、
      `KB_GENERATE_COPY.imageOn`「每道题配一张图」→「自动挑选配图」，说明文字补上
      「只给用得上插图的题配图，所以不是每道题都有图」；`types/api.ts` 里
      `image_url` 为 `null` 的成因清单补一项。
- [x] 18.8 **规格 delta 修订**：那条 MUST 从「为**每道题**生成一张图」改成
      「**先判断哪几道值得配图**，为这些题各生成一张」，并新增两个 Scenario
      （判断认为都不需要 / 判断失败时回退全部配图）；额度段新增
      「判断省下的额度要退回」。
- [x] 18.9 **同步面**：`config.py` 两个新键 / `.env.example` 与 `.env` 同键集
      （**88 = 88**）/ 方案设计 §15.6 / design D18 / 本节任务。另顺手修掉 `.env` 里
      `IMAGE_NEGATIVE_PROMPT` 的**旧版假契约注释**（上一轮只改了模板、漏了 `.env`）。
- [x] 18.10 **闸门（全绿）**：
      - 全量 `pytest` **EXIT=0 / 1371 passed / 0 failed**（比上一轮 1350 多 21 条，
        即本次判断器新增用例）。⚠️ 本机 pytest 的 `=== N passed ===` 汇总行会被环境吞掉
        （连 14 条最小用例也不打印）⇒ 判绿取**三读数一致**：退出码 0 + 进度点
        **1371 个 `.`**、无 `F`/`E` + `--collect-only` 报 **54 文件 / 1371 条**。
      - `scan_secrets` **EXIT=0**（464 文件 / 0 命中）。
      - `openspec validate --all` **5 passed / 0 failed**（含 2 条既有 RFC-2119 警告）。
      - 前端本轮**有改动**（`quiz` 页文案 + `types/api.ts` 注释）⇒ `tsc`
        （`tools/run_frontend_typecheck.py`）**exit=0**；
        双端构建 **weapp `Compiled successfully in 21.40s` / EXIT=0**、
        **h5 `webpack 5.91.0 compiled with 2 warnings in 25837 ms` / EXIT=0**
        （2 条 warning 均为既有 entrypoint 体积提示，非本次引入）。
- [x] 18.11 **真链路验证（判断器部分已做；出图部分受凭据阻塞）**：
      真调判断器两次，**两组对照**证明它在真区分，而不是一律不选 ——
      A 组（水温区间 / 设计模式 / GIL / 光合作用步骤 / HTTP 404）⇒ **`ids=[]`**（1.37s）；
      B 组（羽状复叶 / 屋顶样式 / 酒精灯加热部位 / 咖啡变色 / 哺乳动物分类）⇒
      **`ids=['b1','b2','b5']` 选中 3/5**（0.48s，正好卡 `MAX_SELECTED=3` 上限）。
      ⇒ 「宁缺勿滥」是**正确的保守**：空集是合法结果，不是失效；5 张 → 实际 0~3 张，省成本成立。
      探针 `backend/scripts/` 之外的一次性脚本未入库（只留读数）。
      ⚠️ **仍未做**：端到端「只对选中的题真出图」—— 被 **COS 四键为空**阻塞
      （`image_generation_available=False`）。该段目前**只有测试替身覆盖**
      （`test_quiz_image_flow.py::test_selection_narrows_the_targets` /
      `test_quota_counts_only_the_selected_and_succeeded`），**不宣称真跑过**。
- [x] 18.12 **未验证项如实登记**：① 判断准确度只做过 **2 组 × 5 题**的真调用抽查，
      **无量化指标**（没有标注集，也算不出 precision/recall）；
      ② 判断器**不感知**当日剩余额度（按「值不值得画」判断，不按「今天还剩几张」判断）；
      ③ **端到端出图未真跑**（见 18.11，受 COS 凭据阻塞）。


