"""微信身份校验的抽象层。

## 为什么不直接 `requests.get` 了事

因为「换身份」这个动作有三件互不相干的事搅在一起：
拼请求参数、解释上游错误码、以及「测试里绝不能打真实微信服务器」。
把它们分开之后：

- `interpret_code2session` 是**纯函数**，错误码映射可以逐条单测，不用 mock 网络；
- `fetch` 可注入，测试用一行 lambda 就能覆盖超时、连接失败、返回 HTML 等分支；
- 上层（`auth_service`）只依赖 `WechatIdentityProvider` 这个协议，
  于是「换掉身份来源」不需要改任何业务代码。

## `session_key` 的处理

它随响应一起回来，但**不落库**（方案 §5.1 的裁决）。本轮没有任何用它解密
的场景，存一把用不到的密钥只是凭空多一个泄漏面。这里保留字段是为了让
「上游确实返回了它」这件事在调试时可见，以及将来真要用时不必重构签名。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class WechatIdentity:
    """一次成功登录所换到的用户身份。

    `session_key` 的 `repr` 被刻意排除（`repr=False`）：它属于敏感材料，
    一旦随日志或异常堆栈打印出来就等同泄漏。
    """

    openid: str
    unionid: str | None = None
    session_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not (self.openid or "").strip():
            # 这是**程序错误**而不是业务错误：上游成功响应里必须有 openid，
            # 走到这里说明调用方忘了校验。让它响亮地炸掉，而不是建档出一个空身份。
            raise ValueError("WechatIdentity.openid 不能为空")


class WechatIdentityProvider(ABC):
    """把一次性的 `code` 换成用户身份的抽象。"""

    @abstractmethod
    def exchange_code(self, code: str) -> WechatIdentity:
        """校验 `code` 并返回身份。

        Raises:
            AppError: 4011 / 4030 / 4290 / 5032，见 `app.core.exceptions`。
        """


def build_wechat_provider(settings: Settings | None = None) -> WechatIdentityProvider:
    """按配置构造 Provider。

    `WECHAT_PROVIDER=mock` 只在测试环境使用；生产与开发联调都必须走真实实现，
    否则「登录」会变成一个不发请求就通过的假动作。默认值是 `real`，
    由 `test_default_provider_is_real` 守着 —— 模板默认值必须是生产安全的。
    """
    s = settings or get_settings()
    if s.wechat_provider == "mock":
        from app.llm.wechat.mock import MockWechatIdentityProvider

        return MockWechatIdentityProvider()

    from app.llm.wechat.real import RealWechatIdentityProvider

    return RealWechatIdentityProvider(
        appid=s.wechat_appid,
        secret=s.wechat_app_secret,
        timeout=s.wechat_timeout_seconds,
    )
