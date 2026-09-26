-- ============================================================
-- 知拾冒险社 · 增量变更 08：题目配图（questions.image_url + image_quota_usage）
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：cd backend
--       ./.venv/Scripts/python.exe scripts/apply_sql.py sql/08_question_image.sql
--       （默认对**两个库**都执行：业务库 + 测试库；漏掉测试库的症状是
--         「业务库好了、pytest 全红」，报错是 Unknown column / Unknown table，
--         看不出跟迁移有关）
-- 参考：openspec/changes/add-question-image-generation/design.md D5 / D6 / D9
--
-- ## 为什么只存 URL，不存图片本身
--
-- 图片是二进制且体积大（512×512 的 JPEG 也是几十 KB 量级），把它塞进 `questions`
-- 会让这张「每道题一行」的热表迅速膨胀，而 MySQL 本来就不适合当对象存储。
-- 图片落在腾讯云 COS 上，这里只留一个地址。
--
-- ⚠️ 存的是**我们自己转存后**的地址，不是上游返回的那个：上游的图片链接
--    只有 24 小时有效期，而题目是永久保存的 —— 直接存上游链接的表现是
--    「昨天做的题，今天回看全是裂图」。
--
-- ## 为什么额度要单独一张表，而不是复用 core/ratelimit.py
--
-- `app/core/ratelimit.py` 是**进程内滑动窗口**，做「每人每天 N 张」会有两个
-- 不能接受的后果：进程重启即清零、多实例部署各算各的（用户换个实例就又有额度）。
-- 所以额度必须落库，并且靠 `(user_id, biz_date)` 的主键 + 原子自增保证不超发。
--
-- `used_count` 只计**真正生成成功**的张数：预扣、完成后按实际成功数结算，
-- 任务整体失败时全额退回（见 `app/services/image_quota_service.py`）。
--
-- ## biz_date 是业务日，不是 UTC 日
--
-- 「今天」按 `APP_TIMEZONE`（默认 Asia/Shanghai）判定，与「连续天数」「错题到期」
-- 同一口径。若按 UTC 存，中国用户的额度会在早上 8 点重置 —— 那不是任何人心里的
-- 「明天」。
--
-- ## 存量行不受影响
--
-- `image_url` 可空，且既有行写入时是 NULL，正好表达「这道题没有配图」。
-- 没有默认值意味着「不知道」和「没有」在这里是同一件事 —— 这在本列上是正确的，
-- 因为配图从来没有过，不存在需要区分的两种「没有」。

-- ------------------------------------------------------------
-- 1. questions 加列（幂等：先查 information_schema，已存在则执行 DO 0）
-- ------------------------------------------------------------
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'questions'
    AND COLUMN_NAME = 'image_url'
);
SET @ddl := IF(
  @col_exists = 0,
  'ALTER TABLE `questions`
     ADD COLUMN `image_url` VARCHAR(512) DEFAULT NULL
       COMMENT ''题目配图的**永久**地址（已转存到自己的对象存储；上游链接只有 24 小时）。NULL = 这道题没有配图''
       AFTER `difficulty`',
  'DO 0'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 2. image_quota_usage 建表
-- ------------------------------------------------------------
-- 用 CREATE TABLE IF NOT EXISTS 天然幂等，不需要预处理语句。
-- 联合主键 (user_id, biz_date) 既是唯一约束也是查询索引：
-- 「查某人今天的用量」正好是主键前缀，不用再建第二个索引。
CREATE TABLE IF NOT EXISTS `image_quota_usage` (
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `biz_date`   DATE         NOT NULL COMMENT '业务时区（APP_TIMEZONE）下的自然日；额度按它重置',
  `used_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当天已消耗张数；只计真正生成并转存成功的',
  `created_at` DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`user_id`, `biz_date`),
  -- 用户被删时额度行一并消失：它是纯计数行，没有任何留档价值，
  -- 留着反而会让「当天额度」在用户重建后莫名其妙地继承下来。
  CONSTRAINT `fk_image_quota_usage_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='每人每天的生图额度消耗（按业务日重置）';

-- ------------------------------------------------------------
-- 3. 自检（has_image_url = 1，has_quota_table = 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'questions'
       AND COLUMN_NAME = 'image_url') AS has_image_url,
  (SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'image_quota_usage') AS has_quota_table;
