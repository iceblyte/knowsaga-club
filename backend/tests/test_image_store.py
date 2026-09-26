"""COS 转存（`add-question-image-generation` 第 3 组）。

**上传一律替身**（单测不允许真的往云上传东西）。这里验的是我们自己那部分：
对象键怎么拼、公开地址怎么拼、凭据不全时是否响亮失败。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.llm.image import store


class _FakeCosClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    def put_object(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"ETag": '"abc"'}


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    from app.core.config import get_settings

    baseline = {
        "COS_SECRET_ID": "AKIDtest",
        "COS_SECRET_KEY": "secret-not-real",
        "COS_REGION": "ap-guangzhou",
        "COS_BUCKET": "knowsaga-1250000000",
    }
    baseline.update(env)
    for key, value in baseline.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


# ---------------------------------------------------------------- 对象键
def test_build_object_key_shape() -> None:
    key = store.build_object_key(run_token="abc123", seq=3, ext=".jpg")

    assert key == "questions/abc123/3.jpg"


def test_build_object_key_sanitizes_token() -> None:
    """键里只允许保守白名单字符，脏字符会让 COS 签名与 URL 都出问题。"""
    key = store.build_object_key(run_token="../../etc/passwd", seq=1, ext=".png")

    assert key == "questions/etcpasswd/1.png"
    assert ".." not in key


def test_build_object_key_accepts_ext_without_dot() -> None:
    assert store.build_object_key(run_token="t", seq=1, ext="png") == "questions/t/1.png"


def test_build_object_key_falls_back_when_token_is_all_unsafe() -> None:
    assert store.build_object_key(run_token="////", seq=2, ext=".jpg") == "questions/run/2.jpg"


# ---------------------------------------------------------------- 公开地址
def test_public_url_uses_default_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, COS_PUBLIC_BASE_URL="")

    assert (
        store.public_url("questions/t/1.jpg", settings)
        == "https://knowsaga-1250000000.cos.ap-guangzhou.myqcloud.com/questions/t/1.jpg"
    )


def test_public_url_uses_custom_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, COS_PUBLIC_BASE_URL="https://img.example.com/")

    assert store.public_url("questions/t/1.jpg", settings) == "https://img.example.com/questions/t/1.jpg"


def test_public_url_raises_without_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, COS_REGION="", COS_PUBLIC_BASE_URL="")

    with pytest.raises(store.ImageStoreError):
        store.public_url("questions/t/1.jpg", settings)


# ---------------------------------------------------------------- 上传
def test_upload_image_returns_permanent_url(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, COS_PUBLIC_BASE_URL="")
    fake = _FakeCosClient()
    monkeypatch.setattr(store, "_build_client", lambda _settings: fake)

    url = store.upload_image(
        b"\xff\xd8\xffdata",
        key="questions/t/1.jpg",
        content_type="image/jpeg",
        settings=settings,
    )

    assert url == "https://knowsaga-1250000000.cos.ap-guangzhou.myqcloud.com/questions/t/1.jpg"
    call = fake.calls[0]
    assert call["Bucket"] == "knowsaga-1250000000"
    assert call["Key"] == "questions/t/1.jpg"
    assert call["Body"] == b"\xff\xd8\xffdata"
    # ContentType 必须显式给：不给的话浏览器可能把它当二进制下载而不是显示
    assert call["ContentType"] == "image/jpeg"


def test_upload_image_raises_when_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, COS_SECRET_KEY="")

    with pytest.raises(store.ImageStoreError) as excinfo:
        store.upload_image(b"data", key="k", content_type="image/png", settings=settings)

    assert "凭据" in str(excinfo.value)


def test_upload_image_rejects_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)

    with pytest.raises(store.ImageStoreError):
        store.upload_image(b"", key="k", content_type="image/png", settings=settings)


def test_upload_image_wraps_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    monkeypatch.setattr(
        store, "_build_client", lambda _settings: _FakeCosClient(error=RuntimeError("AccessDenied"))
    )

    with pytest.raises(store.ImageStoreError) as excinfo:
        store.upload_image(b"data", key="k", content_type="image/png", settings=settings)

    assert "AccessDenied" in str(excinfo.value)


def test_upload_image_does_not_build_client_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """凭据不全时**根本不该构造客户端**（构造也会去要签名，白费一次）。"""
    settings = _settings(monkeypatch, COS_BUCKET="")
    built: list[object] = []
    monkeypatch.setattr(store, "_build_client", lambda s: built.append(s) or _FakeCosClient())

    with pytest.raises(store.ImageStoreError):
        store.upload_image(b"data", key="k", content_type="image/png", settings=settings)

    assert built == []
