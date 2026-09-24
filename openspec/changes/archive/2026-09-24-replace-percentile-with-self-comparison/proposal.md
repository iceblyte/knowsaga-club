# Proposal

## Why

成绩单上印着「本局超过社团里 43% 的冒险者」和「按社团里 7 位冒险者的最佳正确率计算」。这两句都不成立：

- **「社团」在产品里没有任何数据实体** —— 库里没有 guild / club / 成员表，「公会社交」是 P2 占位页。
  池子的真实定义是「全站所有答过题的用户」，文案却把它说成「社团里」：给一个不存在的组织单位
  赋予了真实的统计含义。
- **43% 是假精度**：池子 7 人时它只能是 `3 ÷ 7`，即 1/7 粒度上的一个离散值被包装成连续百分比。
  复算那份池子（0/20/80/100/100/100/100）还能得到更荒谬的结论 —— **答对全部题目的用户看到的也是 43%**
  （另外 4 位满分按「并列不算超过」被排除）。
- **口径不可比**：拿「你这一局」比「别人的历史最佳」，比的还是别人**另一份副本**的成绩。
- 「按…最佳正确率计算」是内部实现口径，不该印在用户的成绩单上。

根子在 2026-09-23 那次修复：把「（演示数据）」换成了真实池子，等于**用一份真实但不可比、且样本不足的
数字，替换掉一份假的数字**，并为了让数字显得可信补了一句解释 —— 结果比原症状更糟。

## What Changes

- **BREAKING（数据库）**：`attempts` 删除 `percentile` / `percentile_pool` 两列（幂等迁移，含存量 25 条旧值）。
- **BREAKING（接口）**：`AttemptSummary` / 报告文档 / 归档记录删除 `percentile` / `percentile_pool` /
  `percentile_label` 三个字段。
- 结算页与冒险日志页那一格改为**纵向自我比较**：只说「比过去的自己怎么样」，用「答对几题」表达，
  不出现任何百分比。
- 新增服务端判定的进度状态（首局 / 刷新纪录 / 追平纪录 / 好于上一局 / 与上一局持平 / 差于上一局）与
  最好成绩、上一局成绩等数据；前端只做「状态 → 文案」映射，不写任何比较逻辑（两页必须逐位一致）。
- 删除服务端百分位计算链路（`percentile_service`、`pool_percentile`、`percentile_label_for`），
  提交一局不再做全站聚合查询。
- 统计句里的「社团」全部消失；世界观包装用法（社团大厅、返回社团大厅）保留不动。

## Capabilities

### New Capabilities

- `attempt-progress`: 一局结束后把本局成绩与**该用户自己的**历史记录比较、并在结算页 / 冒险日志页呈现的
  能力 —— 状态判定与优先级、数据来源与口径、文案映射规则、首次挑战的兜底，以及「不做任何横向比较」
  这条硬边界。

### Modified Capabilities

无。现有基线 `knowledge-retrieval` / `quiz-grounding` 与本次无关；被撤下的百分位从未进入 spec 基线。

## Impact

- **页面**：`frontend/src/pages/settle`、`frontend/src/pages/report`（含 `index.scss`）、
  `frontend/src/constants/copy.ts`、`frontend/src/utils/scoring.ts`、`frontend/src/types/api.ts`。
- **接口**：`POST /attempts`（响应 `summary`）、`GET /reports/{id}`、`GET /attempts`（列表项）。
- **数据表**：`attempts` 删两列，DDL 进 `backend/sql/`（`06_*.sql`），用 `scripts/apply_sql.py` 执行。
- **代码**：`backend/app/services/{percentile_service.py 删, scoring.py, attempt_service.py, report_service.py}`、
  `backend/app/models/{attempt,archive,report}.py`、`backend/app/db/tables.py`、
  `backend/scripts/{backfill_percentile.py 删, verify_report_chain.py, verify_user_chain.py}`。
- **测试**：`test_attempt_api.py`、`test_report_api.py`、`test_scoring.py`、`test_report_schema.py`、
  `test_badge_service.py`。
- **文档**：`docs/MVP开发计划.md`、`docs/方案设计文档.md`、`frontend/src/constants/copy.ts` 文件头
  （登记与原型第 1 屏的有意偏离）。

## Non-goals（不做什么）

- **不做任何形式的横向比较** —— 不与他人比、不与全站比、不出现「社团里 N%」、不做排行榜、不做百分位。
  这一条本期是硬边界，不是「暂缓」。
- 不做「同副本内比较」（同一份题集挑战者之间的比较）这个将来可能的形态 —— 它需要样本门槛，
  内测期无意义。
- 不做「最近 N 局趋势图」这个视觉化呈现（本期列入后续可选）。
- 不做百分位历史值的保留与口径迁移：两列直接删除，不备份进库。
- 不改判题 / XP / 金币 / 勋章 / 错题复习等既有逻辑。
- 不改原型第 1 屏这一格以外的任何 UI。
