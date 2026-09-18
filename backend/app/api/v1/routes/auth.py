"""登录 / 登出接口（方案 §6.1、§4.3）。

## 两个路由对象

`router` 始终注册；`dev_router` **只在满足条件时**由 `build_api_router()` 挂上。
不满足时该路径根本不存在（404），而不是「已注册但拒绝」——
后者会把「生产环境有一个能免密登录的端点」这件事留在代码里，
只靠一个配置项挡着，风险面完全不同。

## 限流按通道分开计数

微信通道与调试通道各有一份额度（`name` 不同）。否则本机联调时反复调
`/auth/dev` 会把 `/auth/wechat` 的额度一起耗掉，两边都变得难以调试。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, DbSession, WechatProvider, get_client_ip
from app.core import ratelimit
from app.core.response import ok
from app.models.user import DevLoginRequest, LoginResponse, WechatLoginRequest
from app.services import auth_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])

#: 调试通道。**仅开发环境 + 显式开启时**才会被挂到 `/api/v1` 上。
dev_router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/wechat")
def wechat_login(
    payload: WechatLoginRequest,
    request: Request,
    session: DbSession,
    provider: WechatProvider,
) -> dict:
    """微信静默登录：`code` → 身份 → 建档/查档 → 签发登录态。"""
    ratelimit.enforce("wechat", get_client_ip(request))

    result = auth_service.login_with_wechat_code(session, payload.code, provider)
    return ok(_login_payload(result))


@dev_router.post("/dev")
def dev_login(
    payload: DevLoginRequest,
    request: Request,
    session: DbSession,
) -> dict:
    """开发调试登录：由设备标识派生稳定身份。

    存在的理由：没有正式 AppID 时，除登录外的全部链路都无法在本机验证
    （方案 §12 风险表第 1 行）。它把「本机可跑通全流程」这件事变成可能，
    而代价只是「生产配置下这段代码根本不被挂载」。
    """
    ratelimit.enforce("dev", get_client_ip(request))

    result = auth_service.login_with_device(session, payload.device_id)
    return ok(_login_payload(result))


@router.post("/logout")
def logout(user: CurrentUser, session: DbSession) -> dict:
    """登出：递增登录态版本号，**该用户所有已签发的登录态立即失效**。"""
    auth_service.logout(session, user)
    return ok({"logged_out": True})


def _login_payload(result: auth_service.LoginResult) -> dict:
    """把服务层结果转成对外契约。

    单独抽出来是为了让两个登录端点**共用同一份响应形状** ——
    任何一边漏字段都会立刻在夹具化的接口测试里暴露。
    """
    return LoginResponse(
        token=result.token,
        expires_in=result.expires_in,
        user=user_service.to_user_public(result.user),
    ).model_dump(mode="json")
