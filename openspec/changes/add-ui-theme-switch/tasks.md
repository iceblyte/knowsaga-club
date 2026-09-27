# Tasks

> 顺序即依赖顺序。后端每条拆成「写测试跑红」与「写实现跑绿」两步（项目硬约束）。
> 跑后端测试的环境变量：`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--basetemp=../.tmp_pt_base`。
> 设计决策编号（D1–D14）见 `design.md`。
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
- [x] 3.7 **零漂移验证**：默认主题下，浏览器逐令牌比对本变更前后的计算样式，读数一致（承接 6.2）
      —— 编译级归一化比对**已绿**（45 个 scss 逐字节相同）+ `paper` 组 10 张图标 PNG 与
      被删掉的旧扁平文件 **sha256 逐字节相同**；浏览器侧读数见 6.2，**由用户实跑确认**
- [x] 3.8 **（D12，实施中新发现的真 bug）** 5 个被「别名」掐断的令牌改为 `var(--k-*, …)`：
      `$opt-sel-border` / `$opt-ok-border` / `$opt-bad-border` / `$btn-magic-edge` / `$btn-gold-edge`。
      青柠的已选描边实测 **2.03:1 → 3.13:1**（求解值终于被消费）。
      复核：零漂移仍逐字节相同 + 死令牌 0（69 定义 / 69 引用）
- [x] 3.9 **（D13，实施后由用户实测追问「底部图标为什么不随主题变」才发现）** 标签栏的三件事：
      - [x] ① `custom-tab-bar/index.scss` 的选中文字 + 顶部指示条 `$magic` → `$magic-ink`
            （青柠选中文字 **2.12:1 → 4.70:1**；`magic-ink` 在另外 4 套主题与 `magic` **同值**
            ⇒ 逐字节零漂移。**不用 `$magic-d`**：它会把纸与印的指示条改成 `#1F4694`，那是真漂移）
            复核：零漂移仍逐字节相同 ✅ / `check:theme` exit 0 ✅ /
            产物 `custom-tab-bar/index.wxss` = `color:var(--k-magic-ink,#2f6bd8)`、
            全文 `var(--k-magic,` **0 处**；`build:weapp` exit 0 ✅
      - [x] ② 按主题生成标签栏图标集，修 `midnight` 选中图标 **2.80:1**（低于非文本 3:1）。
            **走的是 (b) 预生成 PNG**：复用已验证的位图路径，不重新引入
            `image` + SVG 的三条未兜底限制，也不赌 `-webkit-mask` 在微信 WebView 的可用性。
            - `rasterize_tab_icons.py` 改为按主题出 5 套（10 → **50 张 / 33.8 KB**），
              色取自各主题 `--k-ink-3` / `--k-magic-ink`（**读 scss，不手抄**）；
              产物 `assets/icons/png/<theme>/`，旧的平铺布局由脚本自清
            - `extract_tab_icons.py` 生成的 `tab.ts` 改为「主题 → 图标集」
              （`Record<UiThemeId, TabIconSet>` + `tabIconsOf`）
            - 修后读数：`midnight` 选中 **2.80 → 6.39:1**；四套新主题全部 ≥ 4.63:1
            - **默认主题零漂移的证据是哈希不是推理**：`png/paper/` 10 张与改造前
              **逐字节相同**（sha256，10/10）
            - 产物取证：`dist/custom-tab-bar/index.js` 内联 `data:image/png;base64`
              **恰好 50 处**（原 10 处）、50 张源图标 **50/50 命中**、
              5 套主题的同一图标 base64 互不相同；bundle 里
              `IA(A){return CA[A]??CA.paper}` 与 `g=IA(E)` 接线完整
            - ⚠️ **H5 端不受本次修复影响**：Taro H5 在 `tabBar.custom: true` 时
              `initTabbar()` 直接 early-return（`@tarojs/router/dist/tabbar.js` 里那句
              `// TODO: custom-tab-bar` 就是上游未实现），所以 **H5 根本没有标签栏**
              （既有事实，记录于 `.workbuddy/memory/2026-09-20.md`）⇒ 图标只在 weapp 侧生效
      - [x] ③ `frontend/scripts/audit_theme_contrast.mjs` 的 `CHECKS` 补
            `ink3 on paper2` 与 `magic-ink on paper2` 两条 —— 原先**整块标签栏是覆盖盲区**，
            所以 165 项全绿却漏掉这两条。
            断言 **165 → 175**；`paper` 两条按既有 sub-AA 登记（2.93:1 / 4.27:1，**不改**），
            既有项 7 → 9；四套新主题 4.63–16.40:1 全达标。
            同时把「体检表只覆盖它列出的组合」这条教训写进 `CHECKS` 的文档块
      - [x] ④ **（D14）把图标像素色钉进闸门**：新增 `scripts/check_icon_parity.mjs`，
            断言「PNG 里 alpha>0 的像素 RGB == 该主题 `--k-ink-3` / `--k-magic-ink`」，
            并接进 `check_theme_parity.mjs`（闸门 2 步 → **3 步**）。
            已做**反向验证**：往 `midnight/hall-active.png` 塞 `paper` 的图标 ⇒
            **exit 1** 且精确报出「像素色 `#2f6bd8`，预期 `#e0a455`」，随后还原并复核哈希一致
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

