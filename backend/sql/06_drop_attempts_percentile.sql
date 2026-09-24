-- ============================================================
-- 知拾冒险社 · 增量变更 06：删除 attempts.percentile / percentile_pool
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：两个库各跑一次（业务库 knowsaga_club / 测试库 knowsaga_club_test）
--
--     cd backend
--     ./.venv/Scripts/python.exe scripts/apply_sql.py sql/06_drop_attempts_percentile.sql
--
-- 参考：openspec/changes/replace-percentile-with-self-comparison/
--       （proposal / design / tasks —— 本次变更的完整来龙去脉）
--       backend/app/services/progress_service.py —— 替代它的那个东西
--
-- ## 为什么删
--
-- 这两列支撑的是界面上那句「本局超过社团里 43% 的冒险者」。那句话有三层问题：
--
--   1. 「社团」在产品里没有数据实体 —— 库里既没有 guild / club 表，也没有
--      成员关系表。那两个字的实际含义是「全站答过题的人」，等于把一个虚构的
--      组织名称套在真实统计池上；用户从没加入过什么社团，却被告知「社团里
--      有 7 位冒险者」。
--   2. 7 人池子只有 1/7 的粒度，43% 是把 42.86% 包装成的假精度 —— 它比
--      当初那句「（演示数据）」更隐蔽，因为它看起来是真的。
--   3. 拿「你这一局」比「别人的历史最佳」（而且是别人**另一份副本**的最好
--      成绩），三个变量都不是同一个东西，这个比较在语义上不成立。
--
-- 替换它的是 `summary.progress` / `report.progress`：与**自己的历史**比，
-- 用「答对几题」说话，不用百分比。新口径**不需要落任何列** —— 状态在读取时
-- 按「截至该局之前的记录」重算；落库反而会变成假话（用户后来又刷新了纪录，
-- 旧那一局的报告仍旧宣称「这是你的最好成绩」）。
--
-- ## 存量数据
--
-- 两列删除前的值已导出留底：
--
--     D:\备份\WorkBuddy\knowsaga-club\2026-09-23\attempts-percentile-*.csv
--
-- 导出**只做留底，不做迁移**：旧值在新口径里没有任何对应物，这不是「换个
-- 算法重算」，而是这一格换了要回答的问题。
--
-- ## 与 01_schema.sql 的关系
--
-- 01 的 CREATE TABLE 原本也含这两列，本次已同步移除（新库一次到位，不含它们）。
-- 本文件只服务于**已经建过表的库**，即 2026-09-23 之前建起来的业务库与测试库。
-- MySQL 不支持 `DROP COLUMN IF EXISTS`，因此用 information_schema 判断 +
-- 预处理语句实现幂等，可重复执行。
--
-- ⚠️ `05_attempts_percentile_pool.sql` 与本次方向相反（它加列，本文件删列）。
-- 05 只对 2026-09-23 之前建过表的库有意义；在那种库上依次跑 05 → 06 之后，
-- 最终状态与本仓现在的 01_schema.sql 一致。**不要**在按新 01 建出来的库上
-- 回放 05 —— 它的第 2 步（改 `percentile` 的列注释）会因列已不存在而报
-- `Unknown column`，而那与「迁移失败」无关。
-- ============================================================

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- 1. 删 percentile_pool（幂等）
-- ------------------------------------------------------------
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'attempts'
    AND COLUMN_NAME = 'percentile_pool'
);
SET @ddl := IF(
  @col_exists = 1,
  'ALTER TABLE `attempts` DROP COLUMN `percentile_pool`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. 删 percentile（幂等）
-- ------------------------------------------------------------
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'attempts'
    AND COLUMN_NAME = 'percentile'
);
SET @ddl := IF(
  @col_exists = 1,
  'ALTER TABLE `attempts` DROP COLUMN `percentile`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 3. 自检（两列都应输出 0）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attempts'
       AND COLUMN_NAME = 'percentile') AS has_percentile,
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attempts'
       AND COLUMN_NAME = 'percentile_pool') AS has_pool;
