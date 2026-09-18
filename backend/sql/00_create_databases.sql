-- ============================================================
-- 知拾冒险社 · 用户系统数据库初始化 —— 第 1 步：建库
-- ============================================================
-- 适用：MySQL 8.0.13+（本机实测为 9.0.1）
-- 执行：mysql -h 127.0.0.1 -P 3306 -u root -p --default-character-set=utf8mb4 -e "source <本文件绝对路径>"
-- 参考：docs/用户系统方案设计文档.md §9.1
--
-- 为什么是两个库：
--   knowsaga_club      业务库，真实数据
--   knowsaga_club_test 测试库，pytest 会反复建表/清表，必须与业务库隔离
--
-- 字符集与排序规则的选择依据（实测本机服务端默认值）：
--   服务端为 utf8mb4 / utf8mb4_0900_ai_ci。
--   库、表、连接三者的排序规则必须一致，否则跨表 JOIN 会报
--   "Illegal mix of collations"。故此处显式锁定为服务端默认值，
--   不采用旧的 utf8mb4_unicode_ci。
--
-- 幂等：全部使用 IF NOT EXISTS，重复执行安全。
-- ============================================================

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS `knowsaga_club`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS `knowsaga_club_test`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

-- ------------------------------------------------------------
-- 可选加固：为应用单独建一个只有这两个库权限的账号。
-- 本机单人开发可以继续用 root；上线前必须换成专用账号。
-- 使用前请把 <PASSWORD> 替换为强密码，并同步修改 .env 的 DATABASE_URL。
-- ------------------------------------------------------------
-- CREATE USER IF NOT EXISTS 'knowsaga'@'localhost' IDENTIFIED BY '<PASSWORD>';
-- GRANT ALL PRIVILEGES ON `knowsaga_club`.*      TO 'knowsaga'@'localhost';
-- GRANT ALL PRIVILEGES ON `knowsaga_club_test`.* TO 'knowsaga'@'localhost';
-- FLUSH PRIVILEGES;
