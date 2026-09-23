-- ============================================================
-- 知拾冒险社 · 用户系统数据库初始化 —— 第 2 步：建表（10 张）
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行（每个库各执行一次，SQL 本身不含 USE，用 -D 指定库）：
--   mysql -h 127.0.0.1 -P 3306 -u root -p -D knowsaga_club      --default-character-set=utf8mb4 -e "source <本文件绝对路径>"
--   mysql -h 127.0.0.1 -P 3306 -u root -p -D knowsaga_club_test --default-character-set=utf8mb4 -e "source <本文件绝对路径>"
-- 参考：docs/用户系统方案设计文档.md §5
--
-- 全局约定：
--   引擎 InnoDB；字符集 utf8mb4；排序规则 utf8mb4_0900_ai_ci（与服务端默认一致）
--   主键 BIGINT UNSIGNED AUTO_INCREMENT
--   表名/列名一律小写 snake_case（本机 lower_case_table_names=1，
--     强制小写可保证将来迁到 Linux（该值通常为 0）不会因大小写不一致而找不到表）
--   时间列 DATETIME(3)，**存 UTC**；「业务日期」按 Asia/Shanghai 派生
--   金额与得分一律整数；平均用时用精确小数 DECIMAL，不用浮点
--
-- 时间写入约定（重要）：
--   created_at / updated_at 的 DEFAULT CURRENT_TIMESTAMP(3) 只是兜底。
--   应用层一律显式写入 UTC 时间（datetime.now(timezone.utc)）；
--   同时建议建连接时执行 SET time_zone = '+00:00'，避免服务器本地时区
--   让 CURRENT_TIMESTAMP 产生非 UTC 值。
--
-- 幂等：全部使用 IF NOT EXISTS，重复执行安全。
-- ============================================================

SET NAMES utf8mb4;

-- ------------------------------------------------------------
-- 1. users —— 冒险者
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `openid`            VARCHAR(64)  NOT NULL COMMENT '微信唯一标识，登录凭据',
  `unionid`           VARCHAR(64)  DEFAULT NULL COMMENT '仅在绑定微信开放平台账号后返回',
  `nickname`          VARCHAR(32)  NOT NULL COMMENT '默认「冒险者 · XXXX」',
  `avatar_key`        VARCHAR(32)  NOT NULL DEFAULT 'scholar'
                      COMMENT '预置头像键：apprentice 学徒 / scholar 学者 / knight 骑士 / mage 法师 / ranger 游侠 / artisan 工匠',
  `avatar_url`        VARCHAR(255) DEFAULT NULL COMMENT '用户上传的头像 URL；读取时优先于 avatar_key',
  `xp_total`          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '累计经验值',
  `coins`             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '冒险金币',
  `streak_days`       INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前连续天数',
  `longest_streak`    INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '历史最长连续天数',
  `last_active_date`  DATE         DEFAULT NULL COMMENT '业务时区（Asia/Shanghai）日期，算连续天数用',
  `token_version`     INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '登录态版本号；递增即让该用户已签发的全部登录态立即失效（登出用）',
  `last_login_at`     DATETIME(3)  DEFAULT NULL,
  `created_at`        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_openid` (`openid`),
  KEY `idx_users_unionid` (`unionid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='冒险者（用户）';

-- 说明：本轮不存 session_key。
-- 官方要求 session_key 必须保密且不得下发前端；本轮没有任何需要它的场景
-- （不做手机号、不解密加密数据），不存即没有泄漏面。将来真要加，另起一条迁移。

