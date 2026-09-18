"""登录、建档与登出。

## 静默登录的完整链路

```
wx.login() → code → POST /auth/wechat
  → provider.exchange_code(code)     # 服务端调 code2Session 换 openid
  → 查 users.openid
      命中 → 用现有档案
      未命中 → 建档（users + user_settings 各一行）
  → 签发 JWT（sub=user.id, ver=user.token_version）
```

## 三处刻意的决定

**1. 自动建档是「登录」的一部分。**
没有注册接口 —— 微信静默登录拿到的 openid 就是账号本身。
所以「首次进入」与「再次进入」必须是同一条代码路径，只是分支不同。
拆成两个接口会让前端多一次「要不要注册」的判断，而那判断本就不该存在。

**2. 昵称与头像是派生默认值，不是空值。**
`nickname` 由 openid 派生（「冒险者 · 7A3F」），`avatar_key` 默认「学者」。
这样任何界面在任何时刻都有东西可渲染，不需要处理「还没有昵称」的空态。
派生而不是随机：同一用户在任何设备重装后都会得到同一个默认昵称。

**3. 登出是递增 `token_version`，不是删 token。**
本轮没有令牌表，无法「把某个 token 作废」。递增版本号让**该用户所有
已签发的登录态**立即失效 —— 对单端场景这就是登出的准确语义。
代价是递增一列，而鉴权时本来就要查这一行。

## 并发首登

同一用户同时发两个登录请求（小程序冷启动 + 页面 onShow 都可能触发），
两个请求可能都判「无档案」然后都去 INSERT，第二个会撞 `uk_users_openid`。
这不是理论问题：`wx.login` 的 code 每次不同，但 openid 相同。
处理方式是**捕获唯一键冲突后回查** —— 让并发变成「一次建档 + 一次查档」，
而不是把 500 抛给用户。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.tables import User, UserSetting
from app.llm.wechat.base import WechatIdentity, WechatIdentityProvider
from app.utils.crypto import DEFAULT_AVATAR_KEY, derive_nickname
from app.utils.timeutil import utcnow

#: 调试通道派生的 openid 前缀。与真实 openid 形状不同，便于人工区分。
DEV_OPENID_PREFIX = "dev_"

#: openid 列的容量上限（`users.openid VARCHAR(64)`）
OPENID_MAX_LEN = 64


@dataclass(frozen=True, slots=True)
class LoginResult:
    """登录成功的结果。`user` 是 ORM 行，由路由层转成对外视图。"""

    user: User
    token: str
    expires_in: int


def dev_openid(device_id: str) -> str:
    """由设备标识派生稳定 openid。

    「稳定」是它唯一的用处：同一个 `device_id` 每次进来都是同一个账号，
    于是 H5 联调时刷新页面不会变成新用户。
    """
    digest = hashlib.sha256(device_id.strip().encode("utf-8")).hexdigest()
    length = OPENID_MAX_LEN - len(DEV_OPENID_PREFIX)
    return f"{DEV_OPENID_PREFIX}{digest[:length]}"


def login_with_identity(session: Session, identity: WechatIdentity) -> LoginResult:
    """按身份查档或建档，然后签发登录态。

    失败时不会留下半条数据：建档的两次 INSERT 在同一次 `commit()` 里，
    `user_settings` 失败会一起回滚 —— 否则会留下一个没有设置行的用户，
    所有设置接口都要额外处理 None。
    """
    user = _find_by_openid(session, identity.openid)

    if user is None:
        user = _create_user(session, identity)

    _touch_login(session, user, identity)

    token, expires_in = create_access_token(
        user_id=int(user.id), token_version=int(user.token_version)
    )
    return LoginResult(user=user, token=token, expires_in=expires_in)


def login_with_wechat_code(
    session: Session,
    code: str,
    provider: WechatIdentityProvider,
) -> LoginResult:
    """真实链路：`code` → 身份 → 登录。"""
    return login_with_identity(session, provider.exchange_code(code))


def login_with_device(session: Session, device_id: str) -> LoginResult:
    """调试通道：设备标识 → 身份 → 登录。"""
    return login_with_identity(session, WechatIdentity(openid=dev_openid(device_id)))


def logout(session: Session, user: User) -> None:
    """让该用户**所有**已签发的登录态立即失效。"""
    user.token_version = int(user.token_version) + 1
    user.updated_at = utcnow()
    session.commit()


# -----------------------------------------------------------------------------
# 内部
# -----------------------------------------------------------------------------
def _find_by_openid(session: Session, openid: str) -> User | None:
    return session.scalar(select(User).where(User.openid == openid))


def _create_user(session: Session, identity: WechatIdentity) -> User:
    """建档。并发冲突时回查已存在的那一行。"""
    user = User(
        openid=identity.openid,
        unionid=identity.unionid,
        nickname=derive_nickname(identity.openid),
        avatar_key=DEFAULT_AVATAR_KEY,
        avatar_url=None,
        xp_total=0,
        coins=0,
        streak_days=0,
        longest_streak=0,
        last_active_date=None,
        token_version=1,
        last_login_at=utcnow(),
    )
    session.add(user)
    try:
        session.flush()  # 需要拿到自增 id 才能建设置行
    except IntegrityError:
        # 并发首次登录：另一个请求已经建好了。回滚本次并复用它。
        session.rollback()
        existing = _find_by_openid(session, identity.openid)
        if existing is None:  # pragma: no cover - 冲突却查不到，说明冲突来自别的约束
            raise
        return existing

    session.add(UserSetting(user_id=int(user.id)))
    session.commit()
    return user


def _touch_login(session: Session, user: User, identity: WechatIdentity) -> None:
    """更新登录痕迹。

    `unionid` 只在「本来没有、这次拿到了」时补写。反过来清空是错误的：
    小程序未绑定开放平台时不会返回 unionid，那不代表用户解绑了。
    """
    user.last_login_at = utcnow()
    if identity.unionid and not user.unionid:
        user.unionid = identity.unionid
    session.commit()
