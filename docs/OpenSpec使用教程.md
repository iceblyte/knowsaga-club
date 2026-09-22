# OpenSpec 使用教程（知拾冒险社版）

> 目标读者：第一次听说 OpenSpec 的人。
> 一句话结论：它就是「**先写清楚要做什么，再让 AI 动手**」的流程，你只需要记 3 个动作。
> 当前状态：本仓库**已经装好、已经开启**，你可以直接用（第 1、2 节是记录，不用重做）。

---

## 0. 先搞懂它在干嘛

平时你怎么让 AI 干活？

> 你：「帮我加个错题本导出功能」
> AI：开始写码 → 写着写着跑偏了 → 你想改方向，只能去聊天记录里翻

OpenSpec 换了个做法：

**先让 AI 把「要做什么」写成 4 个小文件给你审** → **你点头（或直接改文件）** → **它才动手写代码**。

这 4 个文件是：

| 文件 | 说人话 |
| --- | --- |
| `proposal.md` | 为什么做、要做什么、**不做什么** |
| `specs/<能力名>/spec.md` | 做完以后用户能看到什么行为（= 验收标准） |
| `design.md` | 技术上打算怎么做 |
| `tasks.md` | 拆成一条条能勾选的小任务 |

**最大的好处**：改主意只要改这几个 Markdown，不用推翻已经写好的代码。

---

## 1. 装好没？（已装好，你不用做）

OpenSpec CLI 已经全局安装：

```bash
openspec --version     # 应输出 1.13.1
```

哪天提示「找不到命令」，重装一次即可：

```bash
npm install -g @fission-ai/openspec@latest
```

> 需要 Node.js ≥ 20.19.0（本机是 24.15.0，满足）。

---

## 2. 仓库开启了吗？（已开启，你不用做）

我在仓库根目录跑过一次：

```bash
cd knowsaga-club
openspec init --tools codebuddy --no-animation
```

它生成了两样东西：

```text
knowsaga-club/
├── openspec/                  ← 规格库，全是 Markdown，建议入库
│   ├── config.yaml            ← 项目说明书（我已填好，见第 5 节）
│   ├── specs/                 ← 已落地的规格（暂时是空的）
│   └── changes/               ← 正在做的改动，一个改动一个文件夹
│       └── archive/           ← 做完的改动会被挪到这里
└── .codebuddy/                ← 工具生成的命令/技能文件，别手改
```

> `.codebuddy/` 和 `openspec/` 目前都是**未入库的新目录**（`git status` 里能看到 `??`）。
> 建议都提交：`openspec/` 是你的规格资产，`.codebuddy/` 是可复现的工具配置。
> 如果你不想让 `.codebuddy/` 进 git，就在 `.gitignore` 里加一行 `.codebuddy/`。

---

## 3. 日常只有三个动作

### 动作一 · 出提案（你说需求，它写文件）

在 WorkBuddy 里直接打字：

```text
用 openspec 提案：给错题本加一个「导出 PDF」按钮
```

它会：

1. 读 `openspec/config.yaml` 里的项目红线（第 5 节）；
2. 去翻一遍相关代码、原型、现有 specs；
3. 建目录 `openspec/changes/add-export-pdf/`，写上面那 4 个文件。

> **这一步它只写 Markdown，不碰你的代码。**
> 这是 OpenSpec 刻意的硬规矩，防止「一边想一边写、写完才发现方向错」。

### 动作二 · 你审提案（改文件就是提意见）

打开 `openspec/changes/add-export-pdf/`，挨个看。

不满意**直接改 Markdown**，比用嘴描述快得多。想让它改就说：

```text
proposal.md 的「不做什么」太少了，把「不做云同步、不做批量导出」加进去；
tasks.md 每条都要写上具体文件路径
```

对应的斜杠形式是 `/opsx:update add-export-pdf`。

### 动作三 · 动手 + 归档

看完了说：

```text
开始实现 add-export-pdf 这个 change
```

它按 `tasks.md` 一条条做，做一条勾一条（`- [x]`）。

全部做完、测试通过之后：

```text
归档 add-export-pdf
```

归档会把 `changes/add-export-pdf/` 挪进 `changes/archive/`，
**并把里面的规格合并进 `openspec/specs/`** —— 那里积累的就是「这个项目现在到底长什么样」。

```text
想到一个功能
  └─ 用 openspec 提案：<一句话>      ← 它写 4 个 md，不碰代码
       └─ 我审 / 我改 md
            └─ 开始实现 <change 名>   ← 它按 tasks.md 干活
                 └─ 归档 <change 名>  ← 规格沉淀进 openspec/specs/
```

---

## 4. 怎么「叫」它 —— 三种方式，按可靠度排序

