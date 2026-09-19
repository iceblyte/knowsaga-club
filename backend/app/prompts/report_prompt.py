"""报告 Prompt（版本化 v1）。

对应 `docs/方案设计文档.md` §8.4–§8.6，并按本项目的实际情况做了**一处收紧**。

## 收紧之处：模型不产出统计数字

§8.6 的示例 JSON 里带回显 `"accuracy": 80`。本项目**刻意不这么做**。

统计数字（正确率 / 答对答错数 / XP / 金币 / 百分位 / 平均用时）由
`app/services/scoring.py` 确定性算出并落在 `attempts` 表上（MVP开发计划 §8.4）。
如果又让模型回显一遍，同一个事实就有了两个来源 —— 模型只要把 4/5 说成 80%
而环上写 85%，用户立刻会看到一份自相矛盾的报告，而且没人能判断该信哪个。

所以这里的契约是：**数字由服务端算好当输入喂进去，模型只负责把它讲成人话。**
Prompt 里明确要求「不要自己重新计算」。契约测试
（`tests/test_report_prompt.py`）会断言 `accuracy` / `xp_gained` 这类字段名
**不出现在 System Prompt 里** —— 它们一旦出现，就说明有人又把统计数字
挪回模型侧了。

## 与数据模型的对应关系

本 Prompt 要求的结构必须能被 `app/models/report.py` 的 `ReportDraft` 校验通过，
两者是同一份契约的两端。改一边必须同步改另一边。

**`mastered_points` / `weak_points` 的上界必须与 `ReportDraft` 一致（当前 5 个）。**
这两个字段一度在 Prompt 里写「1 到 3 个」、在 `ReportDraft` 里写 `max_length=3`，
结果是「5 道题错 4 道」这种**完全正常**的一局里，模型如实给出 4 个薄弱点却被判为
非法草稿，重试几次后整份报告降级成模板 —— 用户看到的是干巴巴的固定话术，
而日志只说「schema_mapping_failed」。改这两个数字时务必两边一起动。

## 为什么 advice 只要 title / body

原型 03「复习建议」屏的三张卡每张都有一个动作按钮，但**动作不是文案问题，
而是事实问题**：有没有错题可重做、错题有没有进复习队列，都是确定性的。
让模型决定「建议用户重做第 3 题」而实际上第 3 题答对了，就是一份假报告。
所以模型只写标题与正文，`action` 由 `services/report_service.py` 按真实事实挂上。

## 为什么没有 share_quote（分享金句）

`docs/方案设计文档.md` §8.4/§8.6 的 Report 契约里有一个 `share_quote`
（用于「分享海报」屏的金句）。本期**刻意不产出它**，原因有两条：

1. 海报功能已明确移出本期（MVP开发计划 §3.2：调 `getwxacodeunlimit` 需要
   AppID + AppSecret，本期不做），金句因此**没有任何消费方**；
2. `reports` 表里也没有对应的列。为一句没人看的话去改已建好的表结构
   （还要处理「迁移工具首个版本标记基线」的问题）不划算。

等海报功能落地时，把「加列 + 加 Prompt 字段」一起做 —— 两者本来就必须同时改，
分开做只会多一次 schema 变更。这条记在遗留清单里。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

REPORT_PROMPT_VERSION = "v1"

#: 三句话知识总结 —— 恰好 3 条（原型 03 第 2 屏）
REPORT_SUMMARY_LINES = 3

#: 复习建议 —— 恰好 3 条（原型 03 第 3 屏三张卡）
REPORT_ADVICE_COUNT = 3

# -----------------------------------------------------------------------------
# System Prompt
# -----------------------------------------------------------------------------
REPORT_SYSTEM_PROMPT = """你是一名学习复盘教练，为学习产品「知拾冒险社」的冒险者写一份本次闯关的复盘报告。

## 一、输出格式（最高优先级，必须严格遵守）

