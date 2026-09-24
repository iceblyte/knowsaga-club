# Tasks

## 1. 后端：自我比较的判定（TDD）

- [x] 1.1 写 `backend/tests/test_progress_service.py`：覆盖六种状态、优先级冲突（同时满足 record 与 tie_best 时取 record）、首局无基准、并列不算刷新。跑 `pytest tests/test_progress_service.py` 必须红（模块尚不存在）
- [x] 1.2 实现 `backend/app/services/progress_service.py` 的纯判定部分（入参是「本局答对题数 + 上一局 + 此前最好」，不碰库）。1.1 全绿
- [x] 1.3 在 1.1 的文件里补取数口径测试：只取本人、只取 `status='finished'`、`before_attempt_id=None` 取全量、`before_attempt_id=N` 只取 `id < N`、`attempt_count` 含本局。跑红
- [x] 1.4 实现 `progress_service.for_attempt(session, *, user_id, correct_count, before_attempt_id)`（上一局 + 此前最好 + 计数，三条查询）。1.3 全绿
- [x] 1.5 `backend/app/models/attempt.py`：新增 `AttemptProgress` 与 `AttemptScorePoint`，`AttemptSummary` 删除 `percentile` / `percentile_pool`、新增 `progress`。`python -c "import app.models.attempt"` 无导入错误
- [x] 1.6 写结算链路测试（`backend/tests/test_attempt_api.py`）：响应 `summary.progress` 六态正确、`summary` 中不存在 `percentile*` 字段、重复提交（幂等回放）与首次逐位一致。跑红
- [x] 1.7 实现接入：`backend/app/services/attempt_service.py` 在**落库前**算 progress（`before_attempt_id=None`），`_replay` 用 `before_attempt_id=attempt.id`，`_write_attempt` 停止写两列。1.6 全绿

> 执行记录：1.1–1.7 全部完成（`pytest tests/test_attempt_api.py tests/test_progress_service.py` 61 passed）。
> 两处偏离：
> ① 顺序上先做了 1.5 的**新增类型**（`AttemptScorePoint` / `ProgressState`）再写 1.2 —— 1.1 的测试要
>    import 那个类型，不先加就只能测一个裸字符串；`AttemptSummary` 的字段增删仍放在 1.5 做。
> ② 契约比 `design.md` D3 多一个 `delta_vs_best`：D3 的立意是「前端连减法都不用做」，
>    而「刷新纪录」那句文案（「比之前最好的一局多答对 N 题」）缺了它就必须在前端做减法。

## 2. 后端：删除百分位链路

- [x] 2.1 写报告侧测试（`backend/tests/test_report_api.py` / `tests/test_report_schema.py`）：报告响应含 `progress` 且不含 `percentile*`；历史报告的基准只含该局之前的记录。跑红
- [x] 2.2 实现 `backend/app/services/report_service.py`（`_load_snapshot` 算一次 progress 存进 `_Snapshot`，`merge_draft` 取用）与 `backend/app/models/report.py`（删 `percentile` / `percentile_pool` / `percentile_label`）。2.1 全绿
- [x] 2.3 `backend/app/models/archive.py` 与列表接口去掉 `percentile` / `percentile_pool`；同步改 `tests/test_attempt_api.py` 里列表相关断言。`pytest tests/test_attempt_api.py` 全绿
- [x] 2.4 删除 `backend/app/services/percentile_service.py`；`backend/app/services/scoring.py` 删除 `pool_percentile`、`_PERCENTILE_BANDS`、`percentile_label_for`；删 `tests/test_scoring.py` 里对应用例与 `tests/test_badge_service.py:373` 的 `percentile=0` 构造。`pytest tests/test_scoring.py` 全绿
- [x] 2.5 `backend/app/db/tables.py` 与 `backend/sql/01_schema.sql` 删除两列定义（含注释）。`pytest tests/ -k "attempt or report"` 全绿
- [x] 2.6 删除 `backend/scripts/backfill_percentile.py`；`backend/scripts/verify_report_chain.py` 与 `verify_user_chain.py` 去掉分位断言（顺带清掉 `verify_user_chain.py` 里残留的旧公式 `min(95, max(5, round(100*0.9)))`）。`python -m py_compile` 两个脚本无错

## 3. 前端

