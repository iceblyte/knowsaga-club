"""知识库接口 `/api/v1/kb*` 的接口测试。

覆盖：
- 库的建 / 列 / 详情（含文档）/ 改名 / 删库
- 上传（四种格式的准入、体积上限、文件名缺失、`kb_id` 表单字段）
- 删文档
- **越权与不存在返回同一个 4005**（spec 的硬要求：不为越权单独给信号）
- 4002 的文案必须是为文档写的，不能是头像那一句
  （`exceptions.upload_invalid` 的默认文案是「头像不合规，请换一张图片」，
  这条用例就是钉住「调用方必须显式传 message」）
- 全部端点未登录 → 401

## 为什么每条用例都带 `kb_harness`

`db_client` 只覆盖 `get_db`，而解析走的是**后台线程自己的会话**
（`kb_service._open_session`）。不换掉它，这里每一次上传都会真的往业务库
写几行 —— 而接口测试照样全绿。所以本模块用一条 autouse 夹具把
`kb_harness`（会话 + 假向量化 + 开关）整组拉进来。

## 为什么用 `kb_inline_parse`

解析在**本线程**执行，`POST /kb/documents` 返回时状态已经是终态。
真起线程的路径由 `test_kb_service.py` 单独覆盖 —— 接口层要验的是
「请求形状与响应形状」，不是线程调度。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.constants import KB_DEFAULT_NAME
from app.core.exceptions import ErrorCode

KB = "/api/v1/kb"
DOCS = f"{KB}/documents"

#: 一份合法的 Markdown 原文。长度要够切出片段（`kb_chunk_size` 默认 500），
#: 但更重要的是它非空 —— 空正文会被判成解析失败（spec）。
MD_TEXT = "# 监督学习\n\n" + "监督学习是从标注数据中学习映射函数。" * 12
MD_BYTES = MD_TEXT.encode("utf-8")


@pytest.fixture(autouse=True)
def _kb(kb_harness, kb_inline_parse):  # noqa: ANN001, ANN201, ARG001
    """本文件里每条用例都在「知识库已开启 + 解析同步 + 假向量化」的环境里跑。"""
    return kb_harness


# -----------------------------------------------------------------------------
# 小工具
# -----------------------------------------------------------------------------
def _create(client: TestClient, headers: dict, name: str = "机器学习", **extra) -> dict:  # noqa: ANN003
    resp = client.post(KB, headers=headers, json={"name": name, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _upload(
    client: TestClient,
    headers: dict,
    *,
    filename: str = "讲义.md",
    content: bytes = MD_BYTES,
    form_filename: str | None = None,
    kb_id: int | str | None = None,
    mime: str = "text/markdown",
):
    """发一次上传请求。

    `form_filename` 不传则与 multipart 的 filename 一致（真实客户端的做法：
    显式表单字段 + 文件本身都带名字）。传空串用于验「文件名缺失」。
    """
    data: dict[str, str] = {"filename": filename if form_filename is None else form_filename}
    if kb_id is not None:
        data["kb_id"] = str(kb_id)
    return client.post(
        DOCS, headers=headers, data=data, files={"file": (filename, content, mime)}
    )


def _document_in(
    client: TestClient, headers: dict, kb_id: int | str, doc_id: str
) -> dict:
    """从 `GET /kb/{kb_id}`（也就是前端轮询的那个接口）里取出一份文档。"""
    detail = client.get(f"{KB}/{kb_id}", headers=headers).json()["data"]
    for item in detail["documents"]:
        if item["id"] == doc_id:
            return item
    raise AssertionError(f"库 {kb_id} 里没有文档 {doc_id}：{detail}")


# -----------------------------------------------------------------------------
# 库
# -----------------------------------------------------------------------------
def test_create_then_list(db_client: TestClient, auth_headers: dict) -> None:
    created = _create(db_client, auth_headers, "线性代数", description="教材与习题")

    assert created["name"] == "线性代数"
    assert created["description"] == "教材与习题"
    assert created["document_count"] == 0
    assert created["ready_count"] == 0

    listed = db_client.get(KB, headers=auth_headers).json()["data"]
    assert listed["total"] == 1
    assert [item["id"] for item in listed["items"]] == [created["id"]]


def test_create_rejects_duplicate_name(
    db_client: TestClient, auth_headers: dict
) -> None:
    """重名报 4001，**不**静默返回已有的那个 —— 用户说了「新建」。"""
    _create(db_client, auth_headers, "机器学习")

    resp = db_client.post(KB, headers=auth_headers, json={"name": "机器学习"})

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_INPUT == 4001


@pytest.mark.parametrize("name", ["", " ", "x"])
def test_create_rejects_bad_name(
    db_client: TestClient, auth_headers: dict, name: str
) -> None:
    """库名有 2–40 字的下限（`KB_NAME_MIN_LEN`），单字库名在列表里分不出来。"""
    resp = db_client.post(KB, headers=auth_headers, json={"name": name})

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_update_name_and_description(
    db_client: TestClient, auth_headers: dict
) -> None:
    base = _create(db_client, auth_headers, "旧名字")

    resp = db_client.patch(
        f"{KB}/{base['id']}",
        headers=auth_headers,
        json={"name": "新名字", "description": "换了用途"},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "新名字"
    assert data["description"] == "换了用途"
    # 改完再读一次，确认真的落库了（不是只在响应里改）
    again = db_client.get(f"{KB}/{base['id']}", headers=auth_headers).json()["data"]["base"]
    assert again["name"] == "新名字"


def test_update_with_empty_body_is_rejected(
    db_client: TestClient, auth_headers: dict
) -> None:
    """空 PATCH 报 4000 而不是「成功了但什么都没改」——后者客户端看不出来。"""
    base = _create(db_client, auth_headers)

    resp = db_client.patch(f"{KB}/{base['id']}", headers=auth_headers, json={})

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_delete_base(db_client: TestClient, auth_headers: dict) -> None:
    base = _create(db_client, auth_headers)

    resp = db_client.delete(f"{KB}/{base['id']}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["kb_id"] == base["id"]
    assert db_client.get(KB, headers=auth_headers).json()["data"]["total"] == 0
    assert db_client.get(f"{KB}/{base['id']}", headers=auth_headers).status_code == 404


def test_path_id_must_be_positive(db_client: TestClient, auth_headers: dict) -> None:
    """`0` / 负数在进业务层之前就报 4000 —— 否则会被当成「不存在的 id」报 4005。"""
    resp = db_client.get(f"{KB}/0", headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


# -----------------------------------------------------------------------------
# 上传
# -----------------------------------------------------------------------------
def test_upload_returns_document_and_poll_interval(
    db_client: TestClient, auth_headers: dict, _kb  # noqa: ANN001
) -> None:
    """上传**立刻**返回，状态是「尚未就绪」，终态由轮询接口给出。

    ⚠️ 这里刻意**不**断言响应里是 `ready`。响应是调用前的快照：
    `_envelope()` 用的是请求会话里那个对象，而解析线程写在**另一个连接**上，
    快照不会跟着变（实测拿到的是 `pending`）。这正是接口要表达的语义 ——
    「先给你一个标识，去轮询」。所以状态断言分两半：响应只保证「未就绪」，
    `GET /kb/{kb_id}` 才保证「已就绪 + 有片段」。
    """
    base = _create(db_client, auth_headers)

    resp = _upload(db_client, auth_headers, kb_id=int(base["id"]))

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    doc = data["document"]
    assert doc["filename"] == "讲义.md"
    assert doc["ext"] == "md"
    assert doc["kb_id"] == base["id"]
    assert doc["size_bytes"] == len(MD_BYTES)
    assert doc["status"] in ("pending", "parsing"), doc
    # 轮询节奏由后端下发，前端不写死
    assert data["poll_interval_ms"] == int(_kb.kb_doc_poll_interval_ms)

    polled = _document_in(db_client, auth_headers, base["id"], doc["id"])
    assert polled["status"] == "ready", polled
    assert polled["chunk_count"] > 0
    assert polled["parsed_at"] is not None


def test_upload_shows_up_in_base_detail(
    db_client: TestClient, auth_headers: dict
) -> None:
    base = _create(db_client, auth_headers)
    doc = _upload(db_client, auth_headers, kb_id=int(base["id"])).json()["data"]["document"]

    detail = db_client.get(f"{KB}/{base['id']}", headers=auth_headers).json()["data"]

    assert [d["id"] for d in detail["documents"]] == [doc["id"]]
    assert detail["base"]["document_count"] == 1
    assert detail["base"]["ready_count"] == 1


def test_upload_without_kb_id_lands_in_default_base(
    db_client: TestClient, auth_headers: dict
) -> None:
    """大厅那个入口不知道任何库 id —— 它必须落到「默认库」而不是新建一个。"""
    first = _upload(db_client, auth_headers).json()["data"]["document"]
    second = _upload(db_client, auth_headers, filename="第二份.md").json()["data"]["document"]

    assert first["kb_id"] == second["kb_id"]

    listed = db_client.get(KB, headers=auth_headers).json()["data"]
    assert listed["total"] == 1, "两次上传不该建出两个库"
    assert listed["items"][0]["name"] == KB_DEFAULT_NAME
    assert listed["items"][0]["document_count"] == 2


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("表格.xlsx", "application/vnd.ms-excel"),
        ("压缩包.zip", "application/zip"),
        ("旧文档.doc", "application/msword"),
        ("图片.png", "image/png"),
        ("没有扩展名", "application/octet-stream"),
    ],
)
def test_upload_rejects_unsupported_format(
    db_client: TestClient, auth_headers: dict, filename: str, mime: str
) -> None:
    """不支持的格式**在接收之前**就被拒，且不产生任何文档记录。"""
    resp = _upload(db_client, auth_headers, filename=filename, mime=mime)

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == ErrorCode.UPLOAD_INVALID == 4002
    # 文案必须是**为文档写的**（4002 的默认文案是头像那句）
    assert "头像" not in body["message"], body["message"]
    assert "PDF" in body["message"], body["message"]
    assert db_client.get(KB, headers=auth_headers).json()["data"]["total"] == 0


def test_upload_rejects_missing_filename(
    db_client: TestClient, auth_headers: dict
) -> None:
    """spec：「文件名缺失或非法 → 拒绝，而不是回落按 MIME 类型猜测」。"""
    resp = _upload(db_client, auth_headers, form_filename="   ")

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.UPLOAD_INVALID
    assert "头像" not in resp.json()["message"]


def test_upload_rejects_oversized(
    db_client: TestClient, auth_headers: dict, kb_env  # noqa: ANN001
) -> None:
    """把上限压到 10 字节：超限拒绝，且文案里给出上限。"""
    kb_env(kb_doc_max_bytes=10)
    base = _create(db_client, auth_headers)

    resp = _upload(db_client, auth_headers, kb_id=int(base["id"]))

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == ErrorCode.UPLOAD_INVALID
    assert "头像" not in body["message"], body["message"]
    assert "上限" in body["message"], body["message"]
    # 记录也没落
    detail = db_client.get(f"{KB}/{base['id']}", headers=auth_headers).json()["data"]
    assert detail["documents"] == []


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "1.5"])
def test_upload_rejects_bad_kb_id_form_field(
    db_client: TestClient, auth_headers: dict, raw: str
) -> None:
    """`kb_id` 表单字段非数字 → 4000。

    ⚠️ 不能静默当成 `None`（那会悄悄落到默认库上），也不能报 4002
    （前端会提示「换一个文件」，而文件完全没问题）。
    """
    resp = _upload(db_client, auth_headers, kb_id=raw)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM == 4000


def test_upload_to_unknown_base_returns_4005(
    db_client: TestClient, auth_headers: dict
) -> None:
    resp = _upload(db_client, auth_headers, kb_id=999999)

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND == 4005


# -----------------------------------------------------------------------------
# 重新解析
# -----------------------------------------------------------------------------
def test_reparse_resets_status(db_client: TestClient, auth_headers: dict) -> None:
    """重试是**唯一**的恢复手段（进程重启遗留的「解析中」也走它）。

    所以服务层不限制当前状态 —— 一条已就绪的文档重新解析必须照常走完。
    重试是用户的一次明确动作，响应里**立刻**是「解析中」（不是退回「等待解析」
    再等几百毫秒），终态同样由轮询接口给出。
    """
    doc = _upload(db_client, auth_headers).json()["data"]["document"]

    resp = db_client.post(f"{DOCS}/{doc['id']}/reparse", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["document"]["id"] == doc["id"]
    assert data["document"]["status"] == "parsing", data
    assert "poll_interval_ms" in data

    polled = _document_in(db_client, auth_headers, int(doc["kb_id"]), doc["id"])
    assert polled["status"] == "ready", polled
    assert polled["chunk_count"] > 0


def test_reparse_unknown_document_returns_4005(
    db_client: TestClient, auth_headers: dict
) -> None:
    resp = db_client.post(f"{DOCS}/999999/reparse", headers=auth_headers)

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


# -----------------------------------------------------------------------------
# 删文档
# -----------------------------------------------------------------------------
def test_delete_document(db_client: TestClient, auth_headers: dict) -> None:
    base = _create(db_client, auth_headers)
    doc = _upload(db_client, auth_headers, kb_id=int(base["id"])).json()["data"]["document"]

    resp = db_client.delete(f"{DOCS}/{doc['id']}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["doc_id"] == doc["id"]
    assert data["kb_id"] == base["id"]

    detail = db_client.get(f"{KB}/{base['id']}", headers=auth_headers).json()["data"]
    assert detail["documents"] == []
    assert detail["base"]["ready_count"] == 0


def test_delete_unknown_document_returns_4005(
    db_client: TestClient, auth_headers: dict
) -> None:
    resp = db_client.delete(f"{DOCS}/999999", headers=auth_headers)

    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


# -----------------------------------------------------------------------------
# 隔离：越权与不存在必须逐位一致
# -----------------------------------------------------------------------------
def test_other_user_cannot_see_or_touch_my_base(
    db_client: TestClient, auth_headers: dict, other_auth_headers: dict
) -> None:
    """spec：「四种请求都返回与『该知识库不存在』完全相同的结果」。"""
    base = _create(db_client, auth_headers, "私密资料")

    probes = [
        db_client.get(f"{KB}/{base['id']}", headers=other_auth_headers),
        db_client.patch(
            f"{KB}/{base['id']}", headers=other_auth_headers, json={"name": "改名"}
        ),
        db_client.delete(f"{KB}/{base['id']}", headers=other_auth_headers),
        _upload(db_client, other_auth_headers, kb_id=int(base["id"])),
    ]

    for resp in probes:
        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND

    # 我的库毫发无损
    detail = db_client.get(f"{KB}/{base['id']}", headers=auth_headers).json()["data"]
    assert detail["base"]["name"] == "私密资料"
    assert detail["documents"] == []


def test_forbidden_and_missing_are_indistinguishable(
    db_client: TestClient, auth_headers: dict, other_auth_headers: dict
) -> None:
    """**这是本文件最重要的一条。**

    「别人的真实 id」与「根本不存在的 id」必须给出逐字节相同的响应 ——
    只要有一处不同，攻击者就能靠枚举 id 探测「这条数据是否存在」。
    所以比的是完整响应体，不是只比 code。
    """
    other_base = _create(db_client, other_auth_headers, "别人的库")

    forbidden = db_client.get(f"{KB}/{other_base['id']}", headers=auth_headers)
    missing = db_client.get(f"{KB}/987654", headers=auth_headers)

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()


def test_other_user_cannot_see_my_document(
    db_client: TestClient, auth_headers: dict, other_auth_headers: dict
) -> None:
    doc = _upload(db_client, auth_headers).json()["data"]["document"]

    forbidden = db_client.delete(f"{DOCS}/{doc['id']}", headers=other_auth_headers)
    missing = db_client.delete(f"{DOCS}/987654", headers=other_auth_headers)

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()

    # 我的文档还在
    listed = db_client.get(KB, headers=auth_headers).json()["data"]
    assert listed["items"][0]["document_count"] == 1
    assert doc["id"]


def test_base_list_is_per_user(
    db_client: TestClient, auth_headers: dict, other_auth_headers: dict
) -> None:
    _create(db_client, auth_headers, "我的库")
    _create(db_client, other_auth_headers, "别人的库")

    mine = db_client.get(KB, headers=auth_headers).json()["data"]
    theirs = db_client.get(KB, headers=other_auth_headers).json()["data"]

    assert [item["name"] for item in mine["items"]] == ["我的库"]
    assert [item["name"] for item in theirs["items"]] == ["别人的库"]


# -----------------------------------------------------------------------------
# 鉴权
# -----------------------------------------------------------------------------
def test_every_endpoint_requires_auth(db_client: TestClient) -> None:
    calls = [
        ("get", KB, None),
        ("post", KB, {"json": {"name": "无鉴权"}}),
        ("get", f"{KB}/1", None),
        ("patch", f"{KB}/1", {"json": {"name": "无鉴权"}}),
        ("delete", f"{KB}/1", None),
        ("post", DOCS, {"files": {"file": ("a.md", MD_BYTES, "text/markdown")}}),
        ("post", f"{DOCS}/1/reparse", None),
        ("delete", f"{DOCS}/1", None),
    ]

    for method, url, kwargs in calls:
        resp = getattr(db_client, method)(url, **(kwargs or {}))
        assert resp.status_code == 401, f"{method.upper()} {url} → {resp.status_code}"
