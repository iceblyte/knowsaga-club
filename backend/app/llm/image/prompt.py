"""题目 → 生图提示词。

## 这个文件唯一要守住的东西：**不泄题**

配图是**永久**留在题目里的，比一次性的提示更难收回。所以「下面哪个是苹果」这类题
一旦把答案物件画进画面，这道题就废了 —— 而且从界面上看不出任何异常。
提示词构建是这个风险的**第一道也是唯一一道**防线（模型端只能靠负向提示词兜底）。

规则（对应规格 `question-images` 的「配图不得泄露选项内容与正确答案」）：

1. 只用**知识点标签** + 从题干取得的**主题词**，不用选项、不用解析、不用正确答案；
2. 题干里的「提问模板」（`下面哪个…` / `下列说法…`）与疑问/谓语成分先剥掉 ——
   它们描述的是「题在问什么」，不是「画面该画什么」；
3. **题干里出现过的选项文字要被抹掉**。这一步是上面第 1 条的硬保证：
   「下面哪个是苹果」的题干里写着 `苹果`，而 `苹果` 正是某个选项 ——
   抹掉之后主题只剩模板骨架，于是回退成「只用知识点」。

⚠️ 第 3 条会**误伤**：某个选项文字恰好是题干里的普通词时也会被抹掉。
这是有意的取舍 —— 少一点相关性，换「不可能泄题」。相关性的损失通常由
知识点标签兜住（它本来就是这个知识点的名字）。

## ⚠️ 2026-09-26 改形态：从「规格说明书」改成「画面描述」—— 别「修」回去

**旧形态**（分段 + `画面主题：` + `画面要求：` + `1./2./3.` 编号 + 末尾一句
「画面中不得出现任何文字」）在真实出图上被证明是**有害**的。两个模型各 3 张
（`scripts/verify_image_chain.py` + 人眼）结果：

- **三个模型全部把提示词里的中文当文案渲染进画面**；
- 被渲染出来的包括**编号列表**（`1. 只画具体、常见…`）、**冒号标签**
  （`所属知识点：`），甚至**那句禁令本身**「画面中不得出现任何文字」；
- z-image 一张画出了指令的走形文本「固属要求：只具体、常见，容易应阶段」；
- 题干整句被当成知识卡片的标题（「TCP 建立连接为什么需要三次握手而不是两次？」）。

⇒ 结论：**提示词里任何一"条"给人看的指令，都会变成画面里的一行字。**
   中文生图模型对「知识卡片」有强先验，见到 `1. 2. 3.` 的排版就直接照着排版画。

**新形态**因此是：单段、逗号分隔、无换行、无编号、无冒号标签、**一句否定句都没有**。
风格词只给画法（写实 / 构图 / 光线），不给约束。

**那「画面不出现文字」怎么办？** 移到 `IMAGE_NEGATIVE_PROMPT` 负向通道去兜。
⚠️ 但负向对 `z-image-turbo` 是否生效**未经验证**（官方参数表里没有 `negative_prompt`）——
所以「画面真的没有文字」是个**人工验收项**，不是单测能证明的东西。
换模型 / 调风格尾缀之后必须重新看图，别把单测绿当成画面干净的证明。

## 主题词为什么要「短语化」

旧实现只剥**开头**的疑问模板，于是以名词开头的整句原样进提示词
（`TCP 建立连接为什么需要三次握手而不是两次？` → 一个字都没剥掉）。
整句有两个坏处：被当标题渲染（＝画面出现题干文字），以及问句里常带着答案线索。
所以现在按**疑问词 / 谓语词**切一刀，只留前面的名词性主干（见 `topic_of`）。
"""

from __future__ import annotations

import re

from app.models.quiz import Question

#: 题干里的提问模板（仍在**开头**剥）。**长串在前**，否则 `下面` 会先把 `下面哪个` 吃掉一半。
_INTERROGATIVE_TEMPLATES: tuple[str, ...] = (
    "下面哪一种",
    "下面哪个",
    "下面哪项",
    "下面哪些",
    "下面说法",
    "下面关于",
    "以下哪一种",
    "以下哪个",
    "以下哪项",
    "以下哪些",
    "以下说法",
    "以下关于",
    "下列哪一种",
    "下列哪个",
    "下列哪项",
    "下列哪些",
    "下列说法",
    "下列关于",
    "哪一个",
    "哪一项",
    "哪一种",
    "下面",
    "以下",
    "下列",
    "关于",
    "哪个",
    "哪项",
    "哪些",
    "哪种",
    "什么",
    "如何",
    "为什么",
)

