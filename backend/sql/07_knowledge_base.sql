-- ============================================================
-- 知拾冒险社 · 增量变更 07：私有知识库（knowledge_bases / knowledge_documents）
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：cd backend
--       ./.venv/Scripts/python.exe scripts/apply_sql.py sql/07_knowledge_base.sql
--       （默认对**两个库**都执行：业务库 + 测试库；漏掉测试库的症状是
--         「业务库好了、pytest 全红」，报错是 Table doesn't exist，看不出跟迁移有关）
-- 参考：openspec/changes/add-private-knowledge-base/design.md D2 / D3 / D10
--
-- ## 为什么是两张表而不是一张
--
-- 「一个库」与「库里的一份文档」的生命周期不同：
--
--   * 库是用户建的容器，可以被改名、被整体删除，且是「从哪儿出题」的选择单位；
--   * 文档有自己的**解析状态机**（pending → parsing → ready/failed），
--     这是库这一层没有的东西。
--
-- 合成一张表就得让每一行都带一遍库名与库描述，改一次库名要更新 N 行；
-- 而且「库存在但一份文档都没有」这个合法状态会表达不出来。
--
-- ## 为什么解析状态必须落库（而不是复用进程内的任务表）
--
-- 本项目的 `app/services/task_service.py` 是**进程内内存 + TTL 600 秒**，
-- 它的文档里写着「MVP 不做后端持久化」—— 那对「出题任务」是成立的
-- （用户在「副本召唤中」等十秒，拿到题库后任务就没用了）。
-- 但文档解析不成立：
--
--   * 进程重启 ⇒ 任务没了，而文档还在，「它到底解析完了没有」无从回答；
--   * TTL 到期 ⇒ 用户第二天回来看，文档永远停在「解析中」。
--
-- 所以状态存在这张表的 `status` 上，**它是唯一真相**；后台线程只负责把状态往前推。
--
-- ## 为什么 `user_id` 在文档表里冗余存一份
--
-- 严格来说有了 `kb_id` 就能 JOIN 出属主。冗余的理由只有一个：**越权判断要走的查询
-- 越短越好**。检索时按用户隔离 collection，写向量前要确认「这份文档确实是这个人的」，
-- 那次查询不该为了拿 user_id 而 JOIN 另一张表 —— 少一次 JOIN 就少一个写错过滤条件的位置。
-- 代价是插入时多写一列，且两处必须一致（由 `kb_repository` 唯一入口保证）。
--
-- ## 为什么不存冗余计数（doc_count / chunk_count 那种列）
--
-- 「3 份文档 · 120 个知识块」这类数字用一条聚合查询算得出来。存冗余计数看着省事，
-- 但它有两个写入点（加文档、删文档），而这两个写入点里任何一个被绕过
-- （比如解析失败要回滚计数），数字就永久错了 —— 而数字错了没有任何报错。
-- 单份文档的 `chunk_count` 是**文档自己的属性**（解析完成时一次写入，之后不变），
-- 所以它冗余得安全，可以存。

-- ------------------------------------------------------------
-- 1. knowledge_bases —— 私有知识库
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `knowledge_bases` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     BIGINT UNSIGNED NOT NULL COMMENT '属主。所有读写都必须按它过滤；越权与不存在返回同一个 4005',
  `name`        VARCHAR(64)  NOT NULL COMMENT '知识库名，2–40 字。同一用户下唯一，否则用户在列表里分不清该选哪个',
  `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '用途描述（可选）。它同时参与出题语义，写得清楚有助于出题质量',
  `created_at`  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  -- 「列我的库」与「这个库是不是我的」都走它；带上 id 让排序也不必回表
  KEY `idx_kb_user_id` (`user_id`, `id`),
  -- 同用户库名唯一。删库是物理删除，所以「删掉再建同名」不会被这条挡住
  UNIQUE KEY `uk_kb_user_name` (`user_id`, `name`),
  -- 与全项目一致的 FK + 级联：销号时数据跟着走，不留孤儿行
  CONSTRAINT `fk_knowledge_bases_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='私有知识库（用户上传资料的容器）';

-- ------------------------------------------------------------
-- 2. knowledge_documents —— 库里的文档（含解析状态）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `knowledge_documents` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`         BIGINT UNSIGNED NOT NULL COMMENT '所属知识库',
  `user_id`       BIGINT UNSIGNED NOT NULL COMMENT '属主（冗余，见文件头说明）',
  `filename`      VARCHAR(255) NOT NULL COMMENT '客户端提供的原始文件名。用于展示，也是扩展名准入的判据',
  `ext`           VARCHAR(16)  NOT NULL COMMENT '小写扩展名（pdf / docx / md / txt）。单独一列，避免每次从 filename 现切',
  `size_bytes`    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '原始文件字节数',
  `status`        VARCHAR(16)  NOT NULL DEFAULT 'pending'
                  COMMENT '解析状态：pending 等待 / parsing 解析中 / ready 已就绪 / failed 失败。只有 ready 参与检索',
  `chunk_count`   INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '入库的片段数。仅 ready 时非零；解析产出为空会被判 failed 而不是 ready+0',
  `page_count`    INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '页数（PDF / Word 拿得到时）。取不到为 0，不假装知道',
  `error_code`    VARCHAR(32)  NOT NULL DEFAULT '' COMMENT '失败分类（如 unsupported_content / embedding_failed / upstream_timeout），供排查聚合',
  `error_message` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '可直接展示给用户的一句话。与 error_code 分开：一个给人看，一个给聚合看',
  `created_at`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `parsed_at`     DATETIME(3)  DEFAULT NULL COMMENT '解析结束（成功或失败）的时刻；解析中为 NULL',
  PRIMARY KEY (`id`),
  -- 详情页「列出本库文档」、按库检索前取就绪文档，都走它
  KEY `idx_kdoc_kb_id` (`kb_id`, `id`),
  -- 删库时要按用户兜底清理
  KEY `idx_kdoc_user` (`user_id`),
  -- 「有没有卡在解析中的文档」这类排查用
  KEY `idx_kdoc_status` (`status`),
  -- ⚠️ 级联只清**数据库行**，Chroma 里的向量与磁盘上的原文件仍要显式清理
  -- （见 design D10 与 kb_service.delete_document）—— FK 管不到它们，
  -- 残留向量的症状是「删掉的文档还会被检索命中」。
  CONSTRAINT `fk_knowledge_documents_kb` FOREIGN KEY (`kb_id`)
    REFERENCES `knowledge_bases` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_knowledge_documents_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库文档及其解析状态';

-- ------------------------------------------------------------
-- 3. 自检（两张表都应为 1）
-- ------------------------------------------------------------
SELECT
  (SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'knowledge_bases')     AS has_knowledge_bases,
  (SELECT COUNT(*) FROM information_schema.TABLES
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'knowledge_documents') AS has_knowledge_documents;
