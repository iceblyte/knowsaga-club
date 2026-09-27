# Design

## Context

- `frontend/src/styles/tokens.scss` 是全站颜色的**唯一来源**：定义 99 个 SCSS 变量，46 个 `.scss` 通过 `@use` 引用它。SCSS 变量在**编译期**被替换成字面量，产物里不再有变量名 ⇒ 运行时切换颜色在当前机制下不可能。这是必须先动机制的原因（动机见 proposal.md - Why）。
- **实测（非推断）**：全仓没有任何 SCSS 颜色函数（`rgba()` / `mix()` / `lighten()` / `darken()` / `transparentize()`）作用在颜色 token 上；唯一命中的 `math.round($proto-px)` 是尺寸换算。这条决定了「把 token 值换成 `var()`」不会撞上「SCSS 无法对 `var()` 求值」的编译错误。
- 31 个页面里 30 个以 `PhoneShell` 为根，其根节点是 `<View className='page'>`；`custom-tab-bar` 是独立组件，不在 `PhoneShell` 内。
- **微信 WXSS 不支持属性名选择器 `[...]`**（官方文档明写，且推荐只用 class 选择器）⇒ 挂载点只能是 **class**。
- **步骤 0 地基已实测通过**：把 `var(--k-spike)` 与带兜底的 `var(--k-spike-none, <色>)` 注入构建产物后，postcss 原样保留、未被改写（编译期无风险）；在微信开发者工具里肉眼确认「社团大厅顶部标题变红 + `‹` 返回箭头变蓝」⇒ **运行时 WebView 认 `var()`**。
- 后端已有 `UserSettings` 表与 `GET|PATCH /users/me/settings`；前端已有 `services/settings.ts` / `store/useAppStore.ts` / `utils/cache.ts` 的设置链路 ⇒ 本次是**扩展**，不是新建。

## Goals / Non-Goals

**Goals:**

- 让「换颜色」成为运行时可切换的能力，同时保证**默认外观逐项不变**。
- 色值只有一个真源；生成物与真源不一致时能被机检拦住。
- 新增的 4 套主题（含一套暗色）满足 WCAG AA，且不靠兜底掩盖问题。

**Non-Goals:**

- 不做主题的在线下发 / 热更新 / 用户自定义（预设集合是编译期常量）。
- 不改排版尺度（尺寸、字号、圆角、动效一律不动）。
- 不追求让 PNG 图标与原生弹层跟随主题（见 D8）。
- 不引入 CSS-in-JS 或运行时样式引擎。

## Decisions

### D1 换肤机制：CSS 自定义属性 + 根类名

把颜色 token 的值改成 `var(--k-xxx, <原字面量>)`；主题类只在根节点上重定义 `--k-*`。

**备选与否决理由：**

- **编译期生成 N 套作用域样式**（`.ui-theme--x .card { … }`）：产物体积 ×N，且要重写全部 46 个消费方文件。作为**回退方案**保留 —— 只有地基实测不通过才启用。
- **属性选择器 `page[data-theme]`**：微信 WXSS 不支持 ⇒ 直接否决。
- **JS 运行时改样式**：需枚举并改写每个节点，样式来源被撕裂成两处，维护与验证都更贵 ⇒ 否决。

选 CSS 变量的额外好处：**零漂移是构造保证** —— 默认主题不挂类 ⇒ 直接落 fallback，而不是靠「记得别改错」。

### D2 挂载点：`PhoneShell` 根 + `custom-tab-bar` 根

只有两个挂载点：`components/PhoneShell/index.tsx` 的根 `<View className='page'>` 与 `custom-tab-bar/index.tsx` 的根。前者覆盖 30 个页面，后者覆盖标签栏。

**备选**：每个页面各自挂 —— 漏一个就是静默的「半主题」，新增页面时也容易忘 ⇒ 否决。

### D3 改造范围：只换颜色 token 的值

`tokens.scss` 里**颜色类** token 的值改为 `var()`；尺寸、字号、字距、圆角、动效 token 一字不动。依据是 Context 里那条实测：没有 SCSS 颜色函数作用于颜色 token，所以 46 个消费方文件**无需改动**。

