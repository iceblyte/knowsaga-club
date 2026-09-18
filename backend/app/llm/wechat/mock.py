"""测试用的身份 Provider。

## 存在的理由

它是「测试中绝不对微信服务器发真实请求」这条红线的落点。
靠 monkeypatch 打到每个用例里很脆 —— 漏掉一处，测试就会变成
「偶尔依赖外网」的不确定用例，而那种失败最难查。把 mock 做成一个
**配置驱动的 Provider**，风险面就从 N 个用例收敛到 1 个工厂函数。

## 设计要点

- **确定性**：同一 `code` 必得同一 `openid`。否则「老用户查档」这类
  断言根本没法写（第二次登录会变成新用户）。
- **不散列成可变长度**：`users.openid` 是 `VARCHAR(64)`，
  派生长度必须稳定且放得下（`mock_` + 24 位十六进制 = 29 字符）。
- **特殊 code 触发特定失败**：让接口层用例不必替换整个 Provider
  就能覆盖 4011 / 4030 / 5032 三条分支。
"""

from __future__ import annotations

import hashlib

from app.core.exceptions import (
    account_blocked,
    wechat_code_invalid,
    wechat_upstream_error,
)
from app.llm.wechat.base import WechatIdentity, WechatIdentityProvider

#: openid 前缀。刻意与 `auth_service` 的调试通道前缀（`dev_`）区分开，
#: 这样测试库里一眼能看出某个身份是 mock 产生的。
MOCK_OPENID_PREFIX = "mock_"

#: 触发指定失败的保留 code
CODE_INVALID = "mock:invalid"
CODE_BLOCKED = "mock:blocked"
CODE_UPSTREAM = "mock:upstream"

#: 派生 openid 用的十六进制位数
_DIGEST_LEN = 24


class MockWechatIdentityProvider(WechatIdentityProvider):
    """确定性的假身份来源。**仅测试环境使用**。"""

    def exchange_code(self, code: str) -> WechatIdentity:
        value = (code or "").strip()

        if value == CODE_INVALID:
            raise wechat_code_invalid(detail="mock: 模拟 code 无效 (40029)")
        if value == CODE_BLOCKED:
            raise account_blocked(detail="mock: 模拟高风险用户拦截 (40226)")
        if value == CODE_UPSTREAM:
            raise wechat_upstream_error(detail="mock: 模拟上游异常 (-1)")
        if not value:
            # 与真实实现保持一致的前置失败
            raise wechat_code_invalid(detail="mock: empty code")

        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
        return WechatIdentity(
            openid=f"{MOCK_OPENID_PREFIX}{digest}",
            session_key="mock-session-key",
        )
