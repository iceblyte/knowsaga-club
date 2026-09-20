"""用户资料、设置、复习提醒与冒险者档案的读写接口。

## 档案各屏

| 屏 | 接口 | 契约 |
|---|---|---|
| 04·3 数据看板 | `GET /users/me/dashboard` | `models/archive.py` |
| 04·4 知识树 | `GET /users/me/knowledge-tree` | 同上 |
| 04·5 历史卷轴 | `GET /users/me/scrolls` | 同上 |
| 04·6 卷轴详情 | `GET /users/me/scrolls/{attempt_id}` | 同上 |
| 04·7 旧识重温 | `GET /users/me/wrong-questions` | 同上 |
| 04·9 勋章墙 | `GET /users/me/badges` | 同上 |

四个只读聚合的业务逻辑在 `archive_service` 与 `badge_service`；
历史卷轴那三个（列表 / 详情 / 删除）在 `scroll_service`。
路由层只负责把查询参数翻译成调用参数、把结果包成统一响应体。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Path, Query, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.constants import NICKNAME_UI_MAX_LEN, SCROLL_PAGE_SIZE, SCROLL_PAGE_SIZE_MAX
from app.core.exceptions import invalid_input
from app.core.response import ok
from app.models.archive import DashboardRange
from app.models.user import (
    ProfileUpdateRequest,
    SnoozeResponse,
    UserSettingsUpdateRequest,
)
from app.services import archive_service, badge_service, scroll_service, user_service
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


# -----------------------------------------------------------------------------
# 冒险者档案（原型 04 的四屏）
# -----------------------------------------------------------------------------
@router.get("/me/dashboard")
def read_dashboard(
    user: CurrentUser,
    session: DbSession,
    range_: Annotated[DashboardRange, Query(alias="range")] = "7d",
) -> dict:
    """数据看板（原型 04·3）。

    `range` 是 Python 关键字，所以参数名走 `alias`。用 `Literal` 而不是手工校验：
    非法值由 FastAPI 直接挡成 4000，不必在这里写一遍取值表。
    """
    payload = archive_service.dashboard(session, user, range_=range_)
    return ok(payload.model_dump(mode="json"))


@router.get("/me/knowledge-tree")
def read_knowledge_tree(user: CurrentUser, session: DbSession) -> dict:
    """知识树（原型 04·4）。节点含「还没碰过」的领域，三态由后端判定。"""
    payload = archive_service.knowledge_tree(session, user)
    return ok(payload.model_dump(mode="json"))


@router.get("/me/wrong-questions")
def read_wrong_questions(
    user: CurrentUser,
    session: DbSession,
    due: Annotated[int, Query(ge=0, le=1)] = 0,
) -> dict:
    """旧识重温（原型 04·7）。

    `due=1` 只回到期的题（复习关卡的组卷入口用它）；不传则回整个队列，
    页面自己按 `due` 标注两种胶囊。

    用 `int` + `ge/le` 而不是 `bool`：查询串里 `due=false` 在 `bool` 下会被
    Pydantic 解析成 `False` 但 `due=0` 也可以，而 `due=2` 会被静默当成真 ——
    显式限定 0/1 才能让写错的值报错而不是悄悄改变语义。
    """
    payload = archive_service.wrong_questions(session, user, due_only=bool(due))
    return ok(payload.model_dump(mode="json"))


@router.get("/me/badges")
def read_badges(user: CurrentUser, session: DbSession) -> dict:
    """勋章墙（原型 04·9）。恒返回全部 18 枚，未解锁的也带名称与条件。"""
    payload = badge_service.list_badges(session, user)
    return ok(payload.model_dump(mode="json"))


# -----------------------------------------------------------------------------
# 历史卷轴（原型 04 的 5 / 6 屏）
# -----------------------------------------------------------------------------
#: 挑战记录 ID 的路径参数。`ge=1` 让 `0` / 负数在进入业务层之前就被挡成 4000 ——
#: 否则它会被当成「一个不存在的 id」而报 4005，掩盖掉「参数写错了」这件事。
AttemptId = Annotated[int, Path(ge=1)]


@router.get("/me/scrolls")
def read_scrolls(
    user: CurrentUser,
    session: DbSession,
    domain: Annotated[str | None, Query(max_length=64)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=SCROLL_PAGE_SIZE_MAX)] = SCROLL_PAGE_SIZE,
) -> dict:
    """历史卷轴列表（原型 04·5）。

    **一项 = 一次挑战**，不是一份卷轴（方案 §5.5）。所以同一份卷轴重做
    几次就有几条记录，`attempt_no` 标出这是第几次重做。

    `size` 超上限直接报 4000 而不是静默截断：「我要了 500 条却只拿到 50 条」
    是个查不出来的现象，宁可当场说清。
    """
    payload = scroll_service.list_scrolls(
        session, user, domain=domain, page=page, size=size
    )
    return ok(payload.model_dump(mode="json"))


@router.get("/me/scrolls/{attempt_id}")
def read_scroll_detail(
    attempt_id: AttemptId,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """卷轴详情（原型 04·6）。

    题干 / 选项 / 答案 / 讲解都取自 `questions` —— 那张表**本身就是快照**，
    所以历史卷轴能无限期回看，不受后续重新出题影响。

    别人的记录与不存在的记录都回 4005「内容不存在或已删除」，
    不区分越权与不存在（否则错误码差异就成了探测数据是否存在的工具）。
    """
    payload = scroll_service.scroll_detail(session, user, attempt_id)
    return ok(payload.model_dump(mode="json"))


@router.delete("/me/scrolls/{attempt_id}")
def delete_scroll(
    attempt_id: AttemptId,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """删除一条历史记录（原型 04·5 的长按删除）。

    **软删除**：只把 `attempts.deleted_at` 写上时间戳，累计 XP / 正确率 /
    等级一概不变（需求 FR-B5）。硬删会连带 CASCADE 掉 `answers`，
    用户看到的是自己的成绩被改写 —— 见 `sql/03_attempts_deleted_at.sql`。

    重复删除报 4005：幂等由客户端忽略这个错误实现，服务端谎报成功
    会让「删错了」这件事无法被发现。
    """
    payload = scroll_service.delete_scroll(session, user, attempt_id)
    return ok(payload.model_dump(mode="json"))


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
