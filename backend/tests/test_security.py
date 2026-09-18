"""登录态（JWT）签发与校验的单元测试。

覆盖方案设计 §4.1 的「校验顺序」：签名 → `exp` → `sub` 可解析 → 载荷形状。
这里刻意**不碰数据库** —— 版本号比对在 `api/deps.py`，属于接口层用例。
"""

from __future__ import annotations

import base64
import json
import time

import jwt
import pytest

from app.core.config import JWT_SECRET_MIN_LEN, Settings
from app.core.exceptions import AppError, ErrorCode
from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    extract_bearer_token,
)

# 刻意**不**在模块里写死测试密钥：那会出现「测试用的密钥」与「conftest 注入的
# 密钥」两份，改一处忘一处。需要原始密钥的地方一律从 `settings.jwt_secret` 取，
# 单一来源。顺带避免了仓库凭证扫描器把一串字面量误判成真凭证。


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unsigned_token(payload: dict) -> str:
    """手工拼一个 `alg=none` 的 token（签名段为空）。

    为什么要手拼而不是 `jwt.encode(..., algorithm="none")`：后者依赖库对
    「空密钥」的处理细节，手拼才是攻击者真实会构造的形状。
    """
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    return f"{header}.{body}."


# -----------------------------------------------------------------------------
# 正常路径
# -----------------------------------------------------------------------------
def test_roundtrip_carries_user_and_version(settings: Settings) -> None:
    token, expires_in = create_access_token(user_id=7, token_version=3, settings=settings)

    payload = decode_access_token(token, settings=settings)

    assert payload.user_id == 7
    assert payload.token_version == 3
    assert expires_in == 168 * 3600  # 7 天（方案 §4.1）
    assert abs(payload.expires_at - (time.time() + expires_in)) < 5


def test_token_is_hs256(settings: Settings) -> None:
    """算法必须写死 HS256：从 token 头部读算法是算法混淆攻击的入口。"""
    token, _ = create_access_token(user_id=1, token_version=1, settings=settings)

    header = jwt.get_unverified_header(token)

    assert header["alg"] == ALGORITHM == "HS256"


def test_sub_is_string(settings: Settings) -> None:
    """JWT 规范要求 `sub` 是字符串；写成 int 会被严格实现拒绝。"""
    token, _ = create_access_token(user_id=42, token_version=1, settings=settings)
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])

    assert claims["sub"] == "42"
    assert isinstance(claims["sub"], str)


def test_has_jti(settings: Settings) -> None:
    """`jti` 本轮只用于日志追踪，但必须现在就有 —— 将来做单设备登出时需要它。"""
    token, _ = create_access_token(user_id=1, token_version=1, settings=settings)
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])

    assert isinstance(claims.get("jti"), str) and claims["jti"]


def test_two_tokens_have_different_jti(settings: Settings) -> None:
    a, _ = create_access_token(user_id=1, token_version=1, settings=settings)
    b, _ = create_access_token(user_id=1, token_version=1, settings=settings)

    assert jwt.decode(a, settings.jwt_secret, algorithms=["HS256"])["jti"] != jwt.decode(
        b, settings.jwt_secret, algorithms=["HS256"]
    )["jti"]


