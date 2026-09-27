-- ============================================================
-- 知拾冒险社 · 增量变更 09：界面主题（user_settings.ui_theme）
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：cd backend
--       ./.venv/Scripts/python.exe scripts/apply_sql.py sql/09_user_settings_ui_theme.sql
--       （默认对**两个库**都执行：业务库 + 测试库；漏掉测试库的症状是
--         「业务库好了、pytest 全红」，报错是 Unknown column，
--         看不出跟迁移有关）
-- 参考：openspec/changes/add-ui-theme-switch/design.md（D5 / D7）
--
-- ## 为什么是 VARCHAR 而不是 ENUM
--
-- 主题集合是**产品决策**，会随版本增删。用 ENUM 的话，加一套主题就要再写一条
-- `ALTER TABLE ... MODIFY COLUMN` 的迁移 —— 一次纯前端的配色新增被拖成一次
-- DDL 变更，而且 ENUM 的取值顺序会被写进表定义，删主题时旧值残留还得清。
--
-- 取值闭集由**应用层**的白名单守（`app/core/constants.py` 的 `UI_THEME_IDS`，
-- 由 `UserSettingsUpdateRequest.field_validator` 执行）。这样做还有一个好处：
-- 一份白名单同时被「PATCH 校验」和「与 shared/ui-themes.json 的一致性测试」
-- 读取，跨语言对齐是**可测的**；而 ENUM 的取值只能靠读表定义去比对。
--
-- 长度 16：目前最长的标识是 `vermilion`（9 字符），留了近一倍余量。
-- 它是英文小写标识，不是给用户看的名字（名字是中文的「素白墨朱」，在
-- 前端 `frontend/src/constants/ui-theme.ts` 里）。
--
-- ## 为什么 NOT NULL DEFAULT 'paper'
--
-- 三条理由叠在一起：
--   1. 默认主题就是纸与印（design D5），存量行「从未选过主题」的语义
--      正好等于默认值 —— 与 `image_url` 那种「NULL = 没有」不同，
--      这里不存在需要区分「不知道」与「没选」的场景。
--   2. NOT NULL 让读侧不必处理 None，`_to_settings_public` 少一个分支。
--   3. 用 DDL 默认值兜住**绕过接口**写的行（手工 INSERT / 别的服务），
--      拿到的也是合法值，不会让设置页拿到 NULL 而 500。
--
-- ## 存量行不受影响
--
-- `ADD COLUMN ... DEFAULT 'paper'` 会把既有行填成 'paper'，正是期望的结果：
-- 「升级后主题仍是纸与印，界面零变化」。老用户不需要做任何操作。

-- ------------------------------------------------------------
-- 1. user_settings 加列（幂等：先查 information_schema，已存在则执行 DO 0）
-- ------------------------------------------------------------
-- 位置 AFTER `subscribe_quota` 而不是 AFTER `eye_care`：`subscribe_quota`
-- 是预留的内部列、且排在最后，把用户可见的偏好挂在它后面，能让
-- 「界面偏好」和「内部机制」在表定义里天然分开。
-- ⚠️ 这个位置必须与 `app/db/tables.py` 的字段顺序一致 ——
--    `tests/test_db_mapping.py::test_column_order_matches_database` 会逐列比对。
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'user_settings'
    AND COLUMN_NAME = 'ui_theme'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `user_settings`
     ADD COLUMN `ui_theme` VARCHAR(16) NOT NULL DEFAULT ''paper''
       COMMENT ''界面主题标识；取值闭集见 app/core/constants.py 的 UI_THEME_IDS。默认 paper = 纸与印（存量行即默认主题，升级后界面零变化）''
       AFTER `subscribe_quota`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. 自检（has_ui_theme = 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'user_settings'
       AND COLUMN_NAME = 'ui_theme') AS has_ui_theme;
