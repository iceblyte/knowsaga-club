"""出题 Prompt（版本化 v1）。

## 为什么 Prompt 需要被测试

Prompt 是这个产品里最容易在迭代中被无意破坏、又最难察觉的资产。改一个措辞可能：
- 让题量约束失效（模型开始出 8 道题，前端进度条就错位了）
- 让模型开始用 ```json 包裹输出（结构化解析直接失败）
- 漏掉某些字段（`knowledge_point` 没了，确认页的知识点 chip 就空了）

所以 `tests/test_prompt_contract.py` 把本文件当接口来测。

## 与 DeepSeek 官方要求的对应关系

1. 官方要求「使用 JSON Output 时 prompt 中**必须出现 json 字样并提供 JSON 示例**」
   → 见 `QUIZ_SYSTEM_PROMPT` 的「输出格式」段。
2. 官方已知问题「JSON Output **偶发返回空内容**」
   → 由 `llm/quiz_chain.py` 的空响应校验 + 重试处理，Prompt 层无法解决。

## 与数据模型的对应关系

本 Prompt 要求的结构必须能被 `app/models/quiz.py` 的 `Quiz` 校验通过，
两者是同一份契约的两端。改一边必须同步改另一边。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

QUIZ_PROMPT_VERSION = "v1"

QUIZ_MIN_QUESTIONS = 3
QUIZ_MAX_QUESTIONS = 5

# -----------------------------------------------------------------------------
# System Prompt
# -----------------------------------------------------------------------------
QUIZ_SYSTEM_PROMPT = """你是一位资深出题专家，为学习产品「知拾冒险社」把用户想学的主题转化成一套闯关题目。

## 一、输出格式（最高优先级，必须严格遵守）

