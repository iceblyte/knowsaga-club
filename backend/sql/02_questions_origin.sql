-- ============================================================
-- 知拾冒险社 · 增量变更 02：questions.origin_question_id
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：mysql -h 127.0.0.1 -P 3306 -u root -p --default-character-set=utf8mb4 \
--            -D <库名> < <本文件绝对路径>
--      两个库各执行一次：knowsaga_club / knowsaga_club_test
-- 参考：docs/用户系统方案设计文档.md §11 Phase D
--
-- ## 为什么需要它
--
-- 「旧识重温」要把到期的错题组一局复习关卡重做。而 `questions` 有
-- UNIQUE(quiz_id, seq) —— 题目**不能跨卷轴共享**，所以复习关卡必须把错题
-- **复制**进一份新卷轴，副本拿到的是全新的 `questions.id`。
--
-- 于是产生一个问题：复习时答对了，要推进的是**原错题**的阶段
-- （`wrong_questions.stage` → 连续两次答对即移出队列），而不是副本的。
-- 副本必须能指回原题，这就是本列存在的唯一理由。
--
-- 没有它的话，「复习答对 → 阶段推进 → 移出队列」这条规则在复习关卡里永远
-- 不会触发：错题本会一直把同一道题推给你，而每一轮复习都不算数。
--
-- ## 为什么带一个自引用外键（而不是只加一列）
--
-- 错题本写入时用的是 `COALESCE(origin_question_id, id)` 作为 `questions` 的外键值。
-- 如果 origin 指向一个不存在的行，那次交卷会撞外键失败 —— 用户看到的是
-- 「交卷失败」，而答题记录本来该是最不该丢的东西。
-- 外键把这个错误挡在写入之前，`ON DELETE SET NULL` 则保证原题消失时副本
-- 优雅退化成它自己，不留悬空引用。
--
-- ## 与 01_schema.sql 的关系
--
-- 01 的 CREATE TABLE 已包含这一列（新库一次到位）。本文件只服务于
-- **已经建过表的库**。MySQL 不支持 `ADD COLUMN IF NOT EXISTS`，
-- 因此用 information_schema 判断 + 预处理语句实现幂等，可重复执行。
-- ============================================================

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- 1. 加列（幂等）
-- ------------------------------------------------------------
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'questions'
    AND COLUMN_NAME = 'origin_question_id'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `questions`
     ADD COLUMN `origin_question_id` BIGINT UNSIGNED DEFAULT NULL
       COMMENT ''复习关卡的副本题指回原错题；NULL 表示这是原题（错题本按它归并）''
       AFTER `difficulty`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. 加索引（幂等）
-- 外键在 InnoDB 里要求被引用列有索引，MySQL 也会自动建一个；
-- 这里显式声明，名字才可预期（自动生成的名字各版本不一致）。
-- ------------------------------------------------------------
SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'questions'
    AND INDEX_NAME = 'idx_questions_origin'
);
SET @ddl := IF(
  @idx_exists = 0,
  'ALTER TABLE `questions` ADD KEY `idx_questions_origin` (`origin_question_id`)',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 3. 加外键（幂等）
-- ------------------------------------------------------------
SET @fk_exists := (
  SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'questions'
    AND CONSTRAINT_NAME = 'fk_questions_origin'
);
SET @ddl := IF(
  @fk_exists = 0,
  'ALTER TABLE `questions`
     ADD CONSTRAINT `fk_questions_origin` FOREIGN KEY (`origin_question_id`)
       REFERENCES `questions` (`id`) ON DELETE SET NULL',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 4. 自检（应输出 1 / 1 / 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'questions'
       AND COLUMN_NAME = 'origin_question_id') AS has_column,
  (SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'questions'
       AND INDEX_NAME = 'idx_questions_origin')            AS has_index,
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
     WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'questions'
       AND CONSTRAINT_NAME = 'fk_questions_origin')        AS has_fk;
