-- ============================================================
-- 知拾冒险社 · 增量变更 05：attempts.percentile_pool
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：两个库各跑一次（业务库 knowsaga_club / 测试库 knowsaga_club_test）
--
--     cd backend
--     ./.venv/Scripts/python.exe scripts/apply_sql.py sql/05_attempts_percentile_pool.sql
--
-- 参考：docs/MVP开发计划.md §9.4（本次重写）、backend/app/services/percentile_service.py
--
-- ## 为什么需要它
--
-- `percentile` 原本是演示值（`clamp(round(accuracy × 0.9), 5, 95)`），界面上必须
-- 挂一句「（演示数据）」。2026-09-23 起改成按**真实社团成员**的最佳正确率算，
-- 于是出现一个只有新口径才有的状态：**社团里还没有别的冒险者**。
--
-- 那 0–100 的 `percentile` 列写什么都是假的（写 100 是「超过了自己」，
-- 写 0 是「谁也没超过」）。所以判据必须另存一列：
--
--   * `percentile_pool = 0` → 没有可比对象，`percentile` 那一格**不许显示**；
--   * `percentile_pool = N` → 分位按 N 个人算出来的，界面上的说明文案也照它写
--     （「按社团里 N 位冒险者的最佳正确率计算」）。
--
-- 为什么不用「把 `percentile` 改成 NULL」：这一列会被报告链 / 卷轴详情 /
-- 看板四处读，改成可空要在每一处补 `None` 分支，而它们真正需要的判断
-- 不是「有没有值」而是「有没有可比的人」—— 人数本身就是那个判断依据。
-- 默认 0 也让**存量行**天然处于「不许显示」的诚实状态，直到跑完回算脚本。
--
-- ## 存量数据
--
-- 本文件只加列，不动数据。加完必须跑：
--
--     ./.venv/Scripts/python.exe scripts/backfill_percentile.py --dry-run
--     ./.venv/Scripts/python.exe scripts/backfill_percentile.py
--
-- 否则老记录会停在 `percentile_pool = 0`，界面上「百分位」那一条会整块消失
-- （诚实但不完整）。
--
-- ## 与 01_schema.sql 的关系
--
-- 01 的 CREATE TABLE 已包含这两列（新库一次到位），本文件只服务于**已经建过表的库**。
-- MySQL 不支持 `ADD COLUMN IF NOT EXISTS`，因此用 information_schema 判断 +
-- 预处理语句实现幂等，可重复执行。
-- ============================================================

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- 1. 加列（幂等）
-- ------------------------------------------------------------
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'attempts'
    AND COLUMN_NAME = 'percentile_pool'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `attempts`
     ADD COLUMN `percentile_pool` INT UNSIGNED NOT NULL DEFAULT 0
       COMMENT ''算这个百分位时池子里的可比人数（其他有成绩的冒险者数）；0 = 没有可比对象，界面显示「还没有其他冒险者」''
       AFTER `percentile`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. 改 percentile 的列注释（旧注释写着演示公式，留着会骗下一个人）
-- ------------------------------------------------------------
ALTER TABLE `attempts`
  MODIFY COLUMN `percentile` TINYINT UNSIGNED NOT NULL DEFAULT 0
    COMMENT '真实口径：本局正确率严格高于其他冒险者最佳正确率的人数占比（0-100）。percentile_pool=0 时此值无意义，界面不得展示';

-- ------------------------------------------------------------
-- 3. 自检（两列都应输出 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attempts'
       AND COLUMN_NAME = 'percentile_pool') AS has_pool,
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attempts'
       AND COLUMN_NAME = 'percentile') AS has_percentile;
