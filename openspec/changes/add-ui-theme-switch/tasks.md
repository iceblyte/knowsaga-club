# Tasks

> 顺序即依赖顺序。后端每条拆成「写测试跑红」与「写实现跑绿」两步（项目硬约束）。
> 跑后端测试的环境变量：`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--basetemp=../.tmp_pt_base`。
> 设计决策编号（D1–D13）见 `design.md`。
> 勾选状态以**实测读数**为准，不以「看起来做完了」为准。

## 1. 色值真源与色值体检

- [x] 1.1 把 `.workbuddy/design-preview/redesign-v4/index.html` 的 A/B/C 令牌与 `.workbuddy/design-preview/_v3_skins.css` 的青柠已求解值，映射到本项目 token（`$board/$paper/$paper2/$paper3/$line/$ink/$ink2/$ink3/$seal/$magic/$magic-d/$gold/$gold-d/$ok/$bad/$rare` + 状态底 `$paper-*/$opt-*` + 描边 `$stroke-*` + `$on-magic/$on-gold/$mask/$grain`），产出 `shared/ui-themes.json`（`paper` 不写入，见 D5）
- [x] 1.2 写体检脚本（复用 `.workbuddy/design-preview/audit_contrast.py` 或落到 `tools/`），逐套核算语义色对的 WCAG 对比度：**0 不达标且无压线项**（判定发生在 8bit 量化后）
- [x] 1.3 按体检结果修正色值直至全绿；暗色主题单独处理 `--k-grain` / `--k-hi-inset` / `--k-grad-hi` / `--k-grad-lo`（D9）

> ⚠️ 1.2 的「0 不达标」口径对**默认主题**不成立：`check:theme` 报 `paper` 有 **7 条**低于 AA 的
> **既有**项（三级墨 11px / `.c-gold` / `.pill.ok` / `.pill.gold` / 已选 chip 描边 / 次级边界）。
> 它们**不改** —— 改了就是破坏「默认主题零漂移」这条硬约束。属如实登记的接受项，
> `check:theme` 每次运行都会原样打印出来。
> **新增的 4 套主题**（含暗色）语义色对**全部达标且留有余量**（165 项断言）。

## 2. 后端（TDD）

- [x] 2.1 写测试跑红：`backend/tests/test_users_api.py` —— 默认值为 `paper`、合法值往返、非法值被拒（明确错误）、跨用户隔离、未选择过的用户仍是 `paper`
      （红：`ImportError: cannot import name 'UI_THEME_IDS'`，exit 2）
- [x] 2.2 写实现：`backend/sql/09_user_settings_ui_theme.sql`（幂等 `ADD COLUMN ui_theme VARCHAR(16) NOT NULL DEFAULT 'paper'`），用 `backend/scripts/apply_sql.py` 对**业务库 + 测试库各跑一次**
      （自检读数：两库均 `has_ui_theme = 1`）
- [x] 2.3 写实现：`backend/app/db/tables.py` 的 `UserSetting.ui_theme`（`String(16)` / `nullable=False` / `default=UI_THEME_DEFAULT`）
- [x] 2.4 写实现：`backend/app/models/user.py` —— `UserSettingsPublic.ui_theme`；`UserSettingsUpdateRequest.ui_theme` + 白名单 `field_validator`（D7）
- [x] 2.5 写实现：`backend/app/services/user_service.py` —— `update_settings` 处理该字符串字段，`_to_settings_public` 带上
- [x] 2.6 跑绿：`pytest tests/test_users_api.py tests/test_db_mapping.py` 全绿
      （`91 passed / 0 failed`，其中 `test_ui_theme*` 16 条）

## 3. 前端样式基座

- [x] 3.1 `frontend/src/styles/tokens.scss`：颜色类 token 的值改为 `var(--k-xxx, <原字面量>)`；文件头的「唯一视觉来源」改为分层表述（冲突点 1）
- [x] 3.2 `frontend/src/styles/base.scss`：22 处硬编码色改为自定义属性（D9）
- [x] 3.3 5 个组件/页面 scss 的 8 处硬编码色改为自定义属性（D9）
      （`AccuracyRing` 1 / `ReminderPrompt` 1 / `profile/dashboard` 2 / `profile/knowledge-tree` 3 / `workshop/kb-upload` 1 —— 实测口径见 D9 的读数表）
