"""用户资料、设置与复习提醒的读接口。

## 一个刻意的空实现

`GET /users/me/dashboard`、`/knowledge-tree`、`/scrolls`、`/wrong-questions`、
`/badges` 属于 Phase D，本阶段**不建占位路由**。返回假数据的占位接口比
「404」更危险：前端联调时会以为已经通了，直到真正接数据才发现口径不对。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.constants import NICKNAME_UI_MAX_LEN
from app.core.exceptions import invalid_input
from app.core.response import ok
from app.models.user import (
    ProfileUpdateRequest,
    SnoozeResponse,
    UserSettingsUpdateRequest,
)
from app.services import user_service
from app.utils.crypto import NicknameError, normalize_nickname

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
def read_me(user: CurrentUser, session: DbSession) -> dict:
    """个人中心（原型 04·1）的全部数据：身份 + 进度 + 三宫格 + 入口计数。

    一个接口而不是四个：这些数字在同一个屏幕上，拆开只会让首屏出现
    「身份已到、计数还没到」的中间态。
    """
    return ok(user_service.build_profile(session, user).model_dump(mode="json"))


@router.patch("/me")
def update_me(
    payload: ProfileUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """改昵称与预置头像。"""
    if payload.nickname is not None:
        try:
            payload.nickname = normalize_nickname(
                payload.nickname, max_len=NICKNAME_UI_MAX_LEN
            )
        except NicknameError as exc:
            # 昵称不合规复用 4001（方案 §4.6）；4000 留给「参数形状不对」
            raise invalid_input(str(exc)) from exc

    profile = user_service.update_profile(session, user, payload)
    return ok({"user": profile.model_dump(mode="json")})


@router.post("/me/avatar")
def upload_avatar(
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> dict:
    """上传自定义头像（multipart）。

    **同步 def 而不是 async**：整条鉴权 + 落库链路都是同步的，
    用 async 会让这些阻塞调用跑在事件循环里，反而更容易拖慢其他请求。
    同步 def 会被 FastAPI 丢进线程池，与既有路由一致。

    读取时按 `max_bytes + 1` 截断：多读 1 字节就足以判定「超限」，
    不必把一个 1 GB 的垃圾先全量读进内存。
    """
    settings = get_settings()
    limit = max(1, int(settings.avatar_max_bytes))
    data = file.file.read(limit + 1)

    profile = user_service.save_avatar(session, user, data=data, max_bytes=limit)
    return ok({"user": profile.model_dump(mode="json")})


@router.get("/me/settings")
def read_settings(user: CurrentUser, session: DbSession) -> dict:
    """设置页（原型 07·5 / 07·6）。"""
    return ok(user_service.get_settings_public(session, user).model_dump(mode="json"))


@router.patch("/me/settings")
def update_settings(
    payload: UserSettingsUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """改设置。只提交传了的字段。"""
    return ok(user_service.update_settings(session, user, payload).model_dump(mode="json"))


@router.get("/me/reminders/today")
def read_reminders(user: CurrentUser, session: DbSession) -> dict:
    """今日复习提醒（原型 04·8 的三宫格）。

    **本轮不做订阅消息下发**（无模板 ID），所以这里只提供数据，
    入口由大厅与个人中心页内提示承担。
    """
    payload = user_service.reminders_today(session, user)
    return ok(payload.model_dump(mode="json"))


@router.post("/me/reminders/snooze")
def snooze_reminders(user: CurrentUser, session: DbSession) -> dict:
    """「今天先不复习」。

    只写 `remind_snooze_date`，**不改动任何错题的排期** ——
    用户忽略一次提醒，不该被解读成「复习计划推迟一天」。
    """
    user_service.snooze_today(session, user)
    return ok(SnoozeResponse(snoozed_today=True).model_dump(mode="json"))
