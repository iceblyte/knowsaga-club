"""私有知识库的请求 / 响应契约（原型 05 的第 2–8 屏）。

| 屏 | 接口 | 本文件的契约 |
|---|---|---|
| 05·2 上传文档 | `POST /kb/documents` | `KbDocumentEnvelope` |
| 05·3 文档解析中 | `GET /kb/{kb_id}`（轮询） | `KbBaseDetailResponse` |
| 05·5 知识库列表 | `GET /kb` | `KbListResponse` |
| 05·7 知识库详情 | `GET /kb/{kb_id}` | `KbBaseDetailResponse` |
| 05·8 从知识库出题 | `POST /quiz/generate`（带 `kb_id`） | 契约在 `models/quiz.py` |

## 解析状态是闭集，四态文案不由后端下发

`status`（`pending` / `parsing` / `ready` / `failed`）与档案页的 `state` 同一条约定：
**静态界面用语归前端** `constants/copy.ts`，后端只给状态值。
例外是 `error_message` —— 它是**随数据变化**的叙述（spec 要求「面向用户的一句话，
与面向排查的细节分开存放」），所以由后端给，且保证是可展示的句子，
不会是堆栈或上游报文。

## 计数挂在库上，不挂在文档上

`document_count` / `ready_count` 是列表页那两行文案的来源，也是「这个库能不能出题」
的唯一判据（原型 05·5：「未就绪的库不允许出题」）。由后端算，而不是让前端
把整份文档列表拉下来自己数 —— 库里有 100 份文档时那是 100 条没用的传输。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, model_validator

from app.core.constants import (
    KB_DESCRIPTION_MAX_LEN,
    KB_NAME_MIN_LEN,
    KB_NAME_UI_MAX_LEN,
)
from app.models.common import UtcDatetime

#: 文档的解析状态（spec「解析状态是显式状态机」）。**只有 `ready` 参与检索。**
KbDocStatus = Literal["pending", "parsing", "ready", "failed"]

#: 库名：去首尾空白后 2–40 字。下限不是洁癖 —— 单字库名在列表里与图标糊在一起，
#: 用户在「从哪个库出题」那一步几乎分不出来。
KbName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=KB_NAME_MIN_LEN, max_length=KB_NAME_UI_MAX_LEN
    ),
]

#: 用途描述（可空串）。它与库名一起参与出题语义，所以允许 255 字的空间。
KbDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=KB_DESCRIPTION_MAX_LEN)
]


# -----------------------------------------------------------------------------
# 文档
# -----------------------------------------------------------------------------
class KbDocumentItem(BaseModel):
    """一份文档在界面上的全部信息。"""

    #: 字符串形式的数据库主键 —— 与卷轴 / 题目 id 的约定一致（前端当 key 用）
    id: str
    kb_id: str
    #: 客户端给的**原始**文件名（`机器学习导论.pdf`），不是服务端的落盘名
    filename: str
    #: 小写扩展名**不带点**（`pdf` / `docx` / `md` / `txt`）。
    #: 与 `knowledge_documents.ext` 的列注释同一口径；落盘路径拼接时才补点
    #: （`{doc_id}.{ext}`），这样库里的值不需要每次现剥一个 `.`
    ext: str
    size_bytes: int
    status: KbDocStatus
    #: 入库片段数；仅 `ready` 时非零
    chunk_count: int
    #: 页数（PDF 才有）；不适用时为 0 —— 界面据此决定要不要显示「共 N 页」
    page_count: int
    #: 失败原因的一句话；非失败态为空串
    error_message: str = ""
    created_at: UtcDatetime
    #: 解析结束（成功或失败）的时刻；解析中为 `None`
    parsed_at: UtcDatetime | None = None


# -----------------------------------------------------------------------------
# 库
# -----------------------------------------------------------------------------
class KbBaseItem(BaseModel):
    """一个知识库在列表 / 详情页头部的样子。"""

    id: str
    name: str
    description: str = ""
    #: 全部文档数（含解析中与失败的）
    document_count: int
    #: 已就绪文档数。「能不能出题」看它 —— 原型 05·5 的「未就绪不允许出题」
    ready_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class KbListResponse(BaseModel):
    """`GET /kb`。恒返回全部库（不分页）：一个用户手上的资料库是「个位数」。"""

    total: int
    items: list[KbBaseItem]


class KbBaseDetailResponse(BaseModel):
    """`GET /kb/{kb_id}`：库本身 + 它的全部文档。

    文档列表**不分页**：库的文档数上限由 `kb_max_docs_per_base`（默认 100）卡住，
    一屏拉完比「翻页找那份还没解析好的文档」更符合解析进度页的用法。
    这也是解析进度页轮询的接口 —— 它要看到的是一个整体状态，而不是某一页。
    """

    base: KbBaseItem
    documents: list[KbDocumentItem]


# -----------------------------------------------------------------------------
# 写操作
# -----------------------------------------------------------------------------
class KbCreateRequest(BaseModel):
    """`POST /kb`。"""

    name: KbName
    description: KbDescription = ""


class KbUpdateRequest(BaseModel):
    """`PATCH /kb/{kb_id}`：改名 / 改描述，两个字段都可选。

    ⚠️ **两个都不给直接判 4000**，而不是「静默成功」：一个什么都没改的 PATCH
    在客户端看起来与改成功一模一样，而用户明明改过东西 —— 这类「提交了但没生效」
    最难被发现。
    """

    name: KbName | None = None
    description: KbDescription | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> KbUpdateRequest:
        if self.name is None and self.description is None:
            raise ValueError("至少要提供 name 或 description 之一")
        return self


class KbDocumentEnvelope(BaseModel):
    """上传 / 重新解析的返回。

    带上 `poll_interval_ms` 而不是让前端写死：轮询节奏由后端配置决定
    （原型 05·3 写的是 8 秒，本期取 2 秒，见 design 的偏离登记表），
    前端只负责照这个数字轮询。
    """

    document: KbDocumentItem
    poll_interval_ms: int


class KbBaseDeleteResponse(BaseModel):
    """`DELETE /kb/{kb_id}`。"""

    kb_id: str


class KbDocumentDeleteResponse(BaseModel):
    """`DELETE /kb/documents/{doc_id}`。"""

    doc_id: str
    kb_id: str

