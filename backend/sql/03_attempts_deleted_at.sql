-- ============================================================
-- 知拾冒险社 · 增量变更 03：attempts.deleted_at
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：mysql -h 127.0.0.1 -P 3306 -u root -p --default-character-set=utf8mb4 \
--            -D <库名> < <本文件绝对路径>
--      两个库各执行一次：knowsaga_club / knowsaga_club_test
-- 参考：docs/用户系统需求分析文档.md FR-B5、docs/用户系统方案设计文档.md §6.2
--
-- ## 为什么需要它
--
-- 04·5 历史卷轴支持「长按删除」，而需求把结果写得很死（FR-B5）：
--
--   > 删除**仅移除记录，不影响整体统计**；累计 XP、正确率、等级不变。
--
-- 「记录消失」与「统计不变」这两条**同时**成立，就只有软删除一条路：
--
--   * 累计 XP / 等级存在 `users` 上，是结算时物化的，删不删都不动 —— 这条硬删也能满足。
--   * 但**正确率**（看板 `archive_service._aggregate`）与**答题量**是拿 `attempts`
--     / `answers` 实时聚合出来的。硬删一行 `attempts` 会连带 `ON DELETE CASCADE`
--     删掉它的 `answers` 与 `reports`，正确率和柱状图当天就变了 —— 用户看到的是
--     「删掉一条旧记录，我的正确率被改写了」，这比不给删更糟。
--
-- 所以删除写 `deleted_at`，只有**列表与详情**过滤它；所有聚合查询照旧不认这一列。
-- 换言之：这一列的语义是「从我的记录里挪开」，**不是**「这次挑战没发生过」。
--
-- ## 为什么是 NULL 而不是布尔
--
-- 留一个时间戳，将来要做「回收站 / 撤销删除」不必再加列；判定为 NULL 即可，
-- 与 `wrong_questions.mastered` 那种「状态位」不是一回事。
--
-- ## 与 01_schema.sql 的关系
--
-- 01 的 CREATE TABLE 已包含这一列（新库一次到位）。本文件只服务于**已经建过表的库**。
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
    AND COLUMN_NAME = 'deleted_at'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `attempts`
     ADD COLUMN `deleted_at` DATETIME(3) DEFAULT NULL
       COMMENT ''历史卷轴里被删除的时刻；NULL = 未删除。只影响列表与详情，不影响任何聚合统计''
       AFTER `status`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. 自检（应输出 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attempts'
       AND COLUMN_NAME = 'deleted_at') AS has_column;
