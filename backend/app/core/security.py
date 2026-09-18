"""登录态（JWT）的签发与校验。

## 规格（用户系统方案设计文档 §4.1）

| 项 | 取值 |
|---|---|
| 算法 | `HS256`（校验时**显式**传 `algorithms=["HS256"]`） |
| 密钥 | `JWT_SECRET`，≥ 32 字符；不达标时服务拒绝启动，绝不用默认值兜底 |
| 有效期 | `JWT_EXPIRE_HOURS`（默认 168 小时 = 7 天） |
| 载荷 | `sub`(用户 id 字符串) / `ver`(版本号) / `iat` / `exp` / `jti` |
| 传输 | `Authorization: Bearer <token>` |

## 两个必须写死的点

**1. `algorithms` 不能省。** 若省略或从 token 头部读取算法，攻击者可以构造
`alg: none` 或把 HS256 换成非对称算法来伪造身份（算法混淆攻击）。显式白名单是
唯一正确的写法。

**2. `ver` 只在这里解码，不在这里比对。** 版本号是否与库中一致需要一个数据库查询，
而这一层刻意不碰数据库 —— 它只回答「这个 token 是不是我们签的、有没有过期、
是哪个用户、签的是第几版」。比对在 `api/deps.py` 里做。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

import jwt

from app.core.config import JWT_SECRET_MIN_LEN, Settings, get_settings
from app.core.exceptions import unauthorized

#: 唯一的签名算法。
ALGORITHM = "HS256"

#: `Authorization` 头部的前缀（大小写不敏感地匹配）
BEARER_PREFIX = "bearer "


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """解码后的登录态载荷。"""

    user_id: int
    token_version: int
    #: 过期时刻（Unix 秒），便于调试与测试断言
    expires_at: int


def _secret(settings: Settings | None) -> str:
    """取签名密钥。

    Raises:
        RuntimeError: 未配置或长度不足。这是**配置错误**而不是业务错误 ——
            让它以 500 暴露出来，而不是悄悄用一个弱密钥继续签发可被伪造的登录态。
    """
    s = settings or get_settings()
    secret = (s.jwt_secret or "").strip()
    if len(secret) < JWT_SECRET_MIN_LEN:
        raise RuntimeError(
            f"JWT_SECRET 未配置或长度不足 {JWT_SECRET_MIN_LEN} 字符，拒绝签发登录态。"
            "生成方式：python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return secret


def create_access_token(
    *,
    user_id: int,
    token_version: int,
    settings: Settings | None = None,
    issued_at: int | None = None,
) -> tuple[str, int]:
    """签发登录态。

    Args:
        user_id: 用户主键。
        token_version: 该用户当前的登录态版本号（登出时递增即可让旧 token 全失效）。
        issued_at: 签发时刻（Unix 秒）。**只为测试注入**，运行期不要传 ——
            它会让「有效期」变成调用方说了算。

    Returns:
        `(token, expires_in_seconds)`
    """
    s = settings or get_settings()
    now = int(issued_at if issued_at is not None else time.time())
    expires_in = max(1, int(s.jwt_expire_hours)) * 3600

    payload = {
        # `sub` 按 JWT 规范必须是字符串；写成 int 会被严格实现的库拒绝
        "sub": str(user_id),
        "ver": int(token_version),
        "iat": now,
        "exp": now + expires_in,
        # jti 现在只用于日志追踪（本轮不做单 token 撤销）；保留它是因为
        # 将来要「单设备登出」时必须有这个字段，而补发 token 才能加字段代价很大
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, _secret(s), algorithm=ALGORITHM), expires_in


def decode_access_token(token: str, *, settings: Settings | None = None) -> TokenPayload:
    """解码并校验登录态。

    校验顺序：**签名 → 过期 → 载荷形状**。任一失败都抛同一个 `4010` ——
    对外区分「签名错」与「已过期」只会帮攻击者缩小范围。

    Raises:
        AppError: code=4010
    """
    s = settings or get_settings()
    raw = (token or "").strip()
    if not raw:
        raise unauthorized(detail="empty token")

    try:
        data = jwt.decode(
            raw,
            _secret(s),
            algorithms=[ALGORITHM],
            # 本轮没有 aud / iss 概念，显式关掉以免被库的默认行为绊住
            options={"verify_aud": False, "verify_iss": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized(detail="token expired") from exc
    except jwt.InvalidTokenError as exc:
        # 签名错、格式错、算法不符 —— 全部落在这里
        raise unauthorized(detail=f"token invalid: {exc}") from exc

    sub = data.get("sub")
    try:
        user_id = int(sub)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise unauthorized(detail=f"bad sub: {sub!r}") from exc

    ver = data.get("ver")
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise unauthorized(detail=f"bad ver: {ver!r}")

    exp = data.get("exp")
    if not isinstance(exp, int):
        raise unauthorized(detail=f"bad exp: {exp!r}")

    if user_id <= 0:
        raise unauthorized(detail=f"non-positive user_id: {user_id}")

    return TokenPayload(user_id=user_id, token_version=ver, expires_at=exp)


def extract_bearer_token(authorization: str | None) -> str | None:
    """从 `Authorization` 头部取出 bearer 令牌；不合法时返回 `None`。

    刻意**只做形状解析、不做校验**：形状不对与签名不对，对调用方都是
    「没有有效登录态」，交给 `decode_access_token` 统一给 4010。
    """
    if not authorization:
        return None
    value = authorization.strip()
    if len(value) <= len(BEARER_PREFIX) or not value.lower().startswith(BEARER_PREFIX):
        return None
    token = value[len(BEARER_PREFIX) :].strip()
    return token or None
