"""知识库接口（原型 05 的第 2 / 3 / 5 / 6 / 7 / 8 屏）。

| 方法 | 路径 | 屏 |
|---|---|---|
| `POST` | `/kb` | 05·6 新建知识库（本期不单独出屏，由「我的知识库」的重命名/默认库承载） |
| `GET` | `/kb` | 05·5 知识库列表 |
| `GET` | `/kb/{kb_id}` | 05·7 知识库详情 / 05·3 解析进度轮询 |
| `PATCH` | `/kb/{kb_id}` | 05·7 改名 / 改描述 |
| `DELETE` | `/kb/{kb_id}` | 05·7 删库 |
| `POST` | `/kb/documents` | 05·2 上传文档 |
| `POST` | `/kb/documents/{doc_id}/reparse` | 05·3 解析失败后重试 |
| `DELETE` | `/kb/documents/{doc_id}` | 05·7 删文档 |

## 两个贯穿全部端点的约定

**1. 越权与不存在返回同一个 4005。** 每个按标识访问的端点都在服务层
`_own_base()` / `_own_document()` 里做归属判断，两者拿到的是同一句
「内容不存在或已删除」。路由层不做任何额外的存在性检查 —— 那正是把
「这个 id 存不存在」泄漏出去的最短路径。

**2. 上传的 `kb_id` 是可选表单字段，不是路径参数。** 大厅那个「上传文档」入口
不知道任何库 id，它需要落到「默认库」上（design D16）。放进路径
（`/kb/{kb_id}/documents`）就没有表达「不指定」的位置了。

## 为什么全是同步 `def`

与既有路由一致：整条链路（鉴权、落库、`session_scope`）都是同步的，用 `async def`
反而会把阻塞调用塞进事件循环。FastAPI 会把同步路由丢进线程池。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Path, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.exceptions import invalid_param
from app.core.response import ok
from app.models.kb import KbCreateRequest, KbUpdateRequest
from app.services import kb_service

router = APIRouter(prefix="/kb", tags=["kb"])

#: 路径参数。`ge=1` 让 `0` / 负数在进入业务层之前就被挡成 4000 ——
#: 否则它会被当成「一个不存在的 id」而报 4005，掩盖掉「id 写错了」这件事
#: （与 `users.py` 的 `AttemptId` 同一条理由）。
KbId = Annotated[int, Path(ge=1)]
DocId = Annotated[int, Path(ge=1)]


# -----------------------------------------------------------------------------
# 库
# -----------------------------------------------------------------------------
@router.post("", summary="新建知识库")
def create_base(payload: KbCreateRequest, user: CurrentUser, session: DbSession) -> dict:
    """建一个知识库（05·6）。

    名字在同一用户下唯一；重名报 4001 而不是「静默用已有的那个」——
    用户说了「新建」，回一份别的东西会让他以为名字被改了。
    """
    item = kb_service.create_base(
        session, user, name=payload.name, description=payload.description
    )
    return ok(item.model_dump(mode="json"))


@router.get("", summary="知识库列表")
def list_bases(user: CurrentUser, session: DbSession) -> dict:
    """我的知识库（05·5）。

    `ready_count` 是「能不能出题」的判据：它为零的库在前端置灰
    （原型 05·5 的批注「未就绪的库不允许出题」，见 design D17）。
    """
    return ok(kb_service.list_bases(session, user).model_dump(mode="json"))


@router.get("/{kb_id}", summary="知识库详情")
def read_base(kb_id: KbId, user: CurrentUser, session: DbSession) -> dict:
    """库 + 它的全部文档（05·7），也是解析进度页轮询的那一个（05·3）。

    **轮询间隔由上传/重试的响应给出**（`poll_interval_ms`），不由前端写死。
    """
    payload = kb_service.base_detail(session, user, kb_id)
    return ok(payload.model_dump(mode="json"))


@router.patch("/{kb_id}", summary="改名 / 改描述")
def update_base(
    kb_id: KbId, payload: KbUpdateRequest, user: CurrentUser, session: DbSession
) -> dict:
    """只提交要改的字段。两个都不给会被请求契约挡成 4000。

    为什么不留「空 PATCH = 什么都没改也算成功」：那与改成功在客户端看起来
    一模一样，而用户明明改过东西 —— 这类「提交了但没生效」最难被发现。
    """
    item = kb_service.update_base(
        session, user, kb_id, name=payload.name, description=payload.description
    )
    return ok(item.model_dump(mode="json"))


@router.delete("/{kb_id}", summary="删除知识库")
def delete_base(kb_id: KbId, user: CurrentUser, session: DbSession) -> dict:
    """删库：库、全部文档、全部向量、全部原文件一起清（spec 的硬要求）。

    只删记录不删向量的症状是「删掉的内容还会出现在题目里」，所以
    向量的清理在服务层是必做的一步（失败只记日志，见 `kb_service`）。
    """
    payload = kb_service.delete_base(session, user, kb_id)
    return ok(payload.model_dump(mode="json"))


# -----------------------------------------------------------------------------
# 文档
# -----------------------------------------------------------------------------
@router.post("/documents", summary="上传文档")
def upload_document(
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(description="PDF / .docx / .md / .txt")],
    #: 客户端给的**原始文件名**。不走 multipart 的 filename：
    #: `Taro.uploadFile` 只会把临时路径的最后一段当它（微信端是随机临时名）。
    filename: Annotated[str, Form()] = "",
    #: 不传则落到「默认库」（大厅入口不知道任何库 id，见 design D16）
    kb_id: Annotated[str | None, Form()] = None,
) -> dict:
    """接收一份文档并立刻返回（05·2）。

    **立刻返回**是刻意的（spec）：解析进后台线程池，状态由
    `GET /kb/{kb_id}` 轮询。这里不做任何解析，所以候选文件再大也不会
    把请求拖到小程序 60 秒的上限上。

    读取按 `上限 + 1` 字节截断：多读 1 字节就足以判定超限，
    不必把一个 1 GB 的垃圾先全量读进内存（同 `POST /users/me/avatar`）。
    """
    settings = get_settings()
    limit = max(1, int(settings.kb_doc_max_bytes))
    data = file.file.read(limit + 1)

    payload = kb_service.upload_document(
        session,
        user,
        filename=filename or (file.filename or ""),
        data=data,
        kb_id=_parse_kb_id(kb_id),
    )
    return ok(payload.model_dump(mode="json"))


@router.post("/documents/{doc_id}/reparse", summary="重新解析")
def reparse_document(doc_id: DocId, user: CurrentUser, session: DbSession) -> dict:
    """重试解析（05·3 的失败态按钮）。

    它是**唯一**的恢复手段：进程重启遗留的「解析中」、上游抖动导致的失败、
    用户把文件改好之后的重试，都走这一条。所以服务层不限制当前状态。
    """
    payload = kb_service.reparse_document(session, user, doc_id)
    return ok(payload.model_dump(mode="json"))


@router.delete("/documents/{doc_id}", summary="删除文档")
def delete_document(doc_id: DocId, user: CurrentUser, session: DbSession) -> dict:
    """删一份文档：记录 + 向量 + 原文件。"""
    payload = kb_service.delete_document(session, user, doc_id)
    return ok(payload.model_dump(mode="json"))


def _parse_kb_id(raw: str | None) -> int | None:
    """把表单里的 `kb_id` 转成 int。

    ⚠️ multipart 的字段一律是**字符串**，所以「`kb_id=abc`」这种情况只能在这里挡。
    它得报 **4000**，报别的两个都会把用户带偏：

    * **不能静默当成 `None`** —— 那会悄悄落到默认库上，而用户以为自己传到指定库了；
    * **不能报 4002** —— 4002 是「上传文件不合规」，前端据此提示的是「换一个文件」，
      可文件本身完全没问题，用户会白折腾一轮；
    * **不能报 4005** —— 那是「内容不存在或已删除」，而这里根本没有一个「不存在的东西」。

    所以按「请求参数有误」拒绝，并把该传什么写进文案。
    """
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if not text.isdigit() or int(text) < 1:
        raise invalid_param("kb_id 必须是正整数")
    return int(text)