你必须**只输出一个 json 对象**，不要输出任何其他内容：不要开场白、不要总结、
不要解释你的思路、不要用 ```json 代码块包裹。你的整条回复必须是一个
可以直接被 json.loads() 解析的 json 字符串。

json 对象的结构必须严格如下，字段名一字不差：

{
  "mastered_points": ["RAG 基本定义", "向量检索"],
  "weak_points": ["RAG 与搜索引擎的边界"],
  "three_line_summary": [
    "RAG 等于「检索 + 生成」，先找到资料再让模型作答。",
    "向量检索靠语义相似度，所以能匹配同义表达。",
    "它的最大价值在私有文档场景，而不是替代通用搜索。"
  ],
  "advice": [
    {
      "title": "重做第 3 题",
      "body": "你在「RAG 与搜索引擎的边界」上答错了，这是本次唯一的失分点。"
    },
    {
      "title": "3 天后自动提醒复习",
      "body": "已按遗忘曲线为你排入「旧识重温」关卡。"
    },
    {
      "title": "继续下一张卷轴",
      "body": "建议接着学「RAG 的落地实践」，把这次的概念用到真实场景里。"
    }
  ]
}

## 二、统计数字由系统提供，你不要计算也不要输出

下方「统计结果」里的正确率、答对题数、答错题数、用时、经验值、金币**已经由系统算好了**。
你**不要自己重新计算，也不要把任何数字写进 json 里** —— 判断结论（掌握了什么、
哪里薄弱、下一步做什么）才是你的工作。

## 三、内容要求

- **全部内容使用中文**（专有名词可保留英文原文）。
- `mastered_points`：本次答对题目所对应的知识点标签，最多 5 个。
  答对的题太少时可以少于 5 个，但**不要凭空写出本次没考到的知识点**。
- `weak_points`：本次答错或未作答题目所对应的知识点标签，最多 5 个。
  如果全部答对就返回空数组 `[]`，**不要为了凑数编一个薄弱点出来**。
- `three_line_summary`：恰好 **3 句**知识总结，每句一句话、不超过 40 字，
  适合在手机上快速读完。第 1 句讲这次学的核心是什么，第 2 句讲最容易记混的地方，
  第 3 句讲它在真实场景里怎么用。
- `advice`：恰好 **3 条**建议，每条包含 `title`（12 字以内的小标题）与
  `body`（一到两句话的说明）。建议必须**具体、可执行**，指出下一步做什么，
  **不要空泛的鼓励**（例如「继续加油」「保持热情」这类没有信息量的话）。
- 语气**清晰、鼓励式**，但要基于真实作答情况，**不要编造**没有出现的结论，
  也不要夸大（答错就说答错，不要粉饰）。
- 文案要**精简**，适合移动端阅读；不要用 Markdown 标记、不要用 emoji。
- 不要在文案里提到「统计数据」「系统」「Prompt」这类内部词汇，也不要提到
  「第几题」之外的技术细节 —— 用户看到的是自己的复盘，不是一份分析日志。
"""

# -----------------------------------------------------------------------------
# Human 模板
# -----------------------------------------------------------------------------
REPORT_HUMAN_TEMPLATE = """请为下面这次闯关写复盘报告。

【本次主题】
{topic}

【题库】
{quiz_json}

【答题记录】
{answer_records}

【统计结果】（已由系统算好，直接引用结论即可，不要重新计算）
{score_summary}
"""


def build_report_prompt() -> ChatPromptTemplate:
    """构造报告用的 Prompt 模板。

    输入变量：
        topic: 本次学习的主题（题库标题）
        quiz_json: 题库 JSON（含题干、选项、答案、讲解、知识点）
        answer_records: 逐题作答记录的可读文本
        score_summary: 服务端算好的统计结果文本

    ⚠️ System Prompt 用 `SystemMessage` 对象传入，**不要写成 `("system", 文本)` 元组**。
    理由与 `quiz_prompt.build_quiz_prompt` 完全相同：langchain-core 1.x 的模板默认
    按 f-string 解析，而 System Prompt 里含 JSON 示例（大量花括号），
    走模板解析会直接抛 `ValueError: Invalid format specifier in f-string template`。
    """
    return ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=REPORT_SYSTEM_PROMPT),
            ("human", REPORT_HUMAN_TEMPLATE),
        ]
    )


def render_report_prompt(
    *,
    topic: str,
    quiz_json: str,
    answer_records: str,
    score_summary: str,
) -> list[dict[str, str]]:
    """渲染成可直接发给模型的 messages（便于日志与调试）。"""
    prompt = build_report_prompt()
    rendered = prompt.invoke(
        {
            "topic": topic,
            "quiz_json": quiz_json,
            "answer_records": answer_records,
            "score_summary": score_summary,
        }
    )
    out: list[dict[str, str]] = []
    for message in rendered.messages:
        content: Any = message.content
        if not isinstance(content, str):
            content = str(content)
        out.append({"role": message.type, "content": content})
    return out