# -----------------------------------------------------------------------------
# 失败路径 —— 全部必须是 4010
# -----------------------------------------------------------------------------
def test_wrong_signature_rejected(settings: Settings) -> None:
    # 用等长（≥32 字节）的另一把密钥，避免 PyJWT 的密钥长度告警掩盖真正的断言
    other_secret = "another-dummy-key-0123456789abcdefghij"
    forged = jwt.encode(
        {"sub": "1", "ver": 1, "exp": int(time.time()) + 600}, other_secret, algorithm="HS256"
    )

    with pytest.raises(AppError) as exc:
        decode_access_token(forged, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED == 4010


def test_alg_none_rejected(settings: Settings) -> None:
    """`alg=none` 是最经典的伪造手法，必须被显式算法白名单挡掉。"""
    forged = _unsigned_token({"sub": "1", "ver": 1, "exp": int(time.time()) + 600})

    with pytest.raises(AppError) as exc:
        decode_access_token(forged, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_expired_rejected(settings: Settings) -> None:
    past = int(time.time()) - 200 * 3600  # 超过 168 小时
    token, _ = create_access_token(user_id=1, token_version=1, settings=settings, issued_at=past)

    with pytest.raises(AppError) as exc:
        decode_access_token(token, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_garbage_rejected(settings: Settings) -> None:
    for bad in ["", "   ", "not-a-token", "a.b.c", "a.b"]:
        with pytest.raises(AppError) as exc:
            decode_access_token(bad, settings=settings)
        assert exc.value.code == ErrorCode.UNAUTHORIZED, bad


def test_non_numeric_sub_rejected(settings: Settings) -> None:
    token = jwt.encode(
        {"sub": "abc", "ver": 1, "exp": int(time.time()) + 600}, settings.jwt_secret, algorithm="HS256"
    )

    with pytest.raises(AppError) as exc:
        decode_access_token(token, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_missing_ver_rejected(settings: Settings) -> None:
    """没有 `ver` 就无法做服务端主动失效 —— 这种 token 一律不认。"""
    token = jwt.encode({"sub": "1", "exp": int(time.time()) + 600}, settings.jwt_secret, algorithm="HS256")

    with pytest.raises(AppError) as exc:
        decode_access_token(token, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_bool_ver_rejected(settings: Settings) -> None:
    """Python 里 `True` 是 `int` 的子类，必须显式排除，否则 `ver=True` 会被当成 1。"""
    token = jwt.encode(
        {"sub": "1", "ver": True, "exp": int(time.time()) + 600}, settings.jwt_secret, algorithm="HS256"
    )

    with pytest.raises(AppError) as exc:
        decode_access_token(token, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_non_positive_user_id_rejected(settings: Settings) -> None:
    for bad_sub in ["0", "-3"]:
        token = jwt.encode(
            {"sub": bad_sub, "ver": 1, "exp": int(time.time()) + 600}, settings.jwt_secret, algorithm="HS256"
        )
        with pytest.raises(AppError) as exc:
            decode_access_token(token, settings=settings)
        assert exc.value.code == ErrorCode.UNAUTHORIZED, bad_sub


def test_missing_exp_rejected(settings: Settings) -> None:
    token = jwt.encode({"sub": "1", "ver": 1}, settings.jwt_secret, algorithm="HS256")

    with pytest.raises(AppError) as exc:
        decode_access_token(token, settings=settings)

    assert exc.value.code == ErrorCode.UNAUTHORIZED


# -----------------------------------------------------------------------------
# 密钥强度
# -----------------------------------------------------------------------------
def test_short_secret_refuses_to_sign() -> None:
    """弱密钥比没有密钥更危险 —— 宁可 500，也不要签出可被伪造的登录态。"""
    weak = Settings(jwt_secret="too-short")

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_access_token(user_id=1, token_version=1, settings=weak)


def test_empty_secret_refuses_to_sign() -> None:
    blank = Settings(jwt_secret="")

    with pytest.raises(RuntimeError):
        create_access_token(user_id=1, token_version=1, settings=blank)


def test_min_len_constant_is_32() -> None:
    assert JWT_SECRET_MIN_LEN == 32


def test_has_jwt_secret_property() -> None:
    assert Settings(jwt_secret="x" * 32).has_jwt_secret is True
    assert Settings(jwt_secret="x" * 31).has_jwt_secret is False
    assert Settings(jwt_secret="").has_jwt_secret is False


# -----------------------------------------------------------------------------
# Bearer 解析
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER abc", "abc"),
        ("Bearer   abc  ", "abc"),
        (None, None),
        ("", None),
        ("   ", None),
        ("abc", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("Basic abc", None),
        ("Token abc", None),
    ],
)
def test_extract_bearer_token(header: str | None, expected: str | None) -> None:
    assert extract_bearer_token(header) == expected