- [x] 3.1 `frontend/src/types/api.ts`：删除三处 `percentile*` 字段，新增 `progress` 类型（与后端契约逐字段对齐）。`node node_modules/typescript/bin/tsc --noEmit --skipLibCheck` 能跑（允许此步报出待改页面的错）
- [x] 3.2 `frontend/src/constants/copy.ts`：删除 `SETTLE_COPY` / `REPORT_COPY` 里的 `percentilePrefix/Suffix/Note/NoPool`，新增共用的 `PROGRESS_COPY` 与「状态 → { title, note }」映射函数；文件头补记与原型第 1 屏的有意偏离。`tsc` 报错点应只剩两页
- [x] 3.3 `frontend/src/pages/settle/index.tsx`：那一格改用 `progress`，只渲染标题行，删除 `view.percentile` 分支。`tsc --noEmit` 通过
- [x] 3.4 `frontend/src/pages/report/index.tsx` + `index.scss`：标题行 + 说明行 + `record` 时渲染「新纪录」胶囊；进度条宽度改读本局准确率。`tsc --noEmit` 通过且 `git diff --stat` 里 scss 只有这一格相关改动
- [x] 3.5 `frontend/src/utils/scoring.ts` 清理分位相关注释；确认全仓 `grep -ri percentile frontend/src backend/app` 只余零命中。`tsc --noEmit` 通过

## 4. 数据迁移

- [x] 4.1 备份 `attempts` 的 `id / user_id / correct_count / total_count / percentile / percentile_pool` 到 `D:\备份\WorkBuddy\knowsaga-club\2026-09-23\`，用独立命令复核行数与文件大小后再继续
- [x] 4.2 新增 `backend/sql/06_drop_attempts_percentile.sql`（先查 `information_schema` 存在才 DROP），用 `scripts/apply_sql.py` 执行；`SHOW COLUMNS` 确认两列已消失；**再执行一次**验证幂等（第二次仍成功）
- [x] 4.3 重启 `:8000` 并核对进程启动时间晚于本次改码时间（否则会按旧逻辑验收）

## 5. 文档

- [x] 5.1 更新 `docs/MVP开发计划.md` 与 `docs/方案设计文档.md` 里关于百分位的描述，写明替换为纵向比较及其理由

## 6. 全量闸门与端到端

- [x] 6.1 全量闸门：`pytest`（带 `CODEBUDDY_SAFE_DELETE_ENABLED=0` 与 `--basetemp=../.tmp_pt_base`，看「点号全满 + 无 F/E + TOTAL 覆盖率」）+ `tsc --noEmit --skipLibCheck` + `frontend/scripts/check_scoring_parity.mjs` + `python tools/scan_secrets.py`，四项全过
- [x] 6.2 端到端：起后端与跑 `backend/scripts/verify_user_chain.py --skip-generate` 在同一条命令内完成，`--out` 落盘；确认新交一局的响应里 `progress` 状态符合预期且库里不再写两列
- [x] 6.3 浏览器实跑结算页与冒险日志页，给出实测证据：进度条宽度 = 本局正确率、`record` 时胶囊文案为「新纪录」、说明行文本正确、整屏无「社团」统计字样

> 执行记录：2.1–6.3 全部完成（2026-09-24）。
>
> **闸门（6.1）**：`pytest` 938 passed / 0 failed（基线 926，本次 +12）、覆盖率 93%（与基线持平）、
> `tsc --noEmit --skipLibCheck` exit 0、`check_scoring_parity.mjs` exit 0、`scan_secrets.py` 无命中。
>
> **端到端（6.2）**：`verify_user_chain.py` 连跑两次均 47/47；定向脚本实测「落库前算 progress」——
> 提交后 `attempt_count` 由 3 变 4（含本局），`best` 与提交前一致，响应无任何 `percentile*`，
> `SHOW COLUMNS` 确认库里已无两列。
>
> **浏览器（6.3）**：H5 构建后 390×844 实跑，两个新用户造出全部关键态：
> - `first`：结算页「这是你的第一份成绩」，无可见「社团」；
> - `same`：结算页「和上一局一样」；
> - `record`：结算页「刷新了自己的纪录」；冒险日志页进度卡四条同时命中 ——
>   标题「刷新了自己的纪录」、胶囊「新纪录」（单行，未被压成两行）、
>   进度条量得宽度占比 20.00% = 本局正确率、说明行「比之前最好的一局多答对 5 题」，
>   整屏无「社团」统计字样。
>
> **顺带修掉一个静默 Bug（不在原任务书内）**：进度条的内联色原写成 camelCase 的
> `backgroundColor`，被浏览器当未知属性丢弃 → 条形一直退回基座的黄铜色，与环形图色阶对不上
> （实测改前 `rgb(200,145,42)`、改后 `rgb(166,58,46)`）。已在调用点改 kebab-case
> 并让 `styleOf` 归一 camelCase，坑记在 `frontend/src/utils/style.ts` 文件头「坑三」。
>
> **已知限制（不在本次范围）**：H5 下 `AccuracyRing` 的 canvas 弧不绘制（画布 0 个不透明像素，
> 屏幕上看到的只是 CSS 的 `.ring__track` 一圈）。这是既有问题、与本次改动无关
> （本次对该组件仅加了 `export`），真机验证见项目记忆。
