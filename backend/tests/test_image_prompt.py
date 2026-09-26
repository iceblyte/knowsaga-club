"""生图提示词构建（`add-question-image-generation` 第 3 组）。

**这个文件守的是「不泄题」**：配图是永久留在题目里的，一旦把正确答案画进画面，
这道题就废了，而从界面上看不出任何异常。所以每条规则都要被断言钉住。

## ⚠️ 2026-09-26 改形态 —— 别把这些断言「修」回去

旧形态是**规格说明书**：分段 + 「画面主题：」+「画面要求：」+ `1./2./3.` 编号 +
「画面中不得出现任何文字」。真实出图（`scripts/verify_image_chain.py`，两个模型各 3 张）
证明它**有害**：

- 三个模型**全部**把提示词里的中文当文案渲染进画面 —— 连「画面中不得出现任何文字」
  这句禁令本身、以及 `1. 只画具体…` 这种编号列表都被画了出来；
- z-image 那张甚至画出了指令的走形文本「固属要求：只具体、常见，容易应阶段」；
- 题干整句被当成知识卡片的标题（「TCP 建立连接为什么需要三次握手而不是两次？」）。

⇒ 提示词改成**画面描述**形态：单段、逗号分隔、无编号、无冒号标签、**无否定句**。
   「不出现文字」改由 `IMAGE_NEGATIVE_PROMPT` 负向通道兜（见下面
   `test_text_ban_lives_in_negative_prompt_not_in_positive`）。

## 本文件**不**断言什么（诚实的边界）

「画面里到底有没有文字」是**结果**，单测断不了 —— 它只能断形态，结果靠人工看图。
换模型 / 调风格后缀之后，必须重跑人工验收，别拿这里的绿当成画面干净的证明。
"""

from __future__ import annotations

import re

import pytest

from app.core.config import Settings
from app.llm.image import prompt as prompt_builder
from app.models.quiz import Question

from tests.conftest import SAMPLE_QUESTIONS


def _question(**overrides: object) -> Question:
    base = {
        "id": "q1",
        "type": "single",
        "stem": "RAG 的核心思路是什么？",
        "options": [
            {"key": "A", "text": "先检索相关资料，再把资料交给模型生成回答"},
            {"key": "B", "text": "把模型参数调大以获得更多知识"},
            {"key": "C", "text": "只用关键词匹配返回链接列表"},
        ],
        "answer": ["A"],
        "explanation": "RAG 先检索外部资料，再让模型基于资料作答。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "easy",
    }
    base.update(overrides)
    return Question.model_validate(base)


# ---------------------------------------------------------------- 基本形状
def test_prompt_contains_knowledge_point_and_topic() -> None:
    """纯中文题：主题与知识点原样进提示词（它们是画面的唯一依据）。"""
    q = _question(
        stem="咖啡豆烘焙到什么温度区间会进入第一次爆裂？",
        knowledge_point="咖啡烘焙",
        options=[
            {"key": "A", "text": "150°C 到 170°C"},
            {"key": "B", "text": "196°C 到 205°C"},
            {"key": "C", "text": "230°C 到 250°C"},
        ],
        answer=["B"],
    )
    text = prompt_builder.build_prompt(q)

    assert "咖啡豆烘焙" in text
    assert "咖啡烘焙" in text
    assert prompt_builder.topic_of(q) == "咖啡豆烘焙"


def test_prompt_contains_topic_and_knowledge_point_for_ascii_question() -> None:
    """带拉丁字母的题：字母被摘掉，但**中文部分仍然进提示词**。"""
    q = _question(
        stem="TCP 建立连接为什么需要三次握手而不是两次？",
        knowledge_point="TCP 协议",
        options=[
            {"key": "A", "text": "为了让双方都确认对方的收发能力"},
            {"key": "B", "text": "为了加快连接速度"},
            {"key": "C", "text": "为了加密传输内容"},
        ],
        answer=["A"],
    )
    text = prompt_builder.build_prompt(q)

    assert "建立连接" in text
    assert "协议" in text
    assert prompt_builder.topic_of(q) == "TCP 建立连接"


def test_prompt_is_a_single_paragraph_of_phrases() -> None:
    """提示词必须是**一段**逗号分隔的画面描述，不是分条列出的规格说明。

    分段 + 分条是旧形态最直接的祸根：中文生图模型见到 `1. … 2. …` 的排版，
    就照着画了一张「知识卡片」，把条目标题当文案渲染。
    """
    text = prompt_builder.build_prompt(_question())

    assert "\n" not in text
    assert not re.search(r"^\s*\d+\s*[.、)]", text, re.MULTILINE)