#: 题型标注。它是给答题人看的格式提示，不该进入画面。
_TYPE_MARKERS: tuple[str, ...] = (
    "（多选）",
    "（单选）",
    "（判断）",
    "(多选)",
    "(单选)",
    "(判断)",
    "【多选】",
    "【单选】",
    "【判断】",
)

#: 判断题的选项标签。它们不是「画面里的东西」，抹掉它们没有意义（反而会误伤
#: 题干里正常出现的「正确」二字），所以显式跳过。
_JUDGE_LABELS: frozenset[str] = frozenset(
    {"正确", "错误", "对", "错", "是", "否", "true", "false", "yes", "no"}
)

#: 疑问词。切在它**之前**：问句的疑问部分描述「题在问什么」，不是「画面该画什么」。
#: 例：`TCP 建立连接为什么需要三次握手而不是两次` → `TCP 建立连接`。
_INTERROGATIVE_CUTS: tuple[str, ...] = (
    "是什么",
    "为什么",
    "为何",
    "如何",
    "怎么样",
    "怎么",
    "怎样",
    "哪一种",
    "哪一项",
    "哪些",
    "哪种",
    "哪项",
    "哪个",
    "多少",
    "什么",
    "吗",
    "呢",
)

#: 谓语标记（系动词 / 助动词 / 情态动词）。切在它之前，留下**主语短语**。
#: 例：`光合作用的光反应阶段能直接固定二氧化碳` → `光合作用的光反应阶段`。
_PREDICATE_CUTS: tuple[str, ...] = (
    "能不能",
    "会不会",
    "可不可以",
    "是不是",
    "可以",
    "应该",
    "应当",
    "能够",
    "必须",
    "是否",
    "需要",
    "能",
    "会",
    "是",
)

#: 切完之后主题尾部常留下一个悬空的虚词（`咖啡豆烘焙**到**`），留着就成了半句话。
#: 循环剥，因为可能连着好几个（`…的差别在**于**`）。
_TRAILING_PARTICLES = "的到是在于与和及或了着过地得之其为把被"

#: 抹掉选项文字后，主题至少要有这么长才算「够用」；否则回退成只用知识点。
#: 取 3 是因为中文里两字词太泛（`苹果` / `向量`），三字以上才带得动一个画面。
_MIN_TOPIC_CHARS = 3

#: **单字**切词的最低命中位置。单字（`能` / `会` / `是`）误伤率明显更高 ——
#: `人工智能的核心` 里的 `能` 在第 3 个字符上，切下去会剩一个「人工智」。
#: 双字以上的切词用 `_MIN_TOPIC_CHARS` 当门槛就够了。
_SINGLE_CHAR_CUT_MIN = 6

#: 主题词的长度上限。题干可能很长（阅读理解式），而画面描述越短越可控。
#: 24 ≈ 一个中文名词短语的常见长度，再长就开始带从句了。
_MAX_TOPIC_CHARS = 24

#: 摘掉拉丁字母之后，中文部分至少要剩这么多字符才算「还画得出来」。
#: 不够就整个不摘（见 `_derender_latin`）—— 阈值与理由见那个函数。
_MIN_KEPT_CHARS = 6

#: 知识点标签的长度上限。与 `questions.knowledge_point VARCHAR(64)` 一致。
#: ⚠️ 必须在这里截断，而不是靠 `MAX_PROMPT_CHARS` 兜底：整段提示词的尾部
#: 是**风格词**（主体居中 / 背景干净 / 自然光），被截掉等于把画面的可控性删了，
#: 而提示词看着依然「正常」。所以每个可变部分各自有界，末尾那个上限只是最后一道防呆。
_MAX_KNOWLEDGE_POINT_CHARS = 64

#: 整个提示词的长度上限（最后一道防呆）。
MAX_PROMPT_CHARS = 800

