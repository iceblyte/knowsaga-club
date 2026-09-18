"""微信身份校验 Provider 的单元测试。

**一律 mock 网络层**，绝不对 `api.weixin.qq.com` 发真实请求。
覆盖方案设计 §4.6 的错误码映射表：

| 上游 errcode | 业务码 | HTTP |
|---|---|---|
| 0 | — （成功） | 200 |
| 40029 | 4011 | 401 |
| 40226 | 4030 | 403 |
| 45011 | 4290 | 429 |
| -1 | 5032 | 502 |
| 未知 | 5032 | 502 |
"""

from __future__ import annotations

import httpx
import pytest

from app.core.exceptions import AppError, ErrorCode
from app.llm.wechat.base import WechatIdentity, build_wechat_provider
from app.llm.wechat.mock import MockWechatIdentityProvider
from app.llm.wechat.real import (
    CODE2SESSION_URL,
    RealWechatIdentityProvider,
    interpret_code2session,
)

# -----------------------------------------------------------------------------
# interpret_code2session：纯函数，错误码映射的唯一处
# -----------------------------------------------------------------------------
def test_success_returns_identity() -> None:
    identity = interpret_code2session(
        {"openid": "o_abc", "session_key": "sk", "unionid": "u_1", "errcode": 0, "errmsg": "ok"}
    )

    assert identity == WechatIdentity(openid="o_abc", unionid="u_1", session_key="sk")


def test_success_without_errcode_field() -> None:
    """官方文档示例里成功也会带 errcode=0，但字段缺失同样应视为成功。"""
    identity = interpret_code2session({"openid": "o_x", "session_key": "sk"})

    assert identity.openid == "o_x"
    assert identity.unionid is None


def test_success_without_unionid() -> None:
    """未绑定开放平台时不会返回 unionid —— 这不是错误。"""
    identity = interpret_code2session({"openid": "o_x", "session_key": "sk", "errcode": 0})

    assert identity.unionid is None


def test_errcode_zero_as_string() -> None:
    """上游偶尔把 errcode 序列化成字符串，不能因此判失败。"""
    identity = interpret_code2session({"openid": "o_x", "errcode": "0"})

    assert identity.openid == "o_x"


def test_missing_openid_is_upstream_error() -> None:
    """报成功却没有 openid 属于上游异常数据，不能建档出一个空身份。"""
    with pytest.raises(AppError) as exc:
        interpret_code2session({"errcode": 0, "session_key": "sk"})

    assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR


def test_blank_openid_is_upstream_error() -> None:
    with pytest.raises(AppError) as exc:
        interpret_code2session({"openid": "   ", "errcode": 0})

    assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR


@pytest.mark.parametrize(
    ("errcode", "expected_code", "expected_http"),
    [
        (40029, ErrorCode.WECHAT_CODE_INVALID, 401),
        (40226, ErrorCode.ACCOUNT_BLOCKED, 403),
        (45011, ErrorCode.RATE_LIMITED, 429),
        (-1, ErrorCode.WECHAT_UPSTREAM_ERROR, 502),
        (99999, ErrorCode.WECHAT_UPSTREAM_ERROR, 502),
    ],
)
def test_error_code_mapping(errcode: int, expected_code: int, expected_http: int) -> None:
    with pytest.raises(AppError) as exc:
        interpret_code2session({"errcode": errcode, "errmsg": "boom"})

    assert exc.value.code == expected_code
    assert exc.value.http_status == expected_http


def test_error_message_never_leaks_mechanism() -> None:
    """面向用户的提示里不能出现「openid」「code2session」这类内部机制说明。"""
    with pytest.raises(AppError) as exc:
        interpret_code2session({"errcode": 40029, "errmsg": "invalid code"})

    text = exc.value.message
    for leaked in ("openid", "code2session", "jscode", "40029", "session_key"):
        assert leaked not in text.lower()


# -----------------------------------------------------------------------------
# RealWechatIdentityProvider：请求参数与网络失败
# -----------------------------------------------------------------------------
def test_request_uses_get_with_official_params() -> None:
    """官方文档：GET + appid/secret/js_code/grant_type=authorization_code。"""
    seen: dict = {}

    def fake_fetch(url: str, params: dict, timeout: float) -> dict:
        seen.update(url=url, params=params, timeout=timeout)
        return {"openid": "o_1", "errcode": 0}

    provider = RealWechatIdentityProvider(
        appid="wx_app", secret="sec", timeout=7, fetch=fake_fetch
    )
    provider.exchange_code("the-code")

    assert seen["url"] == CODE2SESSION_URL
    assert seen["url"] == "https://api.weixin.qq.com/sns/jscode2session"
    assert seen["params"] == {
        "appid": "wx_app",
        "secret": "sec",
        "js_code": "the-code",
        "grant_type": "authorization_code",
    }
    assert seen["timeout"] == 7


def test_code_is_stripped_before_sending() -> None:
    seen: dict = {}

    def fake_fetch(_url: str, params: dict, _timeout: float) -> dict:
        seen.update(params)
        return {"openid": "o_1"}

    RealWechatIdentityProvider(appid="a", secret="b", fetch=fake_fetch).exchange_code("  c1  ")

    assert seen["js_code"] == "c1"


def test_empty_code_is_rejected_without_request() -> None:
    """空 code 属于客户端错误，不该浪费一次上游调用。"""

    def fake_fetch(*_a, **_kw):  # pragma: no cover - 不应被调用
        raise AssertionError("不应发起上游请求")

    provider = RealWechatIdentityProvider(appid="a", secret="b", fetch=fake_fetch)

    with pytest.raises(AppError) as exc:
        provider.exchange_code("")

    assert exc.value.code == ErrorCode.WECHAT_CODE_INVALID