def test_prompt_has_no_meta_instructions() -> None:
    """提示词里不得出现「元指令」：它们是**描述这张提示词本身**的话，
    模型会把它们当画面文案画出来（实测：z-image 画出「固属要求：…」）。"""
    text = prompt_builder.build_prompt(_question())

    for phrase in (
        "画面要求",
        "画面主题",
        "所属知识点",
        "不得",
        "不要",
        "禁止",
        "不出现",
        "不表达",
        "只画",
        "只做",
    ):
        assert phrase not in text, f"元指令片段 {phrase!r} 出现在提示词里"


def test_text_ban_lives_in_negative_prompt_not_in_positive() -> None:
    """「画面不出现文字」的防线在**负向**通道，正向提示词刻意一个字都不提。

    这是本次改形态最反直觉的一条：把「不得出现任何文字」写进正向提示词，
    等于**告诉**模型「文字」这个词 —— 实测三个模型都把这句话本身画了出来。
    禁令只能走 `IMAGE_NEGATIVE_PROMPT`。

    ⚠️ 但负向对 `z-image-turbo` 是否真的生效**未经验证**（官方参数表里没有
    `negative_prompt`）。所以这条测试证明的是「防线放在哪」，**不是**「文字一定不会出现」——
    后者只能人工看图。
    """
    text = prompt_builder.build_prompt(_question())
    for word in ("文字", "汉字", "字母", "水印", "标志"):
        assert word not in text, f"{word!r} 不该出现在正向提示词里"

    # 负向那一侧必须有 —— 用字段默认值断言，不依赖本机 .env
    negative = Settings.model_fields["image_negative_prompt"].default
    assert "文字" in negative
    assert "汉字" in negative


def test_prompt_has_a_style_tail() -> None:
    """风格词是画面可控性的主要来源，任何分支下都必须在。"""
    assert prompt_builder._STYLE_TAIL in prompt_builder.build_prompt(_question())


def test_style_tail_asks_for_still_life() -> None:
    """风格尾缀必须是**静物**摄影。

    2026-09-26 实测：尾缀写「写实摄影…自然光」时 z-image 的人像摄影先验被激活 ——
    「光合作用」那道题画了一个**人物特写**（旧实现的「不出现人脸特写」禁令被删掉之后
    没人拦它了）。换成「静物摄影」后同一道题变成一只灯泡。

    `静物` 二字**本身就排除了人像**，这是不靠否定句达成约束的办法 ——
    否定句会被当文案渲染（见模块头），不能用来做约束。
    """
    assert "静物" in prompt_builder._STYLE_TAIL


# ---------------------------------------------------------------- 拉丁字母
def test_prompt_drops_latin_tokens() -> None:
    """拉丁字母 token 要摘掉：它们是画面里最主要的**文字来源**。

    2026-09-26 实测：提示词里只要有 `TCP`，z-image 三次全把它画成画面正中的大字
    （换成「静物摄影」尾缀也拦不住）；摘掉之后同一道题画的是**四端相连的接头** ——
    既没有文字，又真的在表达「建立连接」。
    """
    q = _question(
        stem="TCP 建立连接为什么需要三次握手而不是两次？",
        knowledge_point="TCP 协议",
        options=[
            {"key": "A", "text": "为了让双方都确认对方的收发能力"},
            {"key": "B", "text": "为了加快连接速度"},
            {"key": "C", "text": "为了加密传输内容"},
        ],
        answer=["A"],
    )
    text = prompt_builder.build_prompt(q)

    for token in ("TCP", "tcp"):
        assert token not in text, f"字母 token {token!r} 会让模型把它渲染成画面文字"


def test_prompt_keeps_latin_token_when_meaning_would_be_lost() -> None:
    """摘字母会让提示词**失去全部可画信息**时就不摘。

    反例（2026-09-26 实测）：`Python 的 GIL` + `CPython 并发` 摘完只剩「并发」，
    模型没有了题材抓手，只好抓「静物摄影」的风格先验自由发挥 —— 画出一支**口红**。
    宁可留一个字母缩写（画面至少与题目同源），也不要一张与题目毫无关系的静物照。

    这是**有意的取舍**：它意味着「画面不出现任何文字」在字母密集的题上
    可能做不到 —— 如实登记为已知边界，而不是假装两类情况都能兼顾。
    """
    q = _question(
        stem="Python 的 GIL 是什么？",
        knowledge_point="CPython 并发",
        options=[
            {"key": "A", "text": "一把让同一进程内同一时刻只有一个线程执行字节码的锁"},
            {"key": "B", "text": "一种把代码编译成机器码的工具"},
            {"key": "C", "text": "一种包管理机制"},
        ],
        answer=["A"],
    )
    text = prompt_builder.build_prompt(q)

    assert "CPython" in text or "Python" in text or "GIL" in text