-- ------------------------------------------------------------
-- 2. user_settings —— 用户设置（1:1）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_settings` (
  `user_id`             BIGINT UNSIGNED NOT NULL,
  `reminder_enabled`    TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '每日学习提醒开关',
  `reminder_time`       TIME        NOT NULL DEFAULT '20:00:00' COMMENT '提醒时间，对应原型 07·6 的时间 chips',
  `reminder_days`       JSON        NOT NULL DEFAULT (JSON_ARRAY(1,2,3,4,5)) COMMENT '提醒日，1=周一；对应原型星期 chips',
  `remind_streak_break` TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '连续记录即将中断时提醒',
  `remind_review_due`   TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '旧识重温到期时提醒',
  `remind_snooze_date`  DATE        DEFAULT NULL COMMENT '「今天先不复习」的日期；仅影响当日提示，不影响错题排期',
  `sound_enabled`       TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '音效与振动',
  `auto_load_images`    TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '流量下自动加载配图',
  `eye_care`            TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '护眼模式',
  `subscribe_quota`     INT UNSIGNED NOT NULL DEFAULT 0
                        COMMENT '订阅消息剩余可下发次数；本轮不写，仅预留，将来接真下发无需改表',
  `created_at`          DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`          DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`user_id`),
  CONSTRAINT `fk_user_settings_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户设置';

-- ------------------------------------------------------------
-- 3. quizzes —— 卷轴与它的生成参数
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `quizzes` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`        BIGINT UNSIGNED NOT NULL,
  `title`          VARCHAR(128) NOT NULL,
  `summary`        VARCHAR(512) NOT NULL DEFAULT '',
  `source_type`    VARCHAR(16)  NOT NULL DEFAULT 'text' COMMENT '输入类型：text（本轮仅此一种）',
  `source_name`    VARCHAR(128) NOT NULL DEFAULT '' COMMENT '输入来源展示名',
  `source_hash`    CHAR(64)     DEFAULT NULL COMMENT '输入资料指纹，用于「同资料不重复建卷轴」',
  `question_count` TINYINT UNSIGNED NOT NULL COMMENT '题量',
  `difficulty`     VARCHAR(16)  NOT NULL DEFAULT 'mixed',
  `status`         VARCHAR(16)  NOT NULL DEFAULT 'ready' COMMENT '生成成功即落库，无中间态',
  `created_at`     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_quizzes_user_created` (`user_id`, `created_at`),
  KEY `idx_quizzes_user_hash` (`user_id`, `source_hash`),
  CONSTRAINT `fk_quizzes_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='冒险卷轴';

