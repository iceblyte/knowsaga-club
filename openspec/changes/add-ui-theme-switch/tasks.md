# Tasks

> 顺序即依赖顺序。后端每条拆成「写测试跑红」与「写实现跑绿」两步（项目硬约束）。
> 跑后端测试的环境变量：`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--basetemp=../.tmp_pt_base`。
> 设计决策编号（D1–D11）见 `design.md`。

## 1. 色值真源与色值体检

- [ ] 1.1 把 `.workbuddy/design-preview/redesign-v4/index.html` 的 A/B/C 令牌与 `.workbuddy/design-preview/_v3_skins.css` 的青柠已求解值，映射到本项目 token（`$board/$paper/$paper2/$paper3/$line/$ink/$ink2/$ink3/$seal/$magic/$magic-d/$gold/$gold-d/$ok/$bad/$rare` + 状态底 `$paper-*/$opt-*` + 描边 `$stroke-*` + `$on-magic/$on-gold/$mask/$grain`），产出 `shared/ui-themes.json`（`paper` 不写入，见 D5）
- [ ] 1.2 写体检脚本（复用 `.workbuddy/design-preview/audit_contrast.py` 或落到 `tools/`），逐套核算语义色对的 WCAG 对比度：**0 不达标且无压线项**（判定发生在 8bit 量化后）
- [ ] 1.3 按体检结果修正色值直至全绿；暗色主题单独处理 `--k-grain` / `base.scss` 白内高光 / `--k-board-img`（D9）

## 2. 后端（TDD）

- [ ] 2.1 写测试跑红：`backend/tests/test_users_api.py` —— 默认值为 `paper`、合法值往返、非法值被拒（明确错误）、跨用户隔离、未选择过的用户仍是 `paper`
- [ ] 2.2 写实现：`backend/sql/09_user_settings_ui_theme.sql`（幂等 `ADD COLUMN ui_theme VARCHAR(16) NOT NULL DEFAULT 'paper'`），用 `backend/scripts/apply_sql.py` 对**业务库 + 测试库各跑一次**
- [ ] 2.3 写实现：`backend/app/db/tables.py` 的 `UserSetting.ui_theme`（`String(16)` / `nullable=False` / `default="paper"`）
- [ ] 2.4 写实现：`backend/app/models/user.py` —— `UserSettingsPublic.ui_theme`；`UserSettingsUpdateRequest.ui_theme` + 白名单 `field_validator`（D7）
- [ ] 2.5 写实现：`backend/app/services/user_service.py` —— `update_settings` 处理该字符串字段，`_to_settings_public` 带上
- [ ] 2.6 跑绿：`pytest tests/test_users_api.py tests/test_db_mapping.py` 全绿

## 3. 前端样式基座

- [ ] 3.1 `frontend/src/styles/tokens.scss`：颜色类 token 的值改为 `var(--k-xxx, <原字面量>)`，新增 `$board-img`；文件头的「唯一视觉来源」改为分层表述（冲突点 1）
- [ ] 3.2 `frontend/src/styles/base.scss`：22 处硬编码色改为自定义属性（D9）
- [ ] 3.3 10 个页面 scss 的 13 处硬编码色改为自定义属性（D9）
- [ ] 3.4 新增 `frontend/scripts/gen_theme_scss.mjs`：读 `shared/ui-themes.json` 生成 `frontend/src/styles/_themes.scss`（`.ui-theme--<id> { --k-*: … }` 块）
- [ ] 3.5 新增 `frontend/scripts/check_theme_parity.mjs`：生成物与真源不一致即失败；`frontend/package.json` 增 `check:theme` 脚本
- [ ] 3.6 `frontend/src/app.scss`：`@use "./styles/themes"`；跑生成 + parity 校核
- [ ] 3.7 **零漂移验证**：默认主题下，浏览器逐令牌比对本变更前后的计算样式，读数一致（承接 6.2）

## 4. 前端功能链路

- [ ] 4.1 新增 `frontend/src/constants/ui-theme.ts`：id 联合类型 / 列表 / id↔名称 / Canvas 取色（读真源）
- [ ] 4.2 新增 `frontend/src/utils/ui-theme.ts`：镜像读写 + `applyTheme(id)`（含 `Taro.setBackgroundColor`）
- [ ] 4.3 `frontend/src/store/useAppStore.ts`：`uiTheme`（初值**同步**读镜像，D6）+ `setUiTheme`
- [ ] 4.4 `frontend/src/utils/cache.ts`：`PROTECTED_KEYS` 增镜像键
- [ ] 4.5 `frontend/src/app.ts`：启动对账，失败静默（D6）
- [ ] 4.6 `frontend/src/components/PhoneShell/index.tsx` + `frontend/src/custom-tab-bar/index.tsx`：根节点挂 `ui-theme--<id>`（D2）
- [ ] 4.7 `frontend/src/constants/copy.ts`：新增主题相关文案（含覆盖边界的如实说明，硬约束 6）
- [ ] 4.8 `frontend/src/pages/settings/index.tsx`：新增「界面主题」一行（入口，硬约束 7）
- [ ] 4.9 新增 `frontend/src/pages/settings/theme/{index.tsx,index.scss,index.config.ts}`，并在 `frontend/src/app.config.ts` 注册
- [ ] 4.10 `frontend/src/components/AccuracyRing/index.tsx`：4 处硬编码色改为按主题取色（D10）
- [ ] 4.11 `frontend/src/types/api.ts` + `frontend/src/services/settings.ts`：`UserSettingsPublic` 增 `ui_theme`
- [ ] 4.12 `tsc --noEmit` 通过

## 5. 文档

- [ ] 5.1 `docs/方案设计文档.md`：`/users/me/settings` 字段表增 `ui_theme`（先 grep 定位，不猜位置）
- [ ] 5.2 `design.md` 冲突点 2 的落地：把「新增主题无原型可依、依据是设计实验室产物」写进 `docs/方案设计文档.md`
- [ ] 5.3 `shared/scoring-cases.json`：确认与主题无关 ⇒ **不改**，在此登记说明

## 6. 验证（一律以读数为准，不靠肉眼）

- [ ] 6.1 浏览器实跑：5 套 × 4 屏（大厅 / 答题 / 冒险日志 / 我的），量 `--k-*` 生效、零裁切、无横向溢出、console error = 0
- [ ] 6.2 浏览器实跑：默认主题逐令牌读数与改造前一致（与 3.7 合并出结论）
- [ ] 6.3 微信开发者工具实跑：同上，标签栏单独看一眼（图标色是已登记边界）
- [ ] 6.4 数后端请求：启动对账只发一次，无重复探测

## 7. 闸门

- [ ] 7.1 全量 `pytest`（`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--junitxml` + `--basetemp=../.tmp_pt_base`）
- [ ] 7.2 `tsc --noEmit`
- [ ] 7.3 `python tools/scan_secrets.py`
- [ ] 7.4 `openspec validate --all`
- [ ] 7.5 `build:weapp` + `build:h5`
- [ ] 7.6 `git status --porcelain -- frontend/src/ backend/` 复核改动面与计划一致
