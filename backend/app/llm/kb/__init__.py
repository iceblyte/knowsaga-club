"""私有知识库（RAG）的实现层。

分层（从下往上，**不反向依赖**）：

| 模块 | 职责 |
|---|---|
| `embedding.py` | 向量化（百炼 `text-embedding-v4`） |
| `splitter.py` | 文本分块 |
| `loaders.py` | 文件 → 纯文本；扩展名准入也在这一层 |
| `store.py` | Chroma 持久化，以及「带隔离过滤的检索」这个唯一入口 |
| `tools.py` | 把检索包成模型可调用的工具（`kb_search`） |

## 为什么本文件不做任何 re-export

`store.py` 会 import `chromadb`（实测 import 耗时 1.31 秒，连带依赖约 198 MB）。
把它挂在包级 `__init__` 上，任何 `import app.llm.kb.splitter` 的调用方
都会顺带把 Chroma 拖起来 —— 而分块是纯字符串处理，与向量库毫无关系。

各模块按需 import 的代价是调用方多写一行，收益是
**`KNOWLEDGE_BASE_ENABLED=false` 的部署完全不加载这 198 MB**。
"""
