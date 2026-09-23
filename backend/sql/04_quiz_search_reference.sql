-- ============================================================
-- 知拾冒险社 · 增量变更 04：quizzes.search_state / quizzes.references
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：cd backend
--       ./.venv/Scripts/python.exe scripts/apply_sql.py sql/04_quiz_search_reference.sql
--       （默认对**两个库**都执行：业务库 + 测试库；漏掉测试库的症状是
--         「业务库好了、pytest 全红」，报错是 Unknown column，看不出跟迁移有关）
-- 参考：docs/MVP开发计划.md §7.3、openspec/changes/add-web-search-grounding/design.md D9
--
-- ## 为什么需要它
--
-- 接入联网检索之后，「这份卷轴的题目是依据什么出的」变成一个**必须能回答的问题**：
--
--   * 报告链要复用同一批资料；将来做「参考来源展示」要有东西可展示；
--   * 排查「这道题为什么错」时，第一件要确认的事就是「当时到底有没有依据」。
--
-- 资料本身不落库也能出题，但**事后无法区分三种情况**，而这三种的责任完全不同：
--
--   `off`      用户关掉了联网（或后端没开）——正常，不是问题；
--   `degraded` 去取了但一条都没取到（主题太新 / 网页抓不动 / 额度用尽）——要能发现；
--   `hit`      取到了 N 条资料。
--
-- ## 为什么是两列而不是一列
--
-- 把状态和内容塞进一个 JSON 列（例如 `{"state":"degraded"}`）看着更省事，
-- 但「没去取」与「取了没取到」就会退化成「JSON 里有没有某个键」——
-- 前者是配置问题（去看 KNOWLEDGE_SEARCH_ENABLED），后者是主题问题（换个说法或补资料），
-- 排查路径完全不同。分列的代价是 16 字节，收益是这两种情况永远分得开。
--
-- ## 为什么 `references` 用反引号包起来
--
-- `REFERENCES` 是 MySQL 的**保留字**（外键约束语法的一部分）。作为列名必须始终加反引号，
-- 否则任何一句手写的 `SELECT references FROM quizzes` 都会语法报错。
-- SQLAlchemy 会自动加引号，但这里手写 DDL 与将来可能的排查语句都要注意。
--
-- ## 只存「能说明问题的部分」，不存整页正文
--
-- `references` 里每条只留 `title` / `url` / `snippet`（已按上限截断）/ `kind` / `source`。
-- 实测单个网页正文可达 74,801 字符（见 design D14），整篇存进去会让这张表迅速膨胀，
-- 而它**不是**资料的权威副本 —— 资料的权威副本在原始网页上。
--
-- 存量行不受影响：`search_state` 默认 `off`，正好是「这次没有用外部资料」的准确描述。

-- ------------------------------------------------------------
-- 1. 加列（幂等：先查 information_schema，已存在则执行 DO 0）
-- ------------------------------------------------------------
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'quizzes'
    AND COLUMN_NAME = 'search_state'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `quizzes`
     ADD COLUMN `search_state` VARCHAR(16) NOT NULL DEFAULT ''off''
       COMMENT ''本次出题的外部取材状态：off=没去取 / degraded=取了没取到 / hit=取到了。与 references 必须分列，否则两种情况分不开''
       AFTER `difficulty`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'quizzes'
    AND COLUMN_NAME = 'references'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `quizzes`
     ADD COLUMN `references` JSON DEFAULT NULL
       COMMENT ''取材到的资料快照（title/url/snippet/kind/source）。只留能说明问题的部分，不是资料的权威副本；整页正文按上限截断后才进这里''
       AFTER `search_state`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. 自检（两列都应为 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'quizzes'
       AND COLUMN_NAME = 'search_state') AS has_search_state,
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'quizzes'
       AND COLUMN_NAME = 'references') AS has_references;