- [x] 6.1 浏览器实跑：5 套 × 4 屏（大厅 / 答题 / 冒险日志 / 我的），量 `--k-*` 生效、零裁切、无横向溢出、console error = 0
- [x] 6.2 浏览器实跑：默认主题逐令牌读数与改造前一致（与 3.7 合并出结论）
- [x] 6.3 微信开发者工具实跑：同上，标签栏单独看一眼（图标色已不再是边界 —— 3.9② 已修）
- [x] 6.4 数后端请求：启动对账只发一次，无重复探测

> **6.1–6.4 的证据归属（如实标注）**：这四条由**用户实跑确认**（2026-09-27，原话「我跑过了」）。
> **不是本 agent 量出来的读数** —— agent 手上只有产物级与静态级证据：50 张 base64 进包、
> bundle 接线完整、`check:theme` 175 断言、`tsc` / 双端构建 / `openspec validate` / `scan_secrets` 全绿。
> 按项目红线「别把没验证的说成验证过的」，此处不写成 agent 复现过。若日后要机器可复现，
> 需补一次 agent 侧的开发者工具实跑（现状：**未做**）。

## 7. 闸门

- [x] 7.1 全量 `pytest`（`CODEBUDDY_SAFE_DELETE_ENABLED=0` + `--junitxml` + `--basetemp=../.tmp_pt_base`）
      —— **1387 passed / 0 failed / 0 errors**（基线 1371 + 新增 16 条主题用例），
      读数取自 `--junitxml` 机器可读结果，非末行文字
- [x] 7.2 `tsc --noEmit`（src 0 错；`node_modules` 100 条为基线，不因本次变化）
- [x] 7.3 `python tools/scan_secrets.py` —— **干净**（读 484 文件 / 0 命中 / exit 0）
- [x] 7.4 `openspec validate --all` —— **6 passed / 0 failed**（1 变更 + 5 规格基线）
- [x] 7.5 `build:weapp` + `build:h5` —— 均 **exit 0**
      （3.9 ② 修完后重建：weapp **20.82s** / h5 **25.70s**）
      产物读数（**主题块真进包**）：`app-origin.wxss` 24 157 B 内 4 个 `.ui-theme--*` 各 1 次、
      `--k-opt-sel-border` 5 次（4 定义 + 1 消费）、`--k-grain` 6 次；
      `app.wxss` 仅 52 B（`@import`），`pages/settings/theme/index` 已在包内；
      h5 `css/app.*.css` 内同样 4 块齐全 + `var(--k-opt-sel-border,#2f6bd8)` 消费点存在。
      ⚠️ 3.9① 改完后重跑过 weapp（21.81s）、② 改完又重跑一次（20.82s）—— 产物须与源码同步。
      复核：`custom-tab-bar/index.wxss` = `color:var(--k-magic-ink,#2f6bd8)`，
      全文 `var(--k-magic,` **0 处**。
      **3.9② 的产物取证**：`dist/custom-tab-bar/index.js` 内联 `data:image/png;base64`
      **恰好 50 处**（改造前 10 处），50 张源图标 **50/50 命中**，5 套主题的同一图标
      base64 互不相同；bundle 内 `IA(A){return CA[A]??CA.paper}` + `g=IA(E)` 接线完整。
      ⚠️ 双端共用 `frontend/dist/` ⇒ **必须串行**；最后一次构建是 weapp（`dist/` 现为小程序产物）
      ⚠️ **H5 侧看不到这些图标不是 bug**：`tabBar.custom: true` 时 Taro H5 的
      `initTabbar()` 直接 return（上游 `// TODO: custom-tab-bar` 未实现）⇒ **H5 根本没有标签栏**，
      既有事实见 `.workbuddy/memory/2026-09-20.md`
- [x] 7.6 `git status --porcelain -- frontend/src/ backend/` 复核改动面与计划一致
      —— 3.9 修复后 `-uall` **70 项**（20 改/删 + 50 张新图标），全部落在
      `frontend/scripts/`、`frontend/src/assets/icons/`、`openspec/changes/` 内；
      **无 `.env`、无 `dist/`、无截图落仓**
- [x] 7.7 `npm run check:theme`（闸门 2 步 → **3 步**）—— exit 0：
      ① 生成物与真源一致（2 份）② WCAG 体检 **175 断言 / 5 主题**（既有项 9 条登记）
      ③ 图标像素色与主题一致 **50/50**
- [x] 7.8 **零漂移**（3.9 改完 scss 注释与图标后重跑）——
      「45 个 scss 归一化后的编译产物与基线**逐字节相同**」；
      另加 `png/paper/` 10 张 **sha256 逐字节相同**
- [x] 7.9 `tsc --noEmit`（3.9 ② 改完重跑）—— src 内 **0 错**（`node_modules` 100 条为基线）
      注：后端本次未改动 ⇒ 未重跑 `pytest`（7.1 的 1387 passed 仍是最近一次全量读数）