"""认证接口 `/api/v1/auth/*` 的接口测试。

覆盖方案设计 §4.3 鉴权矩阵中的认证三端点，以及 §4.5 登出真失效、
§4.6 错误码映射、§4.7 调试通道的注册边界。

**微信身份一律走 mock Provider**（conftest 的 `WECHAT_PROVIDER=mock`），
所以这里不会对微信服务器发出任何真实请求。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ErrorCode
from app.core.security import create_access_token
from app.llm.wechat.real import RealWechatIdentityProvider

AUTH = "/api/v1/auth"
ME = "/api/v1/users/me"


def _use_provider(client: TestClient, provider) -> None:  # noqa: ANN001
    """把身份 Provider 替换成指定实现。"""
    from app.api.deps import get_wechat_provider

    client.app.dependency_overrides[get_wechat_provider] = lambda: provider


# -----------------------------------------------------------------------------
# 调试通道（§4.7）
# -----------------------------------------------------------------------------
def test_dev_login_returns_token_and_user(db_client: TestClient) -> None:
    resp = db_client.post(f"{AUTH}/dev", json={"device_id": "device-a"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["token"]
    assert data["expires_in"] == 168 * 3600
    assert data["user"]["nickname"].startswith("冒险者 · ")
    assert data["user"]["level"] == 1
    assert data["user"]["xp_total"] == 0
    assert data["user"]["avatar_key"] == "scholar"


def test_dev_login_is_stable_for_same_device(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    first = dev_login("device-a")
    second = dev_login("device-a")

    assert first["user"]["id"] == second["user"]["id"]


def test_dev_login_differs_across_devices(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    assert dev_login("device-a")["user"]["id"] != dev_login("device-b")["user"]["id"]


def test_dev_login_creates_user_settings_row(db_client: TestClient, db_session, dev_login) -> None:  # noqa: ANN001
    """自动建档必须**同时**建设置行 —— 否则设置页会读到空。"""
    from app.db.tables import UserSetting

    user_id = dev_login("device-settings")["user"]["id"]

    row = db_session.get(UserSetting, user_id)
    assert row is not None
    assert row.reminder_enabled is True
    assert row.reminder_days == [1, 2, 3, 4, 5]
    assert str(row.reminder_time).startswith("20:00")
    assert row.sound_enabled is True
    assert row.auto_load_images is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"device_id": ""},
        {"device_id": "   "},
        {"device_id": "x" * 129},
        {"device_id": 123},
    ],
)
def test_dev_login_validates_device_id(db_client: TestClient, payload: dict) -> None:
    resp = db_client.post(f"{AUTH}/dev", json=payload)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_dev_route_absent_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产配置下该路径**根本不存在**（404），而不是「已注册但拒绝」。

    这是 §4.7 的关键：不存在 = 没有「忘记关掉」的风险面。
    """
    monkeypatch.setenv("DEV_LOGIN_ENABLED", "false")
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            resp = client.post(f"{AUTH}/dev", json={"device_id": "device-a"})
        assert resp.status_code == 404
    finally:
        get_settings.cache_clear()


def test_dev_route_absent_in_prod_even_if_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """两个条件必须同时满足：开发环境 **且** 显式开启。"""
    monkeypatch.setenv("DEV_LOGIN_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-0123456789abcdef0123456789abcdef")
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            resp = client.post(f"{AUTH}/dev", json={"device_id": "device-a"})
        assert resp.status_code == 404
    finally:
        get_settings.cache_clear()


# -----------------------------------------------------------------------------
# 微信登录
# -----------------------------------------------------------------------------
def test_wechat_login_with_mock_provider(db_client: TestClient) -> None:
    resp = db_client.post(f"{AUTH}/wechat", json={"code": "code-1"})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["token"]
    assert data["user"]["nickname"].startswith("冒险者 · ")


def test_wechat_login_same_code_maps_to_same_user(db_client: TestClient) -> None:
    first = db_client.post(f"{AUTH}/wechat", json={"code": "code-1"}).json()["data"]
    second = db_client.post(f"{AUTH}/wechat", json={"code": "code-1"}).json()["data"]

    assert first["user"]["id"] == second["user"]["id"]


def test_wechat_login_invalid_code(db_client: TestClient) -> None:
    resp = db_client.post(f"{AUTH}/wechat", json={"code": "mock:invalid"})

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.WECHAT_CODE_INVALID == 4011


def test_wechat_login_blocked_user(db_client: TestClient) -> None:
    resp = db_client.post(f"{AUTH}/wechat", json={"code": "mock:blocked"})

    assert resp.status_code == 403
    assert resp.json()["code"] == ErrorCode.ACCOUNT_BLOCKED == 4030


def test_wechat_login_upstream_error(db_client: TestClient) -> None:
    resp = db_client.post(f"{AUTH}/wechat", json={"code": "mock:upstream"})

    assert resp.status_code == 502
    assert resp.json()["code"] == ErrorCode.WECHAT_UPSTREAM_ERROR == 5032


def test_wechat_login_without_credentials(db_client: TestClient) -> None:
    """未配置 AppID/AppSecret 时以 5032 失败 —— 便于核心闭环先行联调。"""
    _use_provider(db_client, RealWechatIdentityProvider(appid="", secret=""))

    resp = db_client.post(f"{AUTH}/wechat", json={"code": "code-1"})

    assert resp.status_code == 502
    assert resp.json()["code"] == ErrorCode.WECHAT_UPSTREAM_ERROR