-- ------------------------------------------------------------
-- 4. questions —— 题目快照
-- 为什么快照而不只存题目引用：题目由模型生成，没有稳定外部 ID；
-- 历史卷轴要能无限期回看题干、选项、答案与讲解，快照是唯一可靠做法。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `questions` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `quiz_id`         BIGINT UNSIGNED NOT NULL,
  `seq`             SMALLINT UNSIGNED NOT NULL COMMENT '题序，从 1 开始',
  `type`            VARCHAR(16)  NOT NULL COMMENT 'single 单选 / multiple 多选 / judge 判断',
  `stem`            TEXT         NOT NULL COMMENT '题干',
  `options`         JSON         NOT NULL COMMENT '[{"key":"A","text":"..."}]',
  `answer`          JSON         NOT NULL COMMENT '选项键数组，如 ["A","C"]',
  `explanation`     TEXT         NOT NULL COMMENT '知识讲解（答对答错都要给）',
  `knowledge_point` VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '知识点标签，知识树与报告的聚合依据',
  `difficulty`      VARCHAR(16)  NOT NULL DEFAULT 'easy',
  `origin_question_id` BIGINT UNSIGNED DEFAULT NULL
                    COMMENT '复习关卡的副本题指回原错题；NULL 表示这是原题（错题本按它归并）',
  `created_at`      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_questions_quiz_seq` (`quiz_id`, `seq`),
  KEY `idx_questions_quiz_kp` (`quiz_id`, `knowledge_point`),
  KEY `idx_questions_origin` (`origin_question_id`),
  CONSTRAINT `fk_questions_quiz` FOREIGN KEY (`quiz_id`)
    REFERENCES `quizzes` (`id`) ON DELETE CASCADE,
  -- 复习关卡组卷时会把错题**复制**进一份新卷轴（questions 的 UNIQUE(quiz_id, seq)
  -- 决定了题目不能跨卷轴共享）。副本必须能指回原题，否则复习答对只会推进副本，
  -- 原错题的阶段永远不动 —— 而那正是「旧识重温」要的东西。
  -- ON DELETE SET NULL：原题随卷轴被删时，副本退化成它自己，而不是留下悬空引用
  -- （悬空引用会让错题本写入撞外键，用户看到的是「交卷失败」）。
  CONSTRAINT `fk_questions_origin` FOREIGN KEY (`origin_question_id`)
    REFERENCES `questions` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='题目快照';

-- ------------------------------------------------------------
-- 5. attempts —— 一次挑战
-- 口径：原型 04·5「历史卷轴」的一条列表项 = 一次 attempt，不是一份卷轴；
--       同一卷轴重做会产生多条记录。
-- 多选的部分正确不计入 correct_count，与原型「4 / 5」口径一致。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `attempts` (
  `id`                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`                 BIGINT UNSIGNED NOT NULL,
  `quiz_id`                 BIGINT UNSIGNED NOT NULL,
  `attempt_no`              SMALLINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '该卷轴的第几次尝试，首次=1',
  `client_token`            VARCHAR(36) DEFAULT NULL
                            COMMENT '客户端一次性交卷令牌，用于网络重试去重（唯一；NULL 不参与唯一性判断）',
  `started_at`              DATETIME(3) NOT NULL,
  `finished_at`             DATETIME(3) NOT NULL,
  `duration_ms`             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '总用时',
  `correct_count`           SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `wrong_count`             SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `partial_count`           SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '多选题部分正确',
  `total_count`             SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `accuracy`                TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0-100 整数',
  `max_xp`                  SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `xp_gained`               SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `coins_gained`            SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `percentile`              TINYINT UNSIGNED NOT NULL DEFAULT 0
                            COMMENT '真实口径：本局正确率严格高于其他冒险者最佳正确率的人数占比（0-100）。percentile_pool=0 时此值无意义，界面不得展示',
  `percentile_pool`         INT UNSIGNED NOT NULL DEFAULT 0
                            COMMENT '算这个百分位时池子里的可比人数（其他有成绩的冒险者数）；0 = 没有可比对象，界面显示「还没有其他冒险者」',
  `avg_seconds_per_question` DECIMAL(6,2) NOT NULL DEFAULT 0.00 COMMENT '数据看板「平均单局用时」',
  `status`                  VARCHAR(16) NOT NULL DEFAULT 'finished',
  `deleted_at`              DATETIME(3) DEFAULT NULL
                            COMMENT '历史卷轴里被删除的时刻；NULL = 未删除。只影响列表与详情，不影响任何聚合统计',
  `created_at`              DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`              DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_attempts_client_token` (`client_token`),
  KEY `idx_attempts_user_finished` (`user_id`, `finished_at`),
  KEY `idx_attempts_quiz` (`quiz_id`),
  CONSTRAINT `fk_attempts_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_attempts_quiz` FOREIGN KEY (`quiz_id`)
    REFERENCES `quizzes` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='一次挑战（一局）';

-- ------------------------------------------------------------
-- 6. answers —— 逐题作答
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `answers` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `attempt_id`    BIGINT UNSIGNED NOT NULL,
  `question_id`   BIGINT UNSIGNED NOT NULL,
  `selected`      JSON         NOT NULL COMMENT '用户选中的选项键数组',
  `outcome`       VARCHAR(16)  NOT NULL COMMENT 'correct / partial / wrong',
  `earned_xp`     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `max_xp`        SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `time_spent_ms` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '单题用时',
  `answered_at`   DATETIME(3)  NOT NULL,
  `created_at`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_answers_attempt_question` (`attempt_id`, `question_id`),
  CONSTRAINT `fk_answers_attempt` FOREIGN KEY (`attempt_id`)
    REFERENCES `attempts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_answers_question` FOREIGN KEY (`question_id`)
    REFERENCES `questions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='逐题作答明细';

-- ------------------------------------------------------------
-- 7. reports —— 冒险日志（1:1 于 attempt）
-- 为什么独立成表：报告异步生成且可独立失败。
-- 原型 03·6 要求「报告生成失败时答题记录不丢失」，
-- 挂在 attempts 上会让两者的生命周期纠缠。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `reports` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `attempt_id`    BIGINT UNSIGNED NOT NULL,
  `user_id`       BIGINT UNSIGNED NOT NULL,
  `status`        VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending / ready / failed',
  `summary_lines` JSON        DEFAULT NULL COMMENT '三句话总结，恰好 3 条',
  `strong_points` JSON        DEFAULT NULL COMMENT '掌握较好的知识点标签',
  `weak_points`   JSON        DEFAULT NULL COMMENT '薄弱知识点标签',
  `suggestions`   JSON        DEFAULT NULL COMMENT '三条建议，每条 {title, body, action}',
  `model`         VARCHAR(64) NOT NULL DEFAULT '' COMMENT '生成所用模型，便于追溯',
  `error_code`    INT         DEFAULT NULL,
  `error_message` VARCHAR(255) DEFAULT NULL,
  `generated_at`  DATETIME(3) DEFAULT NULL,
  `created_at`    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_reports_attempt` (`attempt_id`),
  KEY `idx_reports_user_status` (`user_id`, `status`),
  CONSTRAINT `fk_reports_attempt` FOREIGN KEY (`attempt_id`)
    REFERENCES `attempts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_reports_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='冒险日志（复盘报告）';