#: 画面风格尾缀。**固定不变**，且刻意只含「怎么画」，不含任何约束句与编号 ——
#: 见模块头「2026-09-26 改形态」。逗号分隔，与主题拼成一段。
#:
#: ⚠️ `静物` 这个词是**实测的防人像护栏**，不是随手写的：尾缀为「写实摄影…自然光」时
#: z-image 把「光合作用」画成了**人物特写**（它的人像摄影先验被「自然光 + 背景干净」
#: 激活了）。换成「静物摄影」后同一道题变成一只灯泡 —— `静物` 本身就排除了人像，
#: 这是不用否定句就能达成约束的办法（否定句会被当文案渲染）。
#:
#: ⚠️ 末尾「背景干净，纯色背景」语义重复，但**别顺手合并** ——
#: 这一整串是实跑过的那一版（`verify_image_chain.py` + 人眼），
#: 改一个字就变成未验证的组合了。
_STYLE_TAIL = "静物摄影，主体居中，背景干净，纯色背景"

#: 主题彻底为空时的兜底画面词。宁可给一句能画的抽象话，
#: 也不把空提示词发给上游（那必然 400）。
_FALLBACK_SUBJECT = "抽象的学习示意"

#: 首尾要剥掉的标点（疑问号、句号、空格、以及用来分句的符号）。
_EDGE_PUNCT = " \t\r\n，。、；：？！?！,.;:·—－-–~～「」『』【】《》()（）\"'“”‘’"

#: 拉丁字母/数字的一段连续串。
_LATIN_RUN = re.compile(r"[A-Za-z0-9]+")

#: 所有空白（剥掉字母之后会留下双空格，中文之间也不需要空格）。
_ANY_SPACE = re.compile(r"\s+")


def strip_templates(text: str) -> str:
    """剥掉题干**开头**的提问模板与题型标注，再去掉首尾标点。

    循环剥离（而不是只剥一次）：`下面关于 RAG 的说法` 里有两层模板。
    """
    out = text or ""
    for marker in _TYPE_MARKERS:
        out = out.replace(marker, " ")

    changed = True
    while changed:
        changed = False
        stripped = out.strip(_EDGE_PUNCT)
        for template in _INTERROGATIVE_TEMPLATES:
            if stripped.startswith(template):
                stripped = stripped[len(template) :]
                out = stripped
                changed = True
                break
        else:
            out = stripped
    return out.strip(_EDGE_PUNCT)


def remove_option_texts(text: str, question: Question) -> str:
    """把题干里**出现过的选项文字**抹掉（见模块头的第 3 条）。

    只抹长度 ≥ 2 的选项文字：单字选项（如 `A`、`对`）在题干里出现的概率太高，
    抹掉会伤到正常内容，而单字几乎不构成「画出答案」的风险。
    """
    out = text or ""
    for option in question.options:
        label = (option.text or "").strip()
        if len(label) < 2:
            continue
        if label.lower() in _JUDGE_LABELS:
            continue
        if label in out:
            out = out.replace(label, " ")
    return re.sub(r"\s+", " ", out).strip(_EDGE_PUNCT)


def _first_cut_index(text: str) -> int:
    """找出「该从哪儿切断」的位置；没有可切的地方就返回 `len(text)`。

    同时看疑问词与谓语词，取**最靠前**的那个。单字切词有更高的位置门槛
    （见 `_SINGLE_CHAR_CUT_MIN`），否则 `人工智能` 会被从 `能` 上切开。
    """
    best = len(text)
    for marker in (*_INTERROGATIVE_CUTS, *_PREDICATE_CUTS):
        index = text.find(marker)
        if index < 0:
            continue
        floor = _SINGLE_CHAR_CUT_MIN if len(marker) == 1 else _MIN_TOPIC_CHARS
        if index >= floor and index < best:
            best = index
    return best


def _reduce_to_phrase(text: str) -> str:
    """把一句题干压成名词短语：在疑问/谓语词处切断，再剥掉悬空的尾部虚词。"""
    out = (text or "").strip(_EDGE_PUNCT)
    cut = _first_cut_index(out)
    if cut < len(out):
        out = out[:cut]
    return _trim_particles(out)