@pytest.mark.parametrize("payload", [{}, {"code": ""}, {"code": "x" * 600}, {"code": 5}])
def test_wechat_login_validates_code(db_client: TestClient, payload: dict) -> None:
    resp = db_client.post(f"{AUTH}/wechat", json=payload)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_wechat_login_is_rate_limited(db_client: TestClient, settings) -> None:  # noqa: ANN001
    """登录接口必须限流：`code` 换来换去就能无限建档，是最容易被刷的入口。"""
    limit = settings.login_rate_limit

    codes = []
    for i in range(limit):
        resp = db_client.post(f"{AUTH}/wechat", json={"code": f"flood-{i}"})
        assert resp.status_code == 200, f"第 {i} 次不该被限流：{resp.text}"
        codes.append(resp.json()["code"])

    blocked = db_client.post(f"{AUTH}/wechat", json={"code": "flood-x"})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == ErrorCode.RATE_LIMITED == 4290


def test_dev_login_has_its_own_rate_limit_budget(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    """两个通道各算各的额度 —— 否则联调时调接口会把微信通道的额度耗光。"""
    for i in range(5):
        db_client.post(f"{AUTH}/wechat", json={"code": f"mixed-{i}"})

    # 微信通道消耗了 5 次，调试通道仍有完整额度
    assert dev_login("device-mixed")["token"]


# -----------------------------------------------------------------------------
# 登出（§4.5）
# -----------------------------------------------------------------------------
def test_logout_invalidates_old_token_immediately(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    data = dev_login("device-logout")
    headers = {"Authorization": f"Bearer {data['token']}"}

    assert db_client.get(ME, headers=headers).status_code == 200

    resp = db_client.post(f"{AUTH}/logout", headers=headers)
    assert resp.status_code == 200, resp.text

    after = db_client.get(ME, headers=headers)
    assert after.status_code == 401
    assert after.json()["code"] == ErrorCode.UNAUTHORIZED


def test_logout_does_not_affect_other_users(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    """递增版本号是按用户隔离的：A 登出不能让 B 掉线。"""
    a = dev_login("device-a")
    b = dev_login("device-b")

    db_client.post(f"{AUTH}/logout", headers={"Authorization": f"Bearer {a['token']}"})

    assert db_client.get(ME, headers={"Authorization": f"Bearer {b['token']}"}).status_code == 200


def test_relogin_after_logout_works(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    first = dev_login("device-relogin")
    db_client.post(f"{AUTH}/logout", headers={"Authorization": f"Bearer {first['token']}"})

    second = dev_login("device-relogin")

    assert second["token"]
    assert second["user"]["id"] == first["user"]["id"]
    assert (
        db_client.get(ME, headers={"Authorization": f"Bearer {second['token']}"}).status_code == 200
    )


def test_logout_requires_auth(db_client: TestClient) -> None:
    resp = db_client.post(f"{AUTH}/logout")

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


# -----------------------------------------------------------------------------
# 鉴权全部失败路径（§4.1 校验顺序）
# -----------------------------------------------------------------------------
def test_me_without_token(db_client: TestClient) -> None:
    resp = db_client.get(ME)

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


@pytest.mark.parametrize(
    "header",
    [
        "Bearer",
        "Bearer ",
        "Basic abc",
        "abc",
        "Bearer not-a-jwt",
        "Bearer a.b.c",
    ],
)
def test_me_with_malformed_header(db_client: TestClient, header: str) -> None:
    resp = db_client.get(ME, headers={"Authorization": header})

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_with_token_signed_by_other_secret(db_client: TestClient, dev_login) -> None:  # noqa: ANN001
    import jwt

    user_id = dev_login("device-forge")["user"]["id"]
    forged = jwt.encode(
        {"sub": str(user_id), "ver": 1, "exp": int(time.time()) + 600},
        "攻击者自己的密钥" * 4,
        algorithm="HS256",
    )

    resp = db_client.get(ME, headers={"Authorization": f"Bearer {forged}"})

    assert resp.status_code == 401


def test_me_with_expired_token(db_client: TestClient, dev_login, settings) -> None:  # noqa: ANN001
    user_id = dev_login("device-expired")["user"]["id"]
    token, _ = create_access_token(
        user_id=user_id,
        token_version=1,
        settings=settings,
        issued_at=int(time.time()) - 200 * 3600,
    )

    resp = db_client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_with_unknown_user(db_client: TestClient, settings) -> None:  # noqa: ANN001
    token, _ = create_access_token(user_id=999999, token_version=1, settings=settings)

    resp = db_client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401
    assert resp.json()["code"] == ErrorCode.UNAUTHORIZED


def test_me_with_future_token_version(db_client: TestClient, dev_login, settings) -> None:  # noqa: ANN001
    """版本号必须**完全相等**：比库里大也不能放行。"""
    user_id = dev_login("device-ver")["user"]["id"]
    token, _ = create_access_token(user_id=user_id, token_version=99, settings=settings)

    resp = db_client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 401


def test_unauthorized_message_has_no_internal_mechanism(db_client: TestClient) -> None:
    """面向用户的提示不出现「JWT」「token」「4010」这类内部机制说明。"""
    message = db_client.get(ME).json()["message"].lower()

    for leaked in ("jwt", "token", "bearer", "4010", "签名", "载荷"):
        assert leaked not in message


# -----------------------------------------------------------------------------
# 回归：既有接口不受影响
# -----------------------------------------------------------------------------
def test_health_still_public(db_client: TestClient) -> None:
    resp = db_client.get("/api/v1/health")

    assert resp.status_code == 200
    assert resp.json()["code"] == 0