-- ------------------------------------------------------------
-- 8. wrong_questions —— 错题本（旧识重温）
-- 复习间隔（原型所说「艾宾浩斯遗忘曲线」）：stage 0-5 → 1/2/4/7/15/30 天
-- 答错 → wrong_count+1，stage 回到 0，下次到期 = 现在+1 天
-- 复习答对 → stage+1，下次到期 = 现在 + 间隔[stage]
-- 连续两次复习答对 → mastered=1，移出队列
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `wrong_questions` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`         BIGINT UNSIGNED NOT NULL,
  `question_id`     BIGINT UNSIGNED NOT NULL,
  `wrong_count`     SMALLINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '累计答错次数',
  `stage`           TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '复习阶段 0-5',
  `next_review_at`  DATETIME(3)  NOT NULL COMMENT '下次到期时刻',
  `last_review_at`  DATETIME(3)  DEFAULT NULL,
  `last_wrong_at`   DATETIME(3)  NOT NULL,
  `mastered`        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '连续两次复习答对置 1',
  `created_at`      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_wrong_questions_user_question` (`user_id`, `question_id`),
  KEY `idx_wrong_questions_user_due` (`user_id`, `mastered`, `next_review_at`),
  CONSTRAINT `fk_wrong_questions_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wrong_questions_question` FOREIGN KEY (`question_id`)
    REFERENCES `questions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='错题本';

-- ------------------------------------------------------------
-- 9. user_knowledge_stats —— 知识树聚合（物化）
-- 为什么物化而不实时聚合：知识树与数据看板的「各知识领域掌握度」都要读它；
-- 实时聚合需跨 answers → questions 按 knowledge_point 分组，随数据增长会变成最慢的查询。
-- 写入时机只有一处（结算），成本可忽略。
-- 三态判定必须先判空：total_count = 0 → 「未开始」，不得落进「进行中」。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_knowledge_stats` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`       BIGINT UNSIGNED NOT NULL,
  `kp_name`       VARCHAR(64) NOT NULL COMMENT '知识点名称',
  `total_count`   INT UNSIGNED NOT NULL DEFAULT 0,
  `correct_count` INT UNSIGNED NOT NULL DEFAULT 0,
  `mastery`       TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'round(correct/total*100)',
  `lit`           TINYINT(1)  NOT NULL DEFAULT 0 COMMENT 'mastery >= 90 置 1（点亮阈值）',
  `first_seen_at` DATETIME(3) NOT NULL,
  `last_seen_at`  DATETIME(3) NOT NULL,
  `created_at`    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_knowledge_stats_user_kp` (`user_id`, `kp_name`),
  KEY `idx_user_knowledge_stats_user_lit` (`user_id`, `lit`),
  CONSTRAINT `fk_user_knowledge_stats_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识树聚合统计';

-- ------------------------------------------------------------
-- 10. user_badges —— 勋章解锁记录
-- 勋章定义不建表：18 枚的规则放 badge_service.py 的常量注册表。
-- 解锁条件需要代码表达（如「单局满分且平均每题 < 5 秒」），
-- 塞进表里只能存字符串再解释，等于自造一套 DSL。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_badges` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`           BIGINT UNSIGNED NOT NULL,
  `badge_key`         VARCHAR(48) NOT NULL COMMENT '勋章键，对应代码内注册表',
  `unlocked_at`       DATETIME(3) NOT NULL,
  `progress_snapshot` JSON        DEFAULT NULL COMMENT '解锁时的进度快照，便于回溯',
  `created_at`        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_badges_user_key` (`user_id`, `badge_key`),
  CONSTRAINT `fk_user_badges_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='勋章解锁记录';
