"""接口层的公共依赖：取当前用户、来源 IP、身份 Provider。

## 为什么版本号比对放在这里而不是 `core/security.py`

`security.py` 刻意不碰数据库 —— 它只回答「这个 token 是不是我们签的、
有没有过期、是哪个用户、签的是第几版」。版本号是否与库里一致需要一次
查询，属于接口层的事。分开之后，JWT 那一层可以纯单测，不需要库。

## 401 的统一口径

无 token / 格式错 / 签名错 / 过期 / 用户不存在 / 版本号不符 ——
全部返回**同一个** 4010。对外区分这些只会帮攻击者缩小范围，
对正常用户则没有任何帮助（他们的动作都是「重新进入」）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.exceptions import unauthorized
from app.core.security import decode_access_token, extract_bearer_token
from app.db.session import get_db
from app.db.tables import User
from app.llm.wechat.base import WechatIdentityProvider, build_wechat_provider


def get_wechat_provider() -> WechatIdentityProvider:
    """身份 Provider（测试用依赖覆盖替换成 mock）。"""
    return build_wechat_provider()


def get_client_ip(request: Request) -> str:
    """取来源 IP，用于登录限流。

    `X-Forwarded-For` 只在**存在**时才用它的**第一段**：这是反代/网关
    透传真实客户端 IP 的标准做法。注意它可被伪造，所以它只用于限流
    （伪造它的代价是「自己被限流」），绝不用于鉴权或授权判断。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def get_current_user(
    session: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """从 `Authorization: Bearer` 解析并校验登录态，返回用户行。

    校验顺序严格按方案 §4.1：签名 → `exp` → `sub` 可解析 → 用户存在 → `ver` 一致。
    前四步都在 `decode_access_token` 与这次查询里，最后一步在下面。

    Raises:
        AppError: 4010
    """
    token = extract_bearer_token(authorization)
    if token is None:
        raise unauthorized(detail="缺少或格式不正确的 Authorization 头")

    payload = decode_access_token(token)

    user = session.get(User, payload.user_id)
    if user is None:
        raise unauthorized(detail=f"用户 {payload.user_id} 不存在")

    # 版本号必须**完全相等**：比库里大也不能放行，否则「登出后重新登录」
    # 期间签发的 token 会带着新版本号被旧会话伪造出来。
    if int(user.token_version) != payload.token_version:
        raise unauthorized(
            detail=f"用户 {payload.user_id} 的登录态版本不匹配（期望 {user.token_version}）"
        )

    return user


#: 路由签名里用 `user: CurrentUser` 即可，读起来比 `Depends(...)` 干净
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
WechatProvider = Annotated[WechatIdentityProvider, Depends(get_wechat_provider)]
