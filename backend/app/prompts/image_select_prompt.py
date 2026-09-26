"""配图判断 Prompt（`add-question-image-generation` 第 18 组，design D18）。

## 这个 Prompt 在决定什么

出题完成后、生图之前，把题目清单交给模型，判断**哪几道值得配一张图**。
目的只有一个：**别把钱花在没有增益的图上**。

配图是逐张计费的，而实践里相当比例的题目画不出有意义的东西 —— 2026-09-26
的人眼验收中，抽象概念题会随机画成花、枫叶或灯泡（证据
`docs/image-chain-evidence-2026-09-26.txt`）。与其每道都配，不如先挑一遍。

## 与 `quiz_prompt.py` 的差别

那个是**生成**（产出一份完整题库），这个是**筛选**（只产出题号）。
所以这里刻意写短：判断依据只有题干、题型与知识点，
**不看选项、不看答案、不看解析** —— 与 `llm/image/prompt.py` 同一条纪律。
「答案侧」的信息不进这条链路，就没有泄题的可能（判断题的输出会决定画什么）。

## `json` 字样是硬要求

`json_mode` 通道要求提示词里出现 "json" 字样并提供示例（DeepSeek 官方要求，
见 `llm/langchain_factory.py` 的模块头）。改这段文案时别把示例删掉 ——
`tests/test_image_select.py::test_prompt_demands_json` 会响。

## 为什么 json 示例放在 System 里

`ChatPromptTemplate` 用 f-string 解析 human 模板，含花括号的字面量会被当成
占位符而抛 `Invalid format specifier`。System Prompt 以 `SystemMessage` 对象
传入、不参与模板解析，所以把含 `{}` 的示例放那里最稳（同 `quiz_prompt.py`）。
"""

from __future__ import annotations

from typing import Sequence

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from app.models.quiz import Question

#: 选题上限。5 道题里最多配 3 张 —— 这是**省钱**这条需求的直接体现：
#: 不设上限的话模型倾向于全选，这个功能就等于没做。
#: 题量档位若将来变大（`QUIZ_MAX_QUESTIONS`），这个数字要跟着重估。
MAX_SELECTED = 3

#: 单条题干 / 知识点进 Prompt 的最大长度。判断只需要大意，
#: 而题干没有长度上限（契约只要求非空）—— 不截断的话一次长题干就能把 Prompt 顶大。
_MAX_STEM_CHARS = 200
_MAX_KNOWLEDGE_POINT_CHARS = 40


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


IMAGE_SELECT_SYSTEM_PROMPT = (
    """你是一位教学插图顾问。下面会给你一份**已经出好的**题目清单，
请判断其中哪些题目**值得配一张插图** —— 也就是「看了这张图能帮助理解这道题」。

## 值得配图

- **具体的东西**：动物、植物、食物、器具、材料、天体、建筑、交通工具
- **看得见的结构或过程**：连接如何建立、数据往哪流、东西怎么组装、实验怎么做
- **有明确视觉形态的场景**：厨房、图书馆、实验室、路口

## 不值得配图

- **抽象概念、定义、原理、方法论**（例如「什么是设计模式」「某某的核心思路是什么」）
- **纯逻辑、数学、数值、统计、日期、版本号**
- **代码、接口、参数、配置、命令**
- **只剩文字表述的观点题与判断题**（例如「以下哪些属于……的收益」）
- 题目主题是一个**缩写或专有名词，而画面根本表现不出来**（例如「GIL」「HTTP 404」）

## 三条硬要求

1. **宁缺勿滥**：只选你确信「画出来能帮到理解」的题；拿不准就不选。
2. **最多选 """
    + str(MAX_SELECTED)
    + """ 道**。一局通常 5 道题，其中多数不值得配图。
3. 一道都不值得配时，就老老实实输出空数组 —— **不要为了凑数而选**。

## 输出格式（最高优先级）

你必须**只输出一个 json 对象**，不要开场白、不要解释、不要用代码块包裹：

{"ids": ["q1", "q4"]}

- `ids` 里的每一个题号都必须**来自下面给出的清单**，不得编造、不得重复。
- 一道都不需要时输出 {"ids": []}。
"""
)

#: Human 模板刻意只含一个变量，不含任何花括号字面量（见模块头最后一段）。
IMAGE_SELECT_HUMAN_TEMPLATE = """请判断下面这份题目清单里，哪些值得配一张图。

【题目清单】
{question_list}
"""


def format_question_list(questions: Sequence[Question]) -> str:
    """把题目渲染成判断用的清单（题号 / 题型 / 知识点 / 题干）。

    ⚠️ **只渲染这四个字段**。选项、答案、解析一律不进 —— 见模块头第二段。
    """
    lines: list[str] = []
    for index, question in enumerate(questions, start=1):
        stem = _clip(question.stem, _MAX_STEM_CHARS)
        knowledge_point = _clip(question.knowledge_point, _MAX_KNOWLEDGE_POINT_CHARS)
        lines.append(
            f"{index}. 题号 {question.id}｜题型 {question.type}"
            f"｜知识点 {knowledge_point}\n   题干：{stem}"
        )
    return "\n".join(lines)


def build_image_select_prompt() -> ChatPromptTemplate:
    """构造判断用的 Prompt 模板。

    输入变量：
        question_list: `format_question_list()` 的产物。
    """
    return ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=IMAGE_SELECT_SYSTEM_PROMPT),
            ("human", IMAGE_SELECT_HUMAN_TEMPLATE),
        ]
    )