| 方式 | 怎么写 | 说明 |
| --- | --- | --- |
| ① 直接说（推荐） | `用 openspec 提案：……` | 我会读到技能说明并按流程走 |
| ② 读文件（保底，一定行） | `读 .workbuddy/skills/openspec-propose/SKILL.md，按它的流程给 XXX 出提案` | 不依赖任何自动识别 |
| ③ 斜杠命令 | `/opsx:propose 你的想法` | 这是 CodeBuddy / Claude Code 的原生形式；**WorkBuddy 里能不能用我没实测过**，用不了就走 ①② |

六个动作分别对应的技能（都在 `.workbuddy/skills/` 下）：

| 你想干嘛 | 技能名 | 官方斜杠形式 |
| --- | --- | --- |
| 还没想清楚，先聊聊 | `openspec-explore` | `/opsx:explore` |
| 出提案 | `openspec-propose` | `/opsx:propose` |
| 改提案 | `openspec-update-change` | `/opsx:update` |
| 动手实现 | `openspec-apply-change` | `/opsx:apply` |
| 归档 | `openspec-archive-change` | `/opsx:archive` |
| 手改了代码，反推回规格 | `openspec-sync-specs` | `/opsx:sync` |

> `.workbuddy/skills/` 里这 6 个是从 `.codebuddy/skills/` 复制过去的，因为 WorkBuddy 读的是 `.workbuddy/`。
> **新加的技能可能要重开一个对话才会出现在技能列表里**；没出现就直接用方式 ②。

---

## 5. 本项目专属：`config.yaml` 已经填好了

`openspec/config.yaml` 的 `context:` 段是**每次出提案都会喂给 AI 的项目说明书**。
我已经把本仓库的红线浓缩进去了：

- 技术栈与锁定版本（Taro 4.2.1 / React 18 / FastAPI / MySQL）
- 目录地图（`tokens.scss` 是唯一真源、`shared/scoring-cases.json` 双向锁定……）
- 硬约束：后端必须 TDD、前端零视觉漂移、密钥绝不入库、统一 `{code,message,data}` 信封
- 已知坑：禁 `style={{}}`、栅格要 `minmax(0, 1fr)`、测试禁用 `get_session_factory()`
- 额外要求：proposal 600 字内且必须写 Non-goals、tasks 每条带文件路径、后端任务先写测试

**以后你发现 AI 老犯同一个错，就把它写进这个文件的 `context:` 里** —— 比每次在对话里重复一遍管用得多。

### 另一个开关：跳过 specs

如果这次改动是**纯文档 / 纯重构 / 纯工具链**，不涉及任何接口或行为，
在 `openspec/changes/<名字>/.openspec.yaml` 里加一行：

```yaml
skip_specs: true
```

不加的话，`openspec validate` 会报
`Change must have at least one delta` —— 这是它在拦你「什么都没定义就开工」。

---

## 6. 五个查状态的命令（在终端里跑）

```bash
openspec list                            # 现在有哪些改动在做
openspec list --specs                     # 已经沉淀了哪些规格
openspec status --change add-export-pdf   # 这个改动写到第几步了
openspec validate --all --strict          # 体检：需求 / 场景有没有写漏
openspec view                             # 打开终端面板浏览
```

另外两个常用：`openspec show <名字>` 看内容，`openspec archive <名字>` 归档。

---

## 7. 常见问题

**Q：我直接改代码、没走提案，会怎样？**
不会怎样，只是规格和代码不一致了。之后用 `/opsx:sync` 把现状反推进规格即可。

**Q：提案写到一半想换方向？**
直接改 `openspec/changes/<名字>/` 里的 Markdown。此时一行代码都还没写，零损失。

**Q：会不会生成一堆垃圾文件？**
只会生成 Markdown。归档后 `changes/` 里只剩 `archive/`，长期生长的只有 `openspec/specs/`。
纯文本，可读、可 diff、可删。

**Q：和 git 怎么配合？**
把 `openspec/` 一起提交。一次改动 = 一个分支 = 一个 change 文件夹。

**Q：`.codebuddy/` 和 `.workbuddy/` 有什么区别？**
`openspec init` 按 CodeBuddy 的目录规范生成到 `.codebuddy/`；WorkBuddy 读的是 `.workbuddy/`。
所以我把 6 个技能复制了一份到 `.workbuddy/skills/`（`.workbuddy/` 已在 `.gitignore` 里，不进库）。

---

## 8. 一张卡片记住全部

```text
① 用 openspec 提案：<一句话描述>     →  它写 4 个 md，不碰代码
② 我审文件 / 直接改 md              →  不满意就说「改 proposal 的 XX」
③ 开始实现 <change 名>              →  它按 tasks.md 一条条做
④ 归档 <change 名>                  →  规格合并进 openspec/specs/

查状态：openspec list / status / validate --all --strict
```