# ---------------------------------------------------------------- 不泄题（核心）
def test_prompt_hides_answer_object_written_in_stem() -> None:
    """「下面哪个是苹果」这类题：苹果是答案，也是选项，绝不能进提示词。

    这一条是本功能最容易出的严重问题：只按题干构建提示词时，
    「苹果」会直接进画面 —— 等于把答案画出来。
    """
    q = _question(
        stem="下面哪个是苹果？",
        options=[
            {"key": "A", "text": "苹果"},
            {"key": "B", "text": "香蕉"},
            {"key": "C", "text": "橘子"},
        ],
        answer=["A"],
        knowledge_point="常见水果识别",
    )
    text = prompt_builder.build_prompt(q)

    for label in ("苹果", "香蕉", "橘子"):
        assert label not in text, f"选项文字 {label!r} 出现在了提示词里"
    # 主题被抹空之后必须回退成知识点，而不是把模板骨架当成画面内容
    assert "常见水果识别" in text
    assert prompt_builder.topic_of(q) == ""


@pytest.mark.parametrize("payload", SAMPLE_QUESTIONS, ids=[q["id"] for q in SAMPLE_QUESTIONS])
def test_prompt_never_contains_option_texts(payload: dict) -> None:
    """对**每一个**样本题目断言：任何选项文字都不在提示词里。

    比「只测一个特例」可靠：选项文字出现在题干里这件事与题型无关，
    而一旦出现就必须被抹掉。
    """
    q = Question.model_validate(payload)
    text = prompt_builder.build_prompt(q)

    for option in q.options:
        label = option.text.strip()
        # 判断题的「正确 / 错误」是**故意**不抹的（它们不是画面里的东西），
        # 所以这里与实现保持同一套豁免规则。
        if len(label) >= 2 and label.lower() not in prompt_builder._JUDGE_LABELS:
            assert label not in text, f"选项文字 {label!r} 出现在了提示词里"


@pytest.mark.parametrize("payload", SAMPLE_QUESTIONS, ids=[q["id"] for q in SAMPLE_QUESTIONS])
def test_prompt_never_contains_whole_stem(payload: dict) -> None:
    """**题干整句**不得进提示词 —— 改了形态之后新增的核心防线。

    整句进提示词有两个坏处，实测都成立：
    1. 模型把它当知识卡片的标题渲染 ⇒ 画面出现题干文字（＝文字污染）；
    2. 问句里常携带答案线索 ⇒ 泄题。

    判据取 10 字：超过这个长度的题干已经是一句话，而画面主题应当是**名词短语**。
    短于等于 10 字的题干本身就是短语（例如「细胞结构」），它进画面是对的。
    """
    q = Question.model_validate(payload)
    text = prompt_builder.build_prompt(q)

    stem = q.stem.strip().strip(prompt_builder._EDGE_PUNCT)
    if len(stem) > 10:
        assert stem not in text, f"题干整句进了提示词：{stem!r}"


@pytest.mark.parametrize("payload", SAMPLE_QUESTIONS, ids=[q["id"] for q in SAMPLE_QUESTIONS])
def test_prompt_never_contains_interrogatives(payload: dict) -> None:
    """疑问成分不得进提示词：它们在画面里没有任何对应物，只会变成渲染出来的文字。"""
    q = Question.model_validate(payload)
    text = prompt_builder.build_prompt(q)

    for word in ("？", "?", "为什么", "如何", "怎么", "哪些", "什么", "多少", "吗？"):
        assert word not in text, f"疑问成分 {word!r} 出现在了提示词里"


def test_prompt_does_not_use_explanation() -> None:
    """解析不进提示词：它通常包含答案的完整说明，是比选项更直接的泄题源。"""
    q = _question(explanation="解析里的独门措辞巧克力香蕉")
    text = prompt_builder.build_prompt(q)

    assert "解析里的独门措辞巧克力香蕉" not in text


def test_judge_labels_are_not_stripped_from_stem() -> None:
    """判断题的「正确 / 错误」不做抹除：它们不是画面里的东西，抹掉只会误伤题干。"""
    q = _question(
        stem="下列说法正确的一项是？",
        type="judge",
        options=[{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}],
        answer=["T"],
        knowledge_point="命题判定",
    )
    # 剥掉「下列说法」之后应当还留着「正确的一项」，而不是被抹成「的一项」
    assert "正确" in prompt_builder.topic_of(q)