- [x] 3.4 新增 `frontend/scripts/gen_theme_scss.mjs`：读 `shared/ui-themes.json` 生成 `frontend/src/styles/_themes.scss`（`.ui-theme--<id> { --k-*: … }` 块）
- [x] 3.5 新增 `frontend/scripts/check_theme_parity.mjs`：生成物与真源不一致即失败；`frontend/package.json` 增 `check:theme` 脚本
- [x] 3.6 `frontend/src/app.scss`：`@use "./styles/themes"`；跑生成 + parity 校核
- [ ] 3.7 **零漂移验证**：默认主题下，浏览器逐令牌比对本变更前后的计算样式，读数一致（承接 6.2）
      —— 编译级归一化比对**已绿**（45 个 scss 逐字节相同），浏览器读数见 6.2
- [x] 3.8 **（D12，实施中新发现的真 bug）** 5 个被「别名」掐断的令牌改为 `var(--k-*, …)`：
      `$opt-sel-border` / `$opt-ok-border` / `$opt-bad-border` / `$btn-magic-edge` / `$btn-gold-edge`。
      青柠的已选描边实测 **2.03:1 → 3.13:1**（求解值终于被消费）。
      复核：零漂移仍逐字节相同 + 死令牌 0（69 定义 / 69 引用）
- [ ] 3.9 **（D13，实施后由用户实测追问「底部图标为什么不随主题变」才发现）** 标签栏的三件事：
      - [x] ① `custom-tab-bar/index.scss` 的选中文字 + 顶部指示条 `$magic` → `$magic-ink`
            （青柠选中文字 **2.12:1 → 4.70:1**；`magic-ink` 在另外 4 套主题与 `magic` **同值**
            ⇒ 逐字节零漂移。**不用 `$magic-d`**：它会把纸与印的指示条改成 `#1F4694`，那是真漂移）
            复核：零漂移仍逐字节相同 ✅ / `check:theme` 165 项 exit 0 ✅ /
            产物 `custom-tab-bar/index.wxss` = `color:var(--k-magic-ink,#2f6bd8)`、
            全文 `var(--k-magic,` **0 处**；`build:weapp` 21.81s exit 0 ✅
      - [ ] ② 按主题生成标签栏图标集，修 `midnight` 选中图标 **2.80:1**（低于非文本 3:1）。
            两条路线待定：**(a)** 复用已有 `assets/icons/svg/*.svg`（10 个 / 4.7 KB）+ CSS `mask`
            ⇒ 零新增资源，但 `-webkit-mask` 在微信 WebView 的可用性**未验证**；
            **(b)** 按主题预生成 PNG（10 → 50 张 / ~34 KB）⇒ 沿用已验证路径，零支持风险
      - [ ] ③ `frontend/scripts/audit_theme_contrast.mjs` 的 `CHECKS` 补
            `ink3 on paper2` 与 `magic-ink on paper2` 两条 —— **当前是覆盖盲区**，
            标签栏底从未被任何一项覆盖，所以 165 项全绿却漏掉了这两条。
            ⚠️ 补的时候要给 `paper` 的 `ink3 on paper2`（2.93:1，既有 sub-AA）**留登记位**，
            否则会误伤零漂移
      - 状态：**① 已修并取证；② ③ 未做**。①②③ 的关系是「先补断言（红）→ 再修消费点 / 换资源（绿）」，
            本次只做了消费点那一半 ⇒ **体检盲区仍在**（D13 判据段已如实登记）
      - ⚠️ 系统弹窗（原生 + Taro 内联样式）**刻意不做**，理由见 D13 末段：
            原生弹窗底永远是白，`midnight` 的 `--k-bad`（#E56F5E）对白只有 3.10:1，
            照搬过去会把一个 6.43:1 的达标按钮变成不达标

## 4. 前端功能链路

