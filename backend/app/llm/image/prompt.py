"""题目 → 生图提示词。

## 这个文件唯一要守住的东西：**不泄题**

配图是**永久**留在题目里的，比一次性的提示更难收回。所以「下面哪个是苹果」这类题
一旦把答案物件画进画面，这道题就废了 —— 而且从界面上看不出任何异常。
提示词构建是这个风险的**第一道也是唯一一道**防线（模型端只能靠负向提示词兜底）。

规则（对应规格 `question-images` 的「配图不得泄露选项内容与正确答案」）：

1. 只用**知识点标签** + 从题干取得的**主题词**，不用选项、不用解析、不用正确答案；
2. 题干里的「提问模板」（`下面哪个…` / `下列说法…`）先剥掉 —— 它们不是画面内容；
3. **题干里出现过的选项文字要被抹掉**。这一步是上面第 1 条的硬保证：
   「下面哪个是苹果」的题干里写着 `苹果`，而 `苹果` 正是某个选项 ——
   抹掉之后主题只剩模板骨架，于是回退成「只用知识点」。
4. 明确禁止画面出现任何文字。

⚠️ 第 3 条会**误伤**：某个选项文字恰好是题干里的普通词时也会被抹掉。
这是有意的取舍 —— 少一点相关性，换「不可能泄题」。相关性的损失通常由
知识点标签兜住（它本来就是这个知识点的名字）。
"""

from __future__ import annotations

import re

from app.models.quiz import Question

#: 题干里的提问模板。**长串在前**，否则 `下面` 会先把 `下面哪个` 吃掉一半。
#: 剥掉它们的理由：这些词描述的是「题在问什么」，不是「画面该画什么」。
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

#: 抹掉选项文字后，主题至少要有这么长才算「够用」；否则回退成只用知识点。
#: 取 3 是因为中文里两字词太泛（`苹果` / `向量`），三字以上才带得动一个画面。
_MIN_TOPIC_CHARS = 3

#: 主题词的长度上限。题干可能很长（阅读理解式），而画面描述越短越可控。
_MAX_TOPIC_CHARS = 60

#: 知识点标签的长度上限。与 `questions.knowledge_point VARCHAR(64)` 一致。
#: ⚠️ 必须在这里截断，而不是靠 `MAX_PROMPT_CHARS` 兜底：整段提示词的尾部
#: 是**约束条款**（不出现文字 / 中性示意），被截掉等于把护栏删了，
#: 而提示词看着依然「正常」。所以每个可变部分各自有界，末尾那个上限只是最后一道防呆。
_MAX_KNOWLEDGE_POINT_CHARS = 64

#: 整个提示词的长度上限（最后一道防呆）。
MAX_PROMPT_CHARS = 800

#: 首尾要剥掉的标点（疑问号、句号、空格、以及用来分句的符号）。
_EDGE_PUNCT = " \t\r\n，。、；：？！?！,.;:·—－-–~～「」『』【】《》()（）\"'“”‘’"


def strip_templates(text: str) -> str:
    """剥掉题干里的提问模板与题型标注，再去掉首尾标点。

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


def topic_of(question: Question) -> str:
    """从题干提炼画面主题；提炼不出可用主题时返回空串（调用方回退到知识点）。

    ⚠️ 空串是**正常返回值**，不是错误：题目本身就是「哪个是 X」这种形态时，
    除了知识点之外没有安全的画面主题可言。
    """
    topic = strip_templates(question.stem)
    topic = remove_option_texts(topic, question)
    topic = topic.strip(_EDGE_PUNCT)
    if len(topic) < _MIN_TOPIC_CHARS:
        return ""
    return topic[:_MAX_TOPIC_CHARS]


def build_prompt(question: Question) -> str:
    """构建生图提示词。

    ⚠️ 只读 `stem` / `knowledge_point` / `options`（后者仅用于**排除**）——
    不读 `answer`、不读 `explanation`。前两者一旦进提示词就是直接泄题。
    """
    knowledge_point = (question.knowledge_point or "").strip()[:_MAX_KNOWLEDGE_POINT_CHARS]
    topic = topic_of(question)

    subject_lines = []
    if topic:
        subject_lines.append(f"画面主题：{topic}")
    if knowledge_point:
        subject_lines.append(f"所属知识点：{knowledge_point}")
    if not subject_lines:
        # 理论上到不了：`knowledge_point` 是 NonEmptyStr，题干也是。
        # 真到了也照样给一句能画的话，而不是把空提示词发给上游（那必然 400）。
        subject_lines.append("画面主题：抽象的学习示意")

    lines = [
        "为一张学习卡片生成写实风格的配图。",
        *subject_lines,
        "画面要求：",
        "1. 只画具体、常见、容易辨认的实物或真实场景；主体居中、背景干净、构图简洁。",
        "2. 画面中不得出现任何文字，包括汉字、字母、数字、公式、招牌、标签、涂鸦与标志。",
        "3. 只做中性示意，不表达对错：不出现试卷、答题卡、选项列表、勾选、对勾与叉号。",
        "4. 不出现人脸特写、不出现任何品牌或机构的标识。",
        "5. 与上述主题无关的元素不要出现在画面里。",
    ]
    prompt = "\n".join(lines)
    return prompt[:MAX_PROMPT_CHARS]
