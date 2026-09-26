"""百炼生图调用与图片下载（`add-question-image-generation` 第 3 组）。

**上游一律替身**（红线：测试不允许发出真实 LLM 请求）。这里验的是我们自己那部分：
传了哪些参数、怎么解析响应、怎么把异常归一。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.llm.image import client


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        output: object = None,
        code: str = "",
        message: str = "",
    ) -> None:
        self.status_code = status_code
        self.output = output
        self.code = code
        self.message = message


def _image_output(url: str = "https://dashscope-result.oss-cn-shanghai.aliyuncs.com/a.png") -> dict:
    """官方响应形状（`output.choices[0].message.content[0].image`）。"""
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [{"image": url}],
                },
            }
        ]
    }


class _FakeMultiModalConversation:
    """替身：记录调用参数，返回预设响应。"""

    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response
        self._error = error

    def call(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


@pytest.fixture
def fake_mmc(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """把 `dashscope.MultiModalConversation` 换成替身。

    `_invoke_call` 内部是 `from dashscope import MultiModalConversation`，
    所以替换**模块属性**即可生效，不必改被测代码。
    """
    import dashscope

    def _install(
        response: object | None = None, error: Exception | None = None
    ) -> _FakeMultiModalConversation:
        fake = _FakeMultiModalConversation(response or _FakeResponse(output=_image_output()), error)
        monkeypatch.setattr(dashscope, "MultiModalConversation", fake)
        return fake

    return _install


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    from app.core.config import get_settings

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


# ---------------------------------------------------------------- 参数
def test_invoke_call_passes_expected_parameters(fake_mmc) -> None:  # noqa: ANN001
    """一次调用一张（`n=1`）、显式传尺寸、关掉润色与水印、超时进 HTTP 层。"""
    fake = fake_mmc()

    url = client._invoke_call(
        model="z-image-turbo",
        prompt="一只苹果",
        size="512*512",
        negative_prompt="文字",
        prompt_extend=False,
        watermark=False,
        api_key="sk-fake",
        timeout=20.0,
    )

    assert url == "https://dashscope-result.oss-cn-shanghai.aliyuncs.com/a.png"
    kwargs = fake.calls[0]
    assert kwargs["model"] == "z-image-turbo"
    assert kwargs["n"] == 1, "一次只能带一个 prompt，n>1 会得到同一主题的近似图"
    assert kwargs["size"] == "512*512"
    assert kwargs["prompt_extend"] is False
    assert kwargs["watermark"] is False
    assert kwargs["result_format"] == "message"
    assert kwargs["api_key"] == "sk-fake"
    # 超时走 request_timeout（上游默认 300 秒 = 对出题链而言没有超时）
    assert kwargs["request_timeout"] == 20
    assert kwargs["messages"] == [{"role": "user", "content": [{"text": "一只苹果"}]}]


def test_empty_negative_prompt_is_sent_as_none(fake_mmc) -> None:  # noqa: ANN001
    """空串负向提示词 → 不传（传一个空串是另一种语义）。"""
    fake = fake_mmc()

    client._invoke_call(
        model="m",
        prompt="p",
        size="512*512",
        negative_prompt="   ",
        prompt_extend=False,
        watermark=False,
        api_key="k",
        timeout=5.0,
    )

    assert fake.calls[0]["negative_prompt"] is None


def test_generate_image_url_uses_settings(fake_mmc, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    """配置项应被如实带进调用（改 `.env` 就能改模型与尺寸，代码不动）。"""
    fake = fake_mmc()
    settings = _settings(
        monkeypatch,
        IMAGE_MODEL="qwen-image-plus",
        IMAGE_SIZE="1024*1024",
        IMAGE_TIMEOUT_SECONDS="35",
        IMAGE_NEGATIVE_PROMPT="水印",
        DASHSCOPE_API_KEY="sk-from-env",
    )

    client.generate_image_url("提示词", settings)

    kwargs = fake.calls[0]
    assert kwargs["model"] == "qwen-image-plus"
    assert kwargs["size"] == "1024*1024"
    assert kwargs["request_timeout"] == 35
    assert kwargs["negative_prompt"] == "水印"
    assert kwargs["api_key"] == "sk-from-env"


# ---------------------------------------------------------------- 异常归一
def test_upstream_error_status_raises(fake_mmc) -> None:  # noqa: ANN001
    fake_mmc(
        _FakeResponse(
            status_code=400,
            code="InvalidParameter",
            message="size is invalid",
        )
    )

    with pytest.raises(client.ImageGenError) as excinfo:
        client._invoke_call(
            model="m",
            prompt="p",
            size="512x512",
            negative_prompt="",
            prompt_extend=False,
            watermark=False,
            api_key="k",
            timeout=5.0,
        )

    assert "400" in str(excinfo.value)
    assert "InvalidParameter" in str(excinfo.value)


def test_transport_exception_is_wrapped(fake_mmc) -> None:  # noqa: ANN001
    """网络/超时异常一律归一成 `ImageGenError`，调用方只需要捕一种。"""
    fake_mmc(error=TimeoutError("read timed out"))

    with pytest.raises(client.ImageGenError) as excinfo:
        client._invoke_call(
            model="m",
            prompt="p",
            size="512*512",
            negative_prompt="",
            prompt_extend=False,
            watermark=False,
            api_key="k",
            timeout=5.0,
        )

    assert "TimeoutError" in str(excinfo.value)


# ---------------------------------------------------------------- 响应解析
def test_parse_image_url_happy_path() -> None:
    assert client.parse_image_url(_image_output("https://x/y.png")) == "https://x/y.png"


def test_parse_image_url_skips_non_image_elements() -> None:
    output = {
        "choices": [
            {
                "message": {
                    "content": [{"text": "这里是说明"}, {"image": "https://x/y.png"}],
                }
            }
        ]
    }
    assert client.parse_image_url(output) == "https://x/y.png"


@pytest.mark.parametrize(
    "output",
    [
        None,
        "not-a-dict",
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": []}}]},
        {"choices": [{"message": {"content": [{"text": "只有文字"}]}}]},
    ],
    ids=[
        "not-object",
        "string",
        "no-choices",
        "empty-choices",
        "choice-not-object",
        "no-message",
        "no-content",
        "content-empty",
        "no-image-field",
    ],
)
def test_parse_image_url_rejects_malformed_output(output: object) -> None:
    """上游换结构时必须响亮地失败。

    降级路径**不报错**，所以「结构变了」在界面上只表现为「配图一张都没有」——
    这里抛错是唯一能留下线索的地方。
    """
    with pytest.raises(client.ImageGenError):
        client.parse_image_url(output)


# ---------------------------------------------------------------- 下载
class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes], content_type: str, status_code: int = 200) -> None:
        self._chunks = chunks
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_bytes(self):  # noqa: ANN201
        yield from self._chunks


class _FakeStream:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeStreamResponse:
        return self._response

    def __exit__(self, *_: object) -> None:
        return None


def _patch_stream(monkeypatch: pytest.MonkeyPatch, response: _FakeStreamResponse) -> None:
    monkeypatch.setattr(client.httpx, "stream", lambda *a, **k: _FakeStream(response))


def test_download_image_returns_bytes_and_type(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stream(monkeypatch, _FakeStreamResponse([b"\xff\xd8\xff", b"rest"], "image/jpeg"))

    data, content_type = client.download_image(
        "https://temp/1.jpg", max_bytes=1024, timeout=5.0
    )

    assert data == b"\xff\xd8\xffrest"
    assert content_type == "image/jpeg"


def test_download_image_rejects_non_image_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """拿到 HTML 错误页时必须拦下：它的字节数不为零，光判大小拦不住。"""
    _patch_stream(monkeypatch, _FakeStreamResponse([b"<html>error</html>"], "text/html"))

    with pytest.raises(client.ImageGenError):
        client.download_image("https://temp/1.jpg", max_bytes=1024, timeout=5.0)


def test_download_image_rejects_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    """边读边判上限：超限在读到第二个 chunk 时就该停下。"""
    _patch_stream(
        monkeypatch,
        _FakeStreamResponse([b"x" * 600, b"y" * 600], "image/png"),
    )

    with pytest.raises(client.ImageGenError) as excinfo:
        client.download_image("https://temp/1.png", max_bytes=1000, timeout=5.0)

    assert "上限" in str(excinfo.value)


def test_download_image_rejects_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stream(monkeypatch, _FakeStreamResponse([], "image/png"))

    with pytest.raises(client.ImageGenError):
        client.download_image("https://temp/1.png", max_bytes=1000, timeout=5.0)


def test_download_image_wraps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_stream(monkeypatch, _FakeStreamResponse([b"x"], "image/png", status_code=403))

    with pytest.raises(client.ImageGenError):
        client.download_image("https://temp/1.png", max_bytes=1000, timeout=5.0)


# ---------------------------------------------------------------- 扩展名
@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("image/jpeg", ".jpg"),
        ("image/jpg", ".jpg"),
        ("image/png", ".png"),
        ("image/webp", ".webp"),
        ("image/png; charset=binary", ".png"),
        ("IMAGE/PNG", ".png"),
    ],
)
def test_extension_for_supported(content_type: str, expected: str) -> None:
    assert client.extension_for(content_type) == expected


@pytest.mark.parametrize("content_type", ["", "text/html", "application/octet-stream", "image/gif"])
def test_extension_for_unsupported(content_type: str) -> None:
    with pytest.raises(client.ImageGenError):
        client.extension_for(content_type)