- [x] 4.1 新增 `frontend/src/constants/ui-theme.ts`：id 联合类型 / 列表 / id↔名称 / Canvas 取色（读真源）
- [x] 4.2 新增 `frontend/src/utils/ui-theme.ts`：镜像读写 + `applyTheme(id)`（含 `Taro.setBackgroundColor`）
- [x] 4.3 `frontend/src/store/useAppStore.ts`：`uiTheme`（初值**同步**读镜像，D6）+ `setUiTheme`
- [x] 4.4 `frontend/src/utils/cache.ts`：`PROTECTED_KEYS` 增镜像键
- [x] 4.5 `frontend/src/app.ts`：启动对账，失败静默（D6）
- [x] 4.6 `frontend/src/components/PhoneShell/index.tsx` + `frontend/src/custom-tab-bar/index.tsx`：根节点挂 `ui-theme--<id>`（D2）
- [x] 4.7 `frontend/src/constants/copy.ts`：新增主题相关文案（含覆盖边界的如实说明，硬约束 6）
- [x] 4.8 `frontend/src/pages/settings/index.tsx`：新增「界面主题」一行（入口，硬约束 7）
- [x] 4.9 新增 `frontend/src/pages/settings/theme/{index.tsx,index.scss,index.config.ts}`，并在 `frontend/src/app.config.ts` 注册
- [x] 4.10 `frontend/src/components/AccuracyRing/index.tsx`：4 处硬编码色改为按主题取色（D10）
- [x] 4.11 `frontend/src/types/api.ts`：`UserSettingsPublic` 增 `ui_theme: UiThemeId`
      —— `services/settings.ts` **无需改动**：`UserSettingsUpdateRequest = Partial<UserSettingsPublic>`，
      加了字段自动跟上（文件里就是这么写的，本次验证属实）。原任务把该文件也列进来，属**过度指定**，已更正。
- [x] 4.12 `tsc --noEmit` 通过（**src 内 0 错**；`node_modules` 的 100 条为既有基线）

## 5. 文档

- [x] 5.1 `docs/用户系统方案设计文档.md`：§5.2 `user_settings` 列表演进增 `ui_theme` + §6.2 `/users/me/settings` 行说明（先 grep 定位，不猜位置）
      ⚠️ 原任务写的文件名是 `docs/方案设计文档.md`，实际是 `docs/用户系统方案设计文档.md`，已更正
- [x] 5.2 `design.md` 冲突点 2 的落地：把「新增主题无原型可依、依据是设计实验室产物」写进 `docs/用户系统方案设计文档.md`（§5.2 表后的引用块）
- [x] 5.3 `shared/scoring-cases.json`：确认与主题无关 ⇒ **不改**，在此登记说明

## 6. 验证（一律以读数为准，不靠肉眼）

- [ ] 6.1 浏览器实跑：5 套 × 4 屏（大厅 / 答题 / 冒险日志 / 我的），量 `--k-*` 生效、零裁切、无横向溢出、console error = 0
- [ ] 6.2 浏览器实跑：默认主题逐令牌读数与改造前一致（与 3.7 合并出结论）
- [ ] 6.3 微信开发者工具实跑：同上，标签栏单独看一眼（图标色是已登记边界）
- [ ] 6.4 数后端请求：启动对账只发一次，无重复探测

## 7. 闸门

- [x] 7.1 全量 `pytest`（`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--junitxml` + `--basetemp=../.tmp_pt_base`）
      —— **1387 passed / 0 failed / 0 errors**（基线 1371 + 新增 16 条主题用例），
      读数取自 `--junitxml` 机器可读结果，非末行文字
- [x] 7.2 `tsc --noEmit`（src 0 错；`node_modules` 100 条为基线，不因本次变化）
- [x] 7.3 `python tools/scan_secrets.py` —— **干净**（读 484 文件 / 0 命中 / exit 0）
- [x] 7.4 `openspec validate --all` —— **6 passed / 0 failed**（1 变更 + 5 规格基线）
- [x] 7.5 `build:weapp` + `build:h5` —— 均 **exit 0**（weapp 21.06s / h5 25.96s）
      产物读数（**主题块真进包**）：`app-origin.wxss` 24 157 B 内 4 个 `.ui-theme--*` 各 1 次、
      `--k-opt-sel-border` 5 次（4 定义 + 1 消费）、`--k-grain` 6 次；
      `app.wxss` 仅 52 B（`@import`），`pages/settings/theme/index` 已在包内；
      h5 `css/app.*.css` 内同样 4 块齐全 + `var(--k-opt-sel-border,#2f6bd8)` 消费点存在。
      ⚠️ 3.9① 改完后**又重跑了一次 weapp**（21.81s exit 0）—— 产物须与源码同步，
      否则 `dist/` 里还是旧的 `var(--k-magic,…)`。复核：`custom-tab-bar/index.wxss` 已是
      `color:var(--k-magic-ink,#2f6bd8)`。**h5 侧尚未重跑**（改的是共用的 scss，需在 6.1 前补一次）
      ⚠️ 双端共用 `frontend/dist/` ⇒ **必须串行**；最后一次构建是 weapp（`dist/` 现为小程序产物）
- [ ] 7.6 `git status --porcelain -- frontend/src/ backend/` 复核改动面与计划一致