def topic_of(question: Question) -> str:
    """从题干提炼画面主题词（一个**名词短语**）；提炼不出可用主题时返回空串。

    ⚠️ 空串是**正常返回值**，不是错误：题目本身就是「哪个是 X」这种形态时，
    除了知识点之外没有安全的画面主题可言。

    ⚠️ 返回值是**短语**而不是原句 —— 这是 2026-09-26 改形态的一部分，
    理由见模块头「主题词为什么要短语化」。
    """
    topic = strip_templates(question.stem)
    topic = remove_option_texts(topic, question)
    topic = _reduce_to_phrase(topic)
    if len(topic) < _MIN_TOPIC_CHARS:
        return ""
    return topic[:_MAX_TOPIC_CHARS]


def _trim_particles(text: str) -> str:
    """剥掉首尾悬空的中文虚词（`的差别在**于**` / `**与**搜索引擎` / `**的**核心思路`）。"""
    out = (text or "").strip(_EDGE_PUNCT)
    while out and out[-1] in _TRAILING_PARTICLES:
        out = out[:-1].strip(_EDGE_PUNCT)
    while out and out[0] in _TRAILING_PARTICLES:
        out = out[1:].strip(_EDGE_PUNCT)
    return out


def _derender_latin(*candidates: str) -> list[str]:
    """把候选片段里的拉丁字母/数字摘掉，**除非摘完就没什么可画的了**。

    ## 为什么要摘

    2026-09-26 实测：提示词里只要有 `TCP`，z-image **三次全把它画成画面正中的大字**
    （换风格尾缀也拦不住）。摘掉之后同一道题画的是**四端相连的接头** ——
    既没有文字，又真的在表达「建立连接」。所以字母是画面里最主要的文字来源。

    ## 为什么不是无条件摘

    反例也是实测的：`Python 的 GIL` + `CPython 并发` 摘完只剩「并发」两个字，
    模型没了题材抓手，只好抓「静物摄影」的风格先验自由发挥 —— 画出一支**口红**。
    一张与题目毫无关系的静物照，比一张带字母缩写的图更糟（字母至少与题目同源）。

    ⇒ 所以这里做**取舍**：摘完中文总量不足 `_MIN_KEPT_CHARS` 时返回空列表，
      调用方据此退回**不摘**的版本。这个取舍的代价是：字母密集的题上
      「画面不出现任何文字」可能做不到 —— 如实登记为已知边界，不假装两全。

    Returns:
        摘干净后的片段列表；如果结论是「不该摘」，返回**空列表**。
    """
    stripped: list[str] = []
    for text in candidates:
        if not text:
            continue
        cleaned = _ANY_SPACE.sub("", _LATIN_RUN.sub("", text))
        cleaned = _trim_particles(cleaned)
        if cleaned:
            stripped.append(cleaned)

    if sum(len(part) for part in stripped) < _MIN_KEPT_CHARS:
        return []
    return stripped


def build_prompt(question: Question) -> str:
    """构建生图提示词：**一段逗号分隔的画面描述**。

    ⚠️ 只读 `stem` / `knowledge_point` / `options`（后者仅用于**排除**）——
    不读 `answer`、不读 `explanation`。前两者一旦进提示词就是直接泄题。

    ⚠️ 刻意**不做**的事（改形态时逐条试过、都有反例）：
    不写「画面要求」、不写编号、不写「不得出现文字」、不给冒号标签 ——
    它们都会被当作画面文案渲染出来。详见模块头。
    """
    knowledge_point = (question.knowledge_point or "").strip()[:_MAX_KNOWLEDGE_POINT_CHARS]
    topic = topic_of(question)

    parts: list[str] = [part for part in (topic, knowledge_point) if part]
    # 去掉重复：`咖啡烘焙，咖啡烘焙` 是纯粹的噪声（知识点常常就是主题的上位写法）
    unique = list(dict.fromkeys(parts))

    # 摘字母；摘完不够画就退回不摘的版本（取舍理由见 `_derender_latin`）
    derendered = _derender_latin(*unique)
    final = list(dict.fromkeys(derendered)) if derendered else unique
    if not final:
        final = [_FALLBACK_SUBJECT]
    final.append(_STYLE_TAIL)

    return "，".join(final)[:MAX_PROMPT_CHARS]