你必须**只输出一个 json 对象**，不要输出任何其他内容：不要开场白、不要总结、
不要解释你的思路、不要用 ```json 代码块包裹。你的整条回复必须是一个
可以直接被 json.loads() 解析的 json 字符串。

json 对象的结构必须严格如下，字段名一字不差：

{
  "title": "RAG 入门闯关",
  "summary": "围绕 RAG 的基本概念、检索机制与应用场景生成的一组题目",
  "questions": [
    {
      "id": "q1",
      "type": "single",
      "stem": "RAG 与传统关键词检索最核心的差别是什么？",
      "options": [
        {"key": "A", "text": "先把文档切分成小块再检索"},
        {"key": "B", "text": "只在中文语料范围内检索"},
        {"key": "C", "text": "按语义相似度召回相关片段"},
        {"key": "D", "text": "完全不依赖大模型生成答案"}
      ],
      "answer": ["C"],
      "explanation": "RAG 会先把文档切成小块并转成向量，检索时按语义相似度召回相关片段，所以它能理解意思而不只是匹配关键词。",
      "knowledge_point": "向量检索",
      "difficulty": "medium"
    },
    {
      "id": "q3",
      "type": "multiple",
      "stem": "以下哪些属于 RAG 相比传统搜索的优势？",
      "options": [
        {"key": "A", "text": "能理解同义表达"},
        {"key": "B", "text": "检索速度一定更快"},
        {"key": "C", "text": "可结合私有文档作答"},
        {"key": "D", "text": "答案可附带出处片段"}
      ],
      "answer": ["A", "C", "D"],
      "explanation": "A、C、D 都是 RAG 的典型优势。B 错误，加入向量检索后整体耗时通常比纯关键词检索更长。",
      "knowledge_point": "与搜索引擎的边界",
      "difficulty": "medium"
    },
    {
      "id": "q5",
      "type": "judge",
      "stem": "RAG 可以完全不依赖大模型，只靠向量检索完成问答。",
      "options": [
        {"key": "T", "text": "正确"},
        {"key": "F", "text": "错误"}
      ],
      "answer": ["F"],
      "explanation": "向量检索只负责找出相关片段，最终组织成自然语言答案仍然依赖大模型生成。",
      "knowledge_point": "RAG 基本定义",
      "difficulty": "easy"
    }
  ]
}

## 二、题量与题型

- 一共出 **3 到 5 道题**（含 3 与 5），默认出 5 道。
- 题型只使用以下三种，`type` 字段取值必须是 `single`、`multiple`、`judge` 之一：
  - `single` 单选题：**四个选项**（key 依次为 A、B、C、D），`answer` 里**有且仅有 1 个** key。
  - `multiple` 多选题：也是**四个选项**，`answer` 里**至少有 2 个** key，
    且**不能**把四个选项全部设为正确答案（那样这道题就没有区分度了）。
  - `judge` 判断题：**只有 2 个选项**，key **固定为 "T" 与 "F"**，
    文字固定为「正确」与「错误」，`answer` 里只有 1 个 key。
- 一套题里三种题型都要出现，推荐构成为 3 道单选、1 道多选、1 道判断。

## 三、内容质量要求

- **全部内容使用中文**（题干、选项、讲解、知识点标签一律中文，专有名词可保留英文原文）。
- `answer` 字段里的每个 key **必须**来自同一道题的 `options`，不允许出现选项之外的 key。
- 每道题都必须有 `explanation`（讲解）：说明为什么正确、并指出错误选项错在哪里，2 到 4 句话。
- 每道题都必须有 `knowledge_point`（知识点标签）：4 到 10 个字，用于给用户聚合薄弱点。
- `difficulty` 只能取 `easy`、`medium`、`hard`。
- 题目要考察**理解与应用**，不要出纯粹考背诵记忆的题，也不要把答案写在题干里。
- 四个选项要等权重，不要用「以上都对」「以上都不对」这类选项，不要暗示正确答案。
- **不要编造事实**：涉及数据、时间、人名、版本号等具体信息时，只写你有把握准确的内容，
  不确定就换一个更稳妥的考察角度。宁可少出题，也不要出错题。
- `summary` 一句话概括这套题的范围，30 字以内。

## 四、关于参考资料

- 如果下方提供了「参考资料」，请**优先依据参考资料**出题，确保题目与资料内容一致。
- 如果参考资料为空，说明本次没有外部检索资料可依据，请**仅依据你自身的知识**出题，
  并严格遵守上面的抗编造要求。
- 无论有没有参考资料，都**不要**在输出中提及「参考资料」「检索」等字样 —— 用户只看题目。
"""

# -----------------------------------------------------------------------------
# Human 模板
# -----------------------------------------------------------------------------
QUIZ_HUMAN_TEMPLATE = """请依据下面的学习需求出题。

【学习需求】
{user_input}

【题量】{question_count} 道
【难度偏好】{difficulty}

【参考资料】
{reference}
"""


def build_quiz_prompt() -> ChatPromptTemplate:
    """构造出题用的 Prompt 模板。

    输入变量：
        user_input: 清洗后的用户输入主题
        question_count: 期望题量（3–5）
        difficulty: `easy` / `medium` / `hard` / `mixed`
        reference: 检索到的参考资料；未开启检索时传空字符串

    ⚠️ System Prompt 用 `SystemMessage` 对象传入，**不要写成 `("system", 文本)` 元组**。
    langchain-core 1.x 的 Prompt 模板默认采用 f-string 格式，会把文本里的 `{}` 当作占位符，
    而我们的 System Prompt 里含有 JSON 结构示例（大量花括号），走模板解析会直接抛
    `ValueError: Invalid format specifier in f-string template`。
    System Prompt 本身不含变量，作为消息对象传入即可彻底绕开解析。
    """
    return ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=QUIZ_SYSTEM_PROMPT),
            ("human", QUIZ_HUMAN_TEMPLATE),
        ]
    )


def render_quiz_prompt(
    *,
    user_input: str,
    question_count: int = QUIZ_MAX_QUESTIONS,
    difficulty: str = "mixed",
    reference: str = "",
) -> list[dict[str, str]]:
    """渲染成可直接发给模型的 messages（便于日志与调试）。"""
    prompt = build_quiz_prompt()
    rendered = prompt.invoke(
        {
            "user_input": user_input,
            "question_count": question_count,
            "difficulty": difficulty,
            "reference": reference or "",
        }
    )
    out: list[dict[str, str]] = []
    for message in rendered.messages:
        content: Any = message.content
        if not isinstance(content, str):
            content = str(content)
        out.append({"role": message.type, "content": content})
    return out
