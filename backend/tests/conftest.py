"""pytest 公共夹具。

原则（见 docs/MVP开发计划.md §10）：
- **绝不允许测试发出真实 LLM 请求**，因此所有 LLM 交互都必须能被 mock。
- 测试环境变量通过 monkeypatch 注入，优先级高于仓库根目录的 `.env`，
  保证测试结果不受开发者本地配置影响。
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# 测试基线环境：在导入 app 之前就位
TEST_ENV = {
    "APP_ENV": "dev",
    "APP_VERSION": "0.1.0-test",
    "DEEPSEEK_API_KEY": "sk-test-key-not-real",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "deepseek-flash",
    "DEEPSEEK_THINKING": "false",
    "KNOWLEDGE_SEARCH_ENABLED": "false",
    "LOG_LEVEL": "WARNING",
    "QUIZ_TASK_TTL_SECONDS": "600",
}


@pytest.fixture(scope="session", autouse=True)
def _baseline_env() -> Iterator[None]:
    """会话级基线环境变量，避免读到开发者本地的 .env 造成测试不确定。"""
    original = {k: os.environ.get(k) for k in TEST_ENV}
    os.environ.update(TEST_ENV)
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def settings(_baseline_env: None):  # noqa: ARG001
    """获取配置单例，并清掉 lru_cache 以确保读到的是当前环境变量。"""
    from app.core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clean_task_store() -> Iterator[None]:
    """任务表是**进程内全局状态**，用例之间必须隔离。

    放在 conftest 里而不是各测试文件里，是因为任何走接口的用例都可能悄悄创建任务，
    漏掉一处就会出现「只在全量跑时失败」的串味问题 —— 那种问题最难查。
    """
    from app.services import task_service

    task_service.reset_store()
    yield
    task_service.reset_store()


@pytest.fixture
def inline_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """把异步任务执行替换成同步，让轮询类用例不依赖线程调度。

    只有明确验证「真实线程池路径」的用例才不用它。
    """
    from app.services import quiz_service

    monkeypatch.setattr(quiz_service, "_submit", lambda fn: fn())


@pytest.fixture
def client(settings) -> Iterator[TestClient]:  # noqa: ARG001
    """FastAPI 测试客户端。"""
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


# -----------------------------------------------------------------------------
# 固定样本：一份「3 单选 + 1 多选 + 1 判断」的合法题库
# -----------------------------------------------------------------------------
# 取这个组合有两个原因：
#   1. 它正是原型「副本确认页」的题型构成（3 单选 · 1 多选 · 1 判断）
#   2. 它同时覆盖三种题型的校验分支，且满分恰好 200 XP
#      （40×3 + 60 + 20），与原型通关结算的数字一致
SAMPLE_QUESTIONS: list[dict] = [
    {
        "id": "q1",
        "type": "single",
        "stem": "RAG 的核心思路是什么？",
        "options": [
            {"key": "A", "text": "先检索相关资料，再把资料交给模型生成回答"},
            {"key": "B", "text": "把模型参数调大以获得更多知识"},
            {"key": "C", "text": "只用关键词匹配返回链接列表"},
            {"key": "D", "text": "把全部训练数据重新训练一遍"},
        ],
        "answer": ["A"],
        "explanation": "RAG（检索增强生成）先检索外部资料，再让模型基于资料作答。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "easy",
    },
    {
        "id": "q2",
        "type": "single",
        "stem": "向量检索相比关键词检索，最主要的优势是？",
        "options": [
            {"key": "A", "text": "检索速度一定更快"},
            {"key": "B", "text": "不需要建立索引"},
            {"key": "C", "text": "能按语义相似度召回，而不只是字面匹配"},
            {"key": "D", "text": "结果永远比关键词检索更准"},
        ],
        "answer": ["C"],
        "explanation": "向量检索把文本映射到语义空间，可以召回字面不同但含义相近的内容。",
        "knowledge_point": "向量检索",
        "difficulty": "medium",
    },
    {
        "id": "q3",
        "type": "single",
        "stem": "RAG 与搜索引擎最本质的差别在于？",
        "options": [
            {"key": "A", "text": "RAG 的数据量更大"},
            {"key": "B", "text": "RAG 会基于检索结果组织成连贯回答，搜索引擎返回的是候选链接"},
            {"key": "C", "text": "RAG 只支持中文"},
            {"key": "D", "text": "搜索引擎不能处理长文本"},
        ],
        "answer": ["B"],
        "explanation": "搜索引擎给链接，用户自己读；RAG 把召回内容转写成直接可用的回答。",
        "knowledge_point": "与搜索引擎的边界",
        "difficulty": "medium",
    },
    {
        "id": "q4",
        "type": "multiple",
        "stem": "下面哪些属于 RAG 的典型收益？（多选）",
        "options": [
            {"key": "A", "text": "回答可以引用最新的外部资料"},
            {"key": "B", "text": "可以彻底消除模型幻觉"},
            {"key": "C", "text": "知识可以更新而无需重新训练模型"},
            {"key": "D", "text": "让模型参数量变小"},
        ],
        "answer": ["A", "C"],
        "explanation": "RAG 能引入新资料、免训练更新知识；但它只能降低幻觉，不能彻底消除。",
        "knowledge_point": "应用场景",
        "difficulty": "hard",
    },
    {
        "id": "q5",
        "type": "judge",
        "stem": "RAG 系统必须先完成检索，才能生成最终答案。",
        "options": [
            {"key": "T", "text": "正确"},
            {"key": "F", "text": "错误"},
        ],
        "answer": ["T"],
        "explanation": "RAG 的「检索—增强—生成」顺序是固定的，检索结果就是生成阶段的输入。",
        "knowledge_point": "RAG 基本定义",
        "difficulty": "easy",
    },
]


@pytest.fixture
def sample_questions() -> list[dict]:
    """一份合法题库的题目列表（深拷贝，避免测试间互相污染）。"""
    import copy

    return copy.deepcopy(SAMPLE_QUESTIONS)


@pytest.fixture
def sample_quiz_payload(sample_questions: list[dict]) -> dict:
    """可直接喂给 `Quiz.model_validate()` 的完整题库字典。"""
    return {
        "quiz_id": "quiz_test",
        "title": "RAG 入门闯关",
        "summary": "围绕 RAG 基础概念与应用场景生成的题库",
        "source_type": "text",
        "user_input": "我想学习什么是 RAG，以及它和传统搜索有什么区别",
        "knowledge_points": None,  # 交给 Quiz 从题目派生
        "questions": sample_questions,
    }


@pytest.fixture
def sample_draft_payload(sample_questions: list[dict]) -> dict:
    """LLM 结构化输出的形状（外层的 quiz_id / user_input / source_type 由服务端补）。"""
    return {
        "title": "RAG 入门闯关",
        "summary": "围绕 RAG 基础概念与应用场景生成的题库",
        "knowledge_points": None,
        "questions": sample_questions,
    }
