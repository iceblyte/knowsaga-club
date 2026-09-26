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
      `image_size: str = "512*512"`、`image_max_workers: int = 3`、
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
      并点明真正的护栏在 `prompt.py` 的正向约束里。避免把死旋钮读成有效护栏。
- [x] 15.6 **顺带查实**：`prompt_extend` 在两个模型上**默认值相反**
      （qwen-image-2.0 为 `true`、z-image-turbo 为 `false`）⇒ 代码已**显式传**，
      不依赖上游默认。
- [ ] 15.7 **未做、也不宣称已验证**：新模型的实际出图质量、以及「画面不出现文字」的达成率 ——
      图片内容无法自动断言，需人眼看图。本次**未看**。

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