# ---------------------------------------------------------------- 主题短语化
@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        # 疑问词处截断：问句 → 名词短语
        ("咖啡豆烘焙到什么温度区间会进入第一次爆裂？", "咖啡豆烘焙"),
        ("TCP 建立连接为什么需要三次握手而不是两次？", "TCP 建立连接"),
        # 谓语/系动词处截断，并剥掉尾部虚词
        ("光合作用的光反应阶段能直接固定二氧化碳。", "光合作用的光反应阶段"),
        ("RAG 系统必须先完成检索，才能生成最终答案。", "RAG 系统"),
        ("RAG 与搜索引擎最本质的差别在于？", "RAG 与搜索引擎最本质的差别"),
        # 模板剥掉之后剩下的已经是短语
        ("下面哪些属于 RAG 的典型收益？（多选）", "属于 RAG 的典型收益"),
    ],
)
def test_topic_of_returns_a_noun_phrase(stem: str, expected: str) -> None:
    """`topic_of` 必须把**问句**压成**名词短语** —— 这是本次改形态的核心。

    旧实现只在开头剥疑问模板，于是「TCP 建立连接为什么需要三次握手」
    这种以名词开头的整句原样进了提示词（实测被画成标题）。
    """
    q = _question(stem=stem)

    assert prompt_builder.topic_of(q) == expected


def test_topic_of_keeps_short_stem_as_is() -> None:
    """题干本来就是短语时不折腾它（截断规则有最短长度保护）。"""
    assert prompt_builder.topic_of(_question(stem="细胞结构")) == "细胞结构"


# ---------------------------------------------------------------- 边界
def test_topic_is_bounded() -> None:
    """题干很长时主题词要截断：画面描述越短越可控。"""
    q = _question(stem="生物学里的细胞结构" + "很长的题干" * 60 + "？")
    topic = prompt_builder.topic_of(q)

    assert len(topic) <= prompt_builder._MAX_TOPIC_CHARS


def test_prompt_is_bounded() -> None:
    q = _question(knowledge_point="知识点" * 200, stem="题干" * 200)
    assert len(prompt_builder.build_prompt(q)) <= prompt_builder.MAX_PROMPT_CHARS


def test_style_tail_survives_absurdly_long_input() -> None:
    """超长输入不得把**风格尾缀**挤掉。

    旧实现把约束条款放在提示词尾部、只靠「整段截断」控长度 —— 一个超长知识点
    就能把它们整段切走，而提示词看上去依然「正常」。新形态里尾缀是风格词，
    同样是"切掉了看不出来但画面会散"的部分，所以每个可变部分仍各自有界。
    """
    q = _question(knowledge_point="知识点" * 200, stem="题干" * 200)
    text = prompt_builder.build_prompt(q)

    assert prompt_builder._STYLE_TAIL in text


def test_knowledge_point_is_bounded() -> None:
    """知识点上限与 `questions.knowledge_point VARCHAR(64)` 一致。"""
    assert prompt_builder._MAX_KNOWLEDGE_POINT_CHARS == 64


def test_topic_empty_when_stem_is_all_template() -> None:
    """整句都是模板（`下面哪个？`）时返回空串，而不是把模板当主题。"""
    q = _question(
        stem="下面哪个？",
        options=[
            {"key": "A", "text": "甲"},
            {"key": "B", "text": "乙"},
            {"key": "C", "text": "丙"},
        ],
    )

    assert prompt_builder.topic_of(q) == ""
    # 主题为空时回退成「只用知识点」，提示词仍然是一句能画的话
    # （不能把空提示词发给上游 —— 那必然 400）
    text = prompt_builder.build_prompt(q)
    assert "RAG 基本定义" in text


def test_prompt_falls_back_when_knowledge_point_is_missing_too() -> None:
    """极端兜底：连知识点都拿不到时也要产出一句能画的话。

    `Question.knowledge_point` 是 NonEmptyStr，所以这条分支在真实数据上走不到 ——
    但它挡的是「空提示词发给上游」这种必然 400 的失败，值得留着并单独覆盖。
    """
    from types import SimpleNamespace

    stub = SimpleNamespace(stem="下面哪个？", knowledge_point="", options=[])
    text = prompt_builder.build_prompt(stub)

    assert text
    assert prompt_builder._STYLE_TAIL in text


def test_strip_templates_peels_multiple_layers() -> None:
    assert prompt_builder.strip_templates("下面关于 RAG 的说法？") == "RAG 的说法"
    assert prompt_builder.strip_templates("（多选）以下哪些属于收益？") == "属于收益"