def test_missing_credentials_is_upstream_error() -> None:
    """未配置 AppID/AppSecret 时以 5032 失败，而不是崩溃或匿名放行。"""

    def fake_fetch(*_a, **_kw):  # pragma: no cover - 不应被调用
        raise AssertionError("不应发起上游请求")

    for appid, secret in (("", ""), ("wx_a", ""), ("", "sec")):
        provider = RealWechatIdentityProvider(appid=appid, secret=secret, fetch=fake_fetch)
        with pytest.raises(AppError) as exc:
            provider.exchange_code("c1")
        assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR, (appid, secret)


def test_timeout_becomes_upstream_error() -> None:
    def fake_fetch(*_a, **_kw):
        raise httpx.ReadTimeout("timed out")

    provider = RealWechatIdentityProvider(appid="a", secret="b", fetch=fake_fetch)

    with pytest.raises(AppError) as exc:
        provider.exchange_code("c1")

    assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR


def test_network_error_becomes_upstream_error() -> None:
    def fake_fetch(*_a, **_kw):
        raise httpx.ConnectError("dns failure")

    provider = RealWechatIdentityProvider(appid="a", secret="b", fetch=fake_fetch)

    with pytest.raises(AppError) as exc:
        provider.exchange_code("c1")

    assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR


def test_non_json_response_becomes_upstream_error() -> None:
    """上游返回 HTML 错误页（网关故障时的常见形态）也不能让服务崩掉。"""

    def fake_fetch(*_a, **_kw):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    provider = RealWechatIdentityProvider(appid="a", secret="b", fetch=fake_fetch)

    with pytest.raises(AppError) as exc:
        provider.exchange_code("c1")

    assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR


def test_secret_never_appears_in_error_detail() -> None:
    """错误详情只进日志，但**日志也会被抄进 issue**，所以密钥一个字都不能出现。

    这里刻意用带 `dummy` 字样的假值：`tools/scan_secrets.py` 的通用模式匹配
    会把「`secret=` 后面接一长串字面量」报成疑似泄漏，而这个词表能让它认出
    「这显然是测试用的假凭证」。真正的防线（与 `.env` 真实值的反向比对）
    不受影响 —— 那条是纯子串判断。
    """
    fake_secret = "dummy-secret-value"

    def fake_fetch(*_a, **_kw):
        raise httpx.ConnectError("failed")

    provider = RealWechatIdentityProvider(appid="wx_a", secret=fake_secret, fetch=fake_fetch)

    with pytest.raises(AppError) as exc:
        provider.exchange_code("c1")

    assert fake_secret not in (exc.value.detail or "")


# -----------------------------------------------------------------------------
# MockWechatIdentityProvider
# -----------------------------------------------------------------------------
def test_mock_is_deterministic() -> None:
    """同一 code 必得同一 openid，否则测试无法稳定断言「老用户查档」。"""
    p = MockWechatIdentityProvider()

    assert p.exchange_code("code-a").openid == p.exchange_code("code-a").openid
    assert p.exchange_code("code-a").openid != p.exchange_code("code-b").openid


def test_mock_openid_fits_column() -> None:
    """`users.openid` 是 VARCHAR(64)，派生的 mock 身份必须放得下。"""
    openid = MockWechatIdentityProvider().exchange_code("x" * 500).openid

    assert 0 < len(openid) <= 64


def test_mock_special_codes() -> None:
    p = MockWechatIdentityProvider()

    with pytest.raises(AppError) as exc:
        p.exchange_code("mock:invalid")
    assert exc.value.code == ErrorCode.WECHAT_CODE_INVALID

    with pytest.raises(AppError) as exc:
        p.exchange_code("mock:blocked")
    assert exc.value.code == ErrorCode.ACCOUNT_BLOCKED

    with pytest.raises(AppError) as exc:
        p.exchange_code("mock:upstream")
    assert exc.value.code == ErrorCode.WECHAT_UPSTREAM_ERROR


def test_mock_rejects_blank_code() -> None:
    with pytest.raises(AppError) as exc:
        MockWechatIdentityProvider().exchange_code("  ")

    assert exc.value.code == ErrorCode.WECHAT_CODE_INVALID


# -----------------------------------------------------------------------------
# 工厂：测试环境绝不允许落到真实实现
# -----------------------------------------------------------------------------
def test_factory_returns_mock_in_test_env(settings) -> None:  # noqa: ANN001
    """`WECHAT_PROVIDER=mock` 时必须是 mock —— 否则测试会真的打微信服务器。"""
    provider = build_wechat_provider(settings)

    assert isinstance(provider, MockWechatIdentityProvider)


def test_factory_returns_real_by_default() -> None:
    from app.core.config import Settings

    provider = build_wechat_provider(Settings(wechat_provider="real", wechat_appid="a", wechat_app_secret="b"))

    assert isinstance(provider, RealWechatIdentityProvider)


def test_default_provider_is_real() -> None:
    """模板默认值必须是生产安全的：不能默认 mock。"""
    from app.core.config import Settings

    assert Settings.model_fields["wechat_provider"].default == "real"


def test_identity_is_frozen() -> None:
    """身份对象不该在传递过程中被改。"""
    identity = WechatIdentity(openid="o_1")

    with pytest.raises(Exception):
        identity.openid = "o_2"  # type: ignore[misc]