### D4 色值真源：`shared/ui-themes.json` → 生成 `_themes.scss` + parity 校核

需要色值的有两个运行时：WXSS（CSS 变量）与 JS（canvas 取色）。两份手抄必然漂移，所以：真源 `shared/ui-themes.json` →（构建期脚本）→ `styles/_themes.scss`（产物入库，同 `assets/icons/tab.ts` 的既有做法）；另配校核脚本，生成物与真源不一致即失败（沿用 `check:scoring` / `check:links` 的先例）。

**备选**：手写 `_themes.scss` —— 5 套 × 40 余个令牌，手改必错 ⇒ 否决。

### D5 默认主题不写进 JSON

`paper` 的色值就是 `tokens.scss` 里的**原字面量**（即 `var()` 的 fallback 位），不写进 `ui-themes.json`。理由：一旦默认色也抄进 JSON，就有了两处默认色定义，任一处改了都不会立刻暴露。⇒ 默认主题的唯一定义处仍是 `tokens.scss`。

### D6 持久化：服务端列 + 本地镜像

`user_settings.ui_theme VARCHAR(16) NOT NULL DEFAULT 'paper'`；前端在 Taro Storage 存一份镜像。

- **启动**：store 初值**同步**读镜像 ⇒ 首帧即正确主题（对齐 spec 的「冷启动不闪」）。
- **对账**：启动后拉一次 `/users/me/settings`，以服务端为准并回写镜像；**失败静默**（保留本地值，不打扰用户）。
- **切换**：先改 store（界面立刻变）+ 写镜像 → PATCH；失败翻回原值 + 提示。与设置页三个开关同一套纪律。
- **镜像键加入 `PROTECTED_KEYS`**：主题是偏好，不是缓存。

**备选**：只存在本机 —— 换设备就丢，不满足 spec 的「跨设备一致」⇒ 否决。

### D7 校验：白名单落在服务端

`UserSettingsUpdateRequest.ui_theme` 用**白名单**校验（同 `avatar_key` 的理由：该值决定客户端加载哪套皮肤）。不合法值 → 明确错误，**不静默兜底**（spec 要求）。

### D8 覆盖边界（如实登记，不假装兑现）

不受主题影响：标签栏 PNG 图标（烘焙了固定的未选中 / 选中两色）、微信原生 `showModal` / `showToast` / `showActionSheet`、`utils/guildCard.ts` 的 canvas 导出图、各 `*.config.ts` 的 `backgroundColor`（由 `Taro.setBackgroundColor` 在切换时补）。

### D9 暗色主题必须单独给值，并补掉硬编码色

`midnight` 是唯一的暗色主题，三处不能照搬浅色：纸纹 `--k-grain`（`mix-blend-mode: multiply` 在暗底会变成噪点）、`base.scss` 里的白色内高光（暗底须换深色高光）、整页背景渐变（`--k-board-img` 换暗色叠加）。

**并且**：`base.scss` 的 22 处硬编码色、10 个页面 scss 的 13 处（另有 8 处是注释）必须一并纳入自定义属性 —— 否则暗色主题会在这些点上「漏白」，而这类遗漏在浅色主题下**完全看不出来**，只有切到暗色才暴露。

### D10 canvas 取色跟随主题

`AccuracyRing` 用 Canvas 2D 画弧，读不到 CSS 变量 ⇒ 从 `constants/ui-theme.ts`（读真源）取当前主题的色值。公会卡导出图**不在本次范围**（另立变更）。

### D11 主题标识与名称

| id | 名称 | 类型 | 色值来源 |
| --- | --- | --- | --- |
| `paper` | 纸与印 | 浅色 · **默认** | `tokens.scss` 原字面量（不写进 JSON） |
| `indigo` | 宣纸靛墨 | 浅色 | `redesign-v4` 实验室 A |
| `vermilion` | 素白墨朱 | 浅色 | `redesign-v4` 实验室 B |
| `midnight` | 夜航公会 | 暗色 | `redesign-v4` 实验室 C |
| `lime` | 青柠 | 浅色 | `theme-lab-v3` 已求解值 |

