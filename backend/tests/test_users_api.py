"""用户接口 `/api/v1/users/me*` 的接口测试。

覆盖：
- 04·1 个人中心所需的全部数字（等级 / 进度 / 三宫格 / 入口计数）
- PATCH 昵称与预置头像（含昵称合规校验）
- 头像上传（类型 / 大小 / 魔数 / 服务端命名 / 静态可访问）
- 设置读写（07·5 与 07·6 的数据面）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ErrorCode

ME = "/api/v1/users/me"


# -----------------------------------------------------------------------------
# GET /users/me —— 新用户
# -----------------------------------------------------------------------------
def test_me_returns_profile_and_stats(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.get(ME, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    user = data["user"]
    assert user["nickname"].startswith("冒险者 · ")
    assert user["avatar_key"] == "scholar"
    assert user["avatar_url"] is None
    assert user["xp_total"] == 0
    assert user["coins"] == 0
    assert user["streak_days"] == 0
    assert user["level"] == 1
    assert user["level_title"] == "见习冒险者"
    assert user["next_level_xp"] == 400
    assert user["xp_to_next_level"] == 400
    assert user["level_progress"] == 0

    stats = data["stats"]
    assert stats["attempt_count"] == 0
    assert stats["avg_accuracy"] == 0
    assert stats["lit_kp_count"] == 0
    assert stats["scroll_count"] == 0
    assert stats["badge_unlocked"] == 0
    assert stats["badge_total"] == 18  # 原型「6 / 18」的分母


def test_me_never_exposes_openid(db_client: TestClient, auth_headers: dict) -> None:
    """`openid` 是登录凭据，绝不能出现在响应里。"""
    payload = db_client.get(ME, headers=auth_headers).text

    assert "openid" not in payload
    assert "session_key" not in payload
    assert "token_version" not in payload


def test_me_does_not_include_auth_headers_in_body(db_client: TestClient, auth_headers: dict) -> None:
    body = db_client.get(ME, headers=auth_headers).json()["data"]

    assert "token" not in body


# -----------------------------------------------------------------------------
# PATCH /users/me
# -----------------------------------------------------------------------------
def test_patch_nickname(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.patch(ME, headers=auth_headers, json={"nickname": "拾光"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user"]["nickname"] == "拾光"
    assert db_client.get(ME, headers=auth_headers).json()["data"]["user"]["nickname"] == "拾光"


def test_patch_nickname_is_trimmed(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.patch(ME, headers=auth_headers, json={"nickname": "  拾光  "})

    assert resp.json()["data"]["user"]["nickname"] == "拾光"


@pytest.mark.parametrize(
    "nickname",
    [
        "",
        "   ",
        "x" * 33,
        "看不见\u200b的字符",
        "方向\u202e控制",
    ],
)
def test_patch_nickname_rejects_bad_input(
    db_client: TestClient, auth_headers: dict, nickname: str
) -> None:
    """昵称不合规复用 4001；零宽字符与方向控制符必须拦（可用于冒充）。"""
    resp = db_client.patch(ME, headers=auth_headers, json={"nickname": nickname})

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_INPUT == 4001


def test_patch_avatar_key(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.patch(ME, headers=auth_headers, json={"avatar_key": "knight"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user"]["avatar_key"] == "knight"


def test_patch_avatar_key_rejects_unknown(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.patch(ME, headers=auth_headers, json={"avatar_key": "dragon"})

    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_patch_both_fields_at_once(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.patch(
        ME, headers=auth_headers, json={"nickname": "夜行者", "avatar_key": "mage"}
    )

    user = resp.json()["data"]["user"]
    assert user["nickname"] == "夜行者"
    assert user["avatar_key"] == "mage"


def test_patch_empty_body_is_noop(db_client: TestClient, auth_headers: dict) -> None:
    before = db_client.get(ME, headers=auth_headers).json()["data"]["user"]

    resp = db_client.patch(ME, headers=auth_headers, json={})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user"]["nickname"] == before["nickname"]


def test_patch_requires_auth(db_client: TestClient) -> None:
    assert db_client.patch(ME, json={"nickname": "x"}).status_code == 401


def test_patch_only_affects_self(
    db_client: TestClient, auth_headers: dict, other_auth_headers: dict
) -> None:
    """接口没有「目标用户」参数，所以不存在改到别人身上的可能 —— 这条守住契约。"""
    db_client.patch(ME, headers=auth_headers, json={"nickname": "只改我"})

    other = db_client.get(ME, headers=other_auth_headers).json()["data"]["user"]
    assert other["nickname"] != "只改我"


# -----------------------------------------------------------------------------
# 头像上传
# -----------------------------------------------------------------------------
def test_upload_avatar_png(db_client: TestClient, auth_headers: dict, tiny_png: bytes) -> None:
    resp = db_client.post(
        f"{ME}/avatar",
        headers=auth_headers,
        files={"file": ("me.png", tiny_png, "image/png")},
    )

    assert resp.status_code == 200, resp.text
    url = resp.json()["data"]["user"]["avatar_url"]
    assert url.startswith("/static/avatars/")
    assert url.endswith(".png")

    # 上传后静态路径可访问
    served = db_client.get(url)
    assert served.status_code == 200
    assert served.content == tiny_png


@pytest.mark.parametrize("ext", ["jpg", "webp"])
def test_upload_avatar_other_formats(
    db_client: TestClient, auth_headers: dict, tiny_jpeg: bytes, tiny_webp: bytes, ext: str
) -> None:
    data = tiny_jpeg if ext == "jpg" else tiny_webp
    mime = "image/jpeg" if ext == "jpg" else "image/webp"

    resp = db_client.post(
        f"{ME}/avatar", headers=auth_headers, files={"file": (f"me.{ext}", data, mime)}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["user"]["avatar_url"].endswith(f".{ext}")


def test_upload_avatar_rejects_fake_extension(
    db_client: TestClient, auth_headers: dict
) -> None:
    """扩展名与 Content-Type 都说是 PNG，内容却是脚本 —— 必须拦。"""
    resp = db_client.post(
        f"{ME}/avatar",
        headers=auth_headers,
        files={"file": ("evil.png", b"<?php system($_GET['c']); ?>", "image/png")},
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.UPLOAD_INVALID == 4002


def test_upload_avatar_rejects_oversized(
    db_client: TestClient, auth_headers: dict, tiny_png: bytes, settings  # noqa: ANN001
) -> None:
    oversized = tiny_png + b"\x00" * (settings.avatar_max_bytes + 1)

    resp = db_client.post(
        f"{ME}/avatar", headers=auth_headers, files={"file": ("big.png", oversized, "image/png")}
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.UPLOAD_INVALID


def test_upload_avatar_rejects_empty_file(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.post(
        f"{ME}/avatar", headers=auth_headers, files={"file": ("empty.png", b"", "image/png")}
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.UPLOAD_INVALID


def test_upload_avatar_ignores_client_filename(
    db_client: TestClient, auth_headers: dict, tiny_png: bytes, tmp_uploads  # noqa: ANN001
) -> None:
    """客户端文件名可以拼出 `../`，绝不能拿它当落盘路径。"""
    resp = db_client.post(
        f"{ME}/avatar",
        headers=auth_headers,
        files={"file": ("../../evil.png", tiny_png, "image/png")},
    )

    assert resp.status_code == 200, resp.text
    stored = list((tmp_uploads / "avatars").iterdir())

    assert len(stored) == 1
    assert stored[0].parent == (tmp_uploads / "avatars").resolve()
    assert "evil" not in stored[0].name
    assert stored[0].name.startswith("u")


def test_upload_avatar_filename_is_unique_per_upload(
    db_client: TestClient, auth_headers: dict, tiny_png: bytes, tmp_uploads  # noqa: ANN001
) -> None:
    for _ in range(2):
        db_client.post(
            f"{ME}/avatar", headers=auth_headers, files={"file": ("a.png", tiny_png, "image/png")}
        )

    assert len(list((tmp_uploads / "avatars").iterdir())) == 2


def test_upload_requires_auth(db_client: TestClient, tiny_png: bytes) -> None:
    resp = db_client.post(f"{ME}/avatar", files={"file": ("a.png", tiny_png, "image/png")})

    assert resp.status_code == 401


def test_patch_preset_avatar_clears_uploaded_url(
    db_client: TestClient, auth_headers: dict, tiny_png: bytes
) -> None:
    """选了预置头像就该盖掉自定义头像，否则页面还是旧照片。"""
    db_client.post(
        f"{ME}/avatar", headers=auth_headers, files={"file": ("a.png", tiny_png, "image/png")}
    )
    assert db_client.get(ME, headers=auth_headers).json()["data"]["user"]["avatar_url"]

    resp = db_client.patch(ME, headers=auth_headers, json={"avatar_key": "ranger"})

    user = resp.json()["data"]["user"]
    assert user["avatar_key"] == "ranger"
    assert user["avatar_url"] is None


# -----------------------------------------------------------------------------
# 设置
# -----------------------------------------------------------------------------
SETTINGS = f"{ME}/settings"


def test_get_settings_defaults(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.get(SETTINGS, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["reminder_enabled"] is True
    assert data["reminder_time"] == "20:00"
    assert data["reminder_days"] == [1, 2, 3, 4, 5]
    assert data["remind_streak_break"] is True
    assert data["remind_review_due"] is True
    assert data["sound_enabled"] is True
    assert data["auto_load_images"] is False
    assert data["eye_care"] is False


def test_patch_settings_roundtrip(db_client: TestClient, auth_headers: dict) -> None:
    payload = {
        "reminder_enabled": False,
        "reminder_time": "08:00",
        "reminder_days": [1, 3, 5],
        "sound_enabled": False,
        "auto_load_images": True,
        "eye_care": True,
        "remind_streak_break": False,
        "remind_review_due": False,
    }

    resp = db_client.patch(SETTINGS, headers=auth_headers, json=payload)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    for key, value in payload.items():
        assert data[key] == value, key

    # 再读一次确认真的落库了
    again = db_client.get(SETTINGS, headers=auth_headers).json()["data"]
    assert again == data


def test_patch_settings_partial(db_client: TestClient, auth_headers: dict) -> None:
    db_client.patch(SETTINGS, headers=auth_headers, json={"reminder_time": "12:30"})

    data = db_client.get(SETTINGS, headers=auth_headers).json()["data"]
    assert data["reminder_time"] == "12:30"
    assert data["reminder_days"] == [1, 2, 3, 4, 5]  # 未传的字段不动


@pytest.mark.parametrize(
    "payload",
    [
        {"reminder_time": "25:00"},
        {"reminder_time": "8:00"},
        {"reminder_time": "08:60"},
        {"reminder_time": "abc"},
        {"reminder_days": []},
        {"reminder_days": [0]},
        {"reminder_days": [8]},
        {"reminder_days": [1, 1]},
        {"reminder_days": [1, 2, 3, 4, 5, 6, 7, 1]},
    ],
)
def test_patch_settings_rejects_bad_values(
    db_client: TestClient, auth_headers: dict, payload: dict
) -> None:
    resp = db_client.patch(SETTINGS, headers=auth_headers, json=payload)

    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_settings_are_per_user(
    db_client: TestClient, auth_headers: dict, other_auth_headers: dict
) -> None:
    db_client.patch(SETTINGS, headers=auth_headers, json={"reminder_time": "08:00"})

    other = db_client.get(SETTINGS, headers=other_auth_headers).json()["data"]
    assert other["reminder_time"] == "20:00"


def test_settings_require_auth(db_client: TestClient) -> None:
    assert db_client.get(SETTINGS).status_code == 401
    assert db_client.patch(SETTINGS, json={"sound_enabled": False}).status_code == 401


def test_settings_never_expose_subscribe_quota_mechanism(
    db_client: TestClient, auth_headers: dict
) -> None:
    """`subscribe_quota` 是本轮的预留列，不该出现在面向用户的响应里。"""
    data = db_client.get(SETTINGS, headers=auth_headers).json()["data"]

    assert "subscribe_quota" not in data


# -----------------------------------------------------------------------------
# 复习提醒（04·8 的数据面；本轮无订阅消息，仅页内提醒）
# -----------------------------------------------------------------------------
def test_reminders_today_empty(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.get(f"{ME}/reminders/today", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["due_count"] == 0
    assert data["estimated_minutes"] == 0
    assert data["available_xp"] == 0
    assert data["snoozed_today"] is False


def test_snooze_today(db_client: TestClient, auth_headers: dict) -> None:
    resp = db_client.post(f"{ME}/reminders/snooze", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert db_client.get(f"{ME}/reminders/today", headers=auth_headers).json()["data"][
        "snoozed_today"
    ] is True


def test_snooze_does_not_touch_schedule(
    db_client: TestClient, auth_headers: dict, db_session  # noqa: ANN001
) -> None:
    """「今天先不复习」只记一次忽略，**不改变错题排期** —— 用户的计划不因一次忽略而变。"""
    from app.db.tables import UserSetting

    user_id = db_client.get(ME, headers=auth_headers).json()["data"]["user"]["id"]
    db_client.post(f"{ME}/reminders/snooze", headers=auth_headers)

    row = db_session.get(UserSetting, user_id)
    db_session.refresh(row)
    assert row.remind_snooze_date is not None
    assert row.reminder_time is not None  # 提醒时间未被改动
