"""真实微信身份校验（调用官方 `code2Session`）。

## 官方用法（2026-09-18 核对官方文档，见 docs 记录）

```
GET https://api.weixin.qq.com/sns/jscode2session
      ?appid=<APPID>&secret=<APP_SECRET>&js_code=<CODE>&grant_type=authorization_code
```

（上面用尖括号写的是**参数模板**，不是真实取值。）

- 请求方法就是 **GET**，参数走 query；官方另有「更安全地在服务端使用 POST」的
  通用建议，但本接口文档给出的调用方式是 GET，保持一致以免踩到网关差异。
- `grant_type` 固定 `authorization_code`，不填或写错一律失败。
- 接口**只能在服务端调用**（前端没有 secret，且官方明文禁止）。

## 错误码映射（方案 §4.6）

| 上游 errcode | 含义 | 业务码 |
|---|---|---|
| 0 | 成功 | — |
| 40029 | code 无效（含已使用/过期） | 4011 |
| 40226 | 高风险用户，登录被拦截 | 4030 |
| 45011 | 调用太频繁 | 4290 |
| -1 | 系统繁忙 | 5032 |
| 其他 / 网络异常 / 非 JSON | — | 5032 |

**所有失败详情只进 `AppError.detail`（写日志用），不进 `message`（给用户看）**，
且绝不把 `secret` 拼进任何错误文本。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

import httpx

from app.core.exceptions import (
    AppError,
    account_blocked,
    rate_limited,
    wechat_code_invalid,
    wechat_upstream_error,
)
from app.llm.wechat.base import WechatIdentity, WechatIdentityProvider

#: 官方端点。`grant_type` 固定值也一并放在模块级，便于测试直接引用。
CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
GRANT_TYPE = "authorization_code"

#: `fetch` 的形状：`(url, params, timeout) -> dict`
FetchJson = Callable[[str, Mapping[str, str], float], Any]

#: `code` 的长度上限。官方 `code` 是 32 位字符串，这里留足余量只防超长输入；
#: 真正的合法性由上游判定 —— 我们不做「猜格式」的前置校验。
CODE_MAX_LEN = 512


def _default_fetch(url: str, params: Mapping[str, str], timeout: float) -> Any:
    """真实 HTTP 调用。

    `trust_env=True`（httpx 默认）会读 `HTTP_PROXY`/`HTTPS_PROXY`，
    这对国内需要走代理的开发机是必要的；线上若不需要，不设这两个变量即可。
    """
    response = httpx.get(url, params=dict(params), timeout=timeout)
    response.raise_for_status()
    # 上游在网关故障时会返回 HTML，`json()` 会抛 ValueError —— 由调用方统一兜住
    return response.json()


def interpret_code2session(data: Any) -> WechatIdentity:
    """把上游响应解释成身份，或抛出对应的业务错误。

    抽成纯函数是为了让错误码映射**可被逐条断言**，不必 mock 网络。
    """
    if not isinstance(data, Mapping):
        raise wechat_upstream_error(detail=f"unexpected payload type: {type(data).__name__}")

    errcode = _as_int(data.get("errcode"))
    errmsg = str(data.get("errmsg") or "")

    # 成功：官方示例里成功也会带 errcode=0，但字段缺失同样视为成功
    if errcode is None or errcode == 0:
        openid = str(data.get("openid") or "").strip()
        if not openid:
            # 报成功却没有 openid 属于上游异常数据。绝不能据此建档：
            # 那会造出一个「所有异常请求共用」的身份。
            raise wechat_upstream_error(detail=f"code2session ok but openid missing: {errmsg}")
        unionid = str(data.get("unionid") or "").strip() or None
        return WechatIdentity(
            openid=openid,
            unionid=unionid,
            session_key=str(data.get("session_key") or ""),
        )

    if errcode == 40029:
        raise wechat_code_invalid(detail=f"errcode=40029 errmsg={errmsg}")
    if errcode == 40226:
        raise account_blocked(detail=f"errcode=40226 errmsg={errmsg}")
    if errcode == 45011:
        raise rate_limited(detail=f"errcode=45011 errmsg={errmsg}")
    if errcode == -1:
        raise wechat_upstream_error(detail=f"errcode=-1 errmsg={errmsg}")

    # 未知错误码：归到 5032。不能默认放行，也不能当成「code 无效」——
    # 后者会把上游故障说成用户的问题，让排查方向跑偏。
    raise wechat_upstream_error(detail=f"unknown errcode={errcode} errmsg={errmsg}")


def _as_int(value: Any) -> int | None:
    """宽松取整：上游偶尔把 errcode 序列化成字符串。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RealWechatIdentityProvider(WechatIdentityProvider):
    """真实 Provider。

    Args:
        fetch: 可注入的网络层，签名 `(url, params, timeout) -> dict`。
            测试用它覆盖超时 / 连接失败 / 非 JSON 响应等分支；
            运行期不传，走 `_default_fetch`。
    """

    def __init__(
        self,
        *,
        appid: str,
        secret: str,
        timeout: float = 8.0,
        fetch: FetchJson | None = None,
    ) -> None:
        self._appid = (appid or "").strip()
        self._secret = (secret or "").strip()
        self._timeout = float(timeout)
        self._fetch: FetchJson = fetch or _default_fetch

    @property
    def is_configured(self) -> bool:
        """凭据是否齐备。测试号两者都为空，无法换取身份。"""
        return bool(self._appid) and bool(self._secret)

    def exchange_code(self, code: str) -> WechatIdentity:
        value = (code or "").strip()

        # 两种「不必打上游」的前置失败，提前返回能省一次请求、也让日志更干净：
        # 空 code 是客户端错误；缺凭据是服务端配置错误。
        if not value or len(value) > CODE_MAX_LEN:
            raise wechat_code_invalid(detail=f"empty or overlong code (len={len(value)})")
        if not self.is_configured:
            raise wechat_upstream_error(detail="WECHAT_APPID / WECHAT_APP_SECRET 未配置")

        params = {
            "appid": self._appid,
            "secret": self._secret,
            "js_code": value,
            "grant_type": GRANT_TYPE,
        }

        try:
            payload = self._fetch(CODE2SESSION_URL, params, self._timeout)
        except httpx.HTTPStatusError as exc:
            # 带上状态码，但**不带 URL** —— URL 里含 secret
            raise wechat_upstream_error(
                detail=f"upstream http {exc.response.status_code}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 目标是「绝不把异常漏给用户」
            # 超时、DNS 失败、连接重置、非 JSON（ValueError）、JSON 形状不对……
            # 这些对用户都是同一件事：这次没换成身份，请重试。
            # `detail` 里只放异常类型与文本，不放参数（参数含 secret）。
            raise wechat_upstream_error(detail=f"{type(exc).__name__}: {exc}") from exc

        return interpret_code2session(payload)


def describe_error(error: AppError) -> str:
    """给日志用的一行描述（不含任何凭据）。"""
    return json.dumps({"code": error.code, "detail": error.detail}, ensure_ascii=False)
