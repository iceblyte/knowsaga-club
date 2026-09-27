# Proposal

## Why

界面配色目前只有一套「纸与印」，用户没有选择。而颜色全部由 `styles/tokens.scss` 的 SCSS 变量在**编译期**固化，运行时换不了 —— 要支持换肤，必须先引入一套运行时可覆盖的颜色机制，否则改的只是色号、不是能力。

## What Changes

- **5 套主题**：`paper` 纸与印（默认，逐字不动）+ 新增 `indigo` 宣纸靛墨 / `vermilion` 素白墨朱 / `midnight` 夜航公会（暗色）/ `lime` 青柠。
- **设置入口**：设置页新增「界面主题」一行，下钻到子页 `pages/settings/theme`（与「学习提醒 / 头像与昵称」同构）；选中即全局生效。
- **持久化**：`user_settings` 增 `ui_theme` 列（默认 `paper`）；`GET|PATCH /users/me/settings` 增该字段（**白名单**校验，理由同 `avatar_key` —— 该值决定前端加载哪套皮肤）。启动时本地镜像先行、服务端为准对账，避免首屏闪回默认主题。
- **样式基座**：颜色类 token 的值由字面量改为 `var(--k-xxx, <原字面量>)`；主题类名挂 `PhoneShell` 与 `custom-tab-bar` 根节点（微信 WXSS 不支持属性选择器，只能走 class）。**默认主题不挂任何类** ⇒ 兜底即原值 ⇒ **零视觉漂移是构造保证**，不是「小心保证」。
- **色值真源**：新增 `shared/ui-themes.json`，构建期生成 `styles/_themes.scss`，并用校核脚本防手改漂移（沿用 `check:scoring` / `check:links` 的既有做法）。

## Capabilities

### New Capabilities

- `ui-theme`：界面主题的取值集合、持久化、切换生效范围与降级规则。

### Modified Capabilities

（无。既有 5 份规格基线的需求均不改变 —— 本变更只增加「颜色的来源」这一层，不改任何取材 / 出题 / 评分 / 复盘行为。）

## Impact

- **数据表**：`user_settings` 增一列 `ui_theme VARCHAR(16) NOT NULL DEFAULT 'paper'`。
- **接口**：`GET|PATCH /users/me/settings` 增 `ui_theme` 字段（白名单 + 默认值）。
- **页面**：设置页新增一行；新增主题选择子页；其余 30 个页面**结构不动**，只经由 `PhoneShell` 继承主题类。
- **前端基础设施**：设计令牌基座（`styles/tokens.scss` / `base.scss` + 10 个页面 scss 的硬编码色）、新增色值真源与生成物、`PhoneShell` / `custom-tab-bar` 挂载点、`AccuracyRing` 的 canvas 取色。
- **文档**：`docs/方案设计文档.md` 的 `/users/me/settings` 字段表。
- 无既有接口签名破坏（新字段可选）；无迁移工具，加列走幂等 DDL（`scripts/apply_sql.py`）。

## Non-goals（不做什么）

- **不改任何页面的结构与文案** —— 只换颜色的来源。
- **不改尺寸 / 字号 / 圆角 / 动效** —— 主题只换颜色，不换排版。
- **不做跟随系统深色**（`prefers-color-scheme`）—— 那是另一件事。
- **不做用户自定义调色板** —— 本轮只给 5 套预设。
- **不给标签栏 PNG 图标重烘焙** —— 图标色不随主题变（已登记为已知边界）。
- **不改公会卡导出图的 canvas 配色**、**不改原生弹层**（`showModal` / `showToast` 由微信渲染，WXSS 管不到）。