## 与现有实现 / 原型的冲突点（先列出，不自行拍板）

1. **`tokens.scss` 文件头写着「唯一视觉来源：prototype/00-设计规范.html」**。新增 4 套主题后这句话不再完整 ⇒ 打算改写成**分层表述**：默认主题（`paper`）仍以原型为准，其余主题以 `shared/ui-themes.json` 为准。这是对文档口径的修改，**不是**削弱原型的裁决权。
2. **原型只定义了「纸与印」一套外观**，新增 4 套没有原型可依 ⇒ 它们的设计依据是既有设计实验室产物（`redesign-v4` 的 A/B/C 与 `theme-lab-v3` 中已按 WCAG 求解过的青柠值），**不是**原型。这一点必须在设计文档里写明，免得日后被读成「原型里本来就有这些主题」。
3. **`frontend/.gitignore` 命中 `dist/`** ⇒ 步骤 0 的 spike 注入不产生 git 变更（已复核为 0 条）。

## 硬约束逐条回应

| # | 硬约束 | 如何满足 |
| --- | --- | --- |
| 1 | 后端走 TDD：先写测试跑红，再写实现跑绿 | tasks 里后端每条都拆成「写测试跑红」+「写实现跑绿」两步 |
| 2 | 前端改动零视觉漂移，且要有实测证据 | 默认主题走 fallback（构造保证）；另用浏览器对**改造前后**逐令牌读 `getComputedStyle` 比对，以读数而非截图下结论 |
| 3 | 公开仓库，密钥绝不入库 | 本次不新增任何密钥；提交前跑 `python tools/scan_secrets.py` |
| 4 | 接口统一信封，只在 `services/request.ts` 解包 | 新字段走既有 `services/settings.ts` 链路，不新开解包点 |
| 5 | 接口改动必须同步 docs 与 shared 用例 | 更新 `docs/方案设计文档.md` 的 `/users/me/settings` 字段表；`shared/scoring-cases.json` 与评分无关 ⇒ **不改**，登记说明 |
| 6 | 文案与实现冲突时改文案 | 换肤覆盖不到的部分不写「全部元素已随主题变化」，如实说明边界 |
| 7 | 交付页面要连入口一起交 | 设置页新增入口行与该子页**同时**交付，不留占位 toast |

## 项目已知坑的规避

- 前端禁 `style={{}}` 内联对象、长度不许写死 ⇒ 主题类与 `--k-*` 一律走 **class + SCSS**，不在 JSX 里写内联样式。
- Taro 的失效大多是**静默**的 ⇒ 交付前真浏览器跑一遍并**量 DOM / 计算样式**，不靠肉眼。
- 页面必须有一处挂载即发首帧请求 ⇒ 本次不改任何页面的请求逻辑，只改颜色来源。

## Risks / Trade-offs

- [暗色主题漏白：某处硬编码色没纳入自定义属性，在暗底上显示为刺眼白块] → 把 `base.scss` 22 处与 10 个页面 13 处一并改造，并在浏览器里逐屏检查暗色主题的对比与溢出。
- [生成物与真源漂移] → parity 校核脚本进闸门，不一致即失败。
- [首屏闪回默认主题] → 本地镜像**同步**读作 store 初值。
- [主题类漏挂导致半主题] → 只有两个挂载点，且都纳入验证清单（标签栏单独看一眼）。
- [WCAG 压线：求解停在 4.50 / 3.00，8bit 量化后翻红] → 求解按「门槛 + 安全余量」，判定发生在量化后的色值上（沿用 v3 的教训）。
- [微信端不生效但 H5 正常] → 步骤 0 已在开发者工具确认 `var()` 生效；交付前仍要求双端各跑一次。

## Open Questions

- 无。配色值来自既有设计资产（v4 / v3），换肤机制已由步骤 0 实测确定。
