"""冒险者档案四个读接口的测试（原型 04 的 3 / 4 / 7 / 9 屏）。

## 这些接口都是**只读聚合**，但错法很隐蔽

它们不改数据，所以「跑不通」会很明显 —— 真正危险的是**算错**：
柱子的窗口差一天、上一周期的数据漏进本周、知识树的「未开始」被算成「0% 掌握」。
这些在界面上都不报错，只是数字不对，而用户看到的「我进步了」就是这些数字。

所以每个数字都单独钉一个用例，边界（第 7 天 / 第 8 天、90% 与 89%）各钉一次。

## 数据全部由**真实的写入路径**产生

挑战走 `POST /attempts`（服务端权威结算），知识统计与错题队列由它内部的
`growth_service` 写入。这样读接口面对的库状态与线上完全同形 ——
手工插 `user_knowledge_stats` 行会让读接口与写接口各自有一套口径而测试全绿。

代价是必须显式处理两件事：

1. **卷轴要先提交**：`db_session` 建完卷轴要让接口的会话看得见它。
2. **写完再读要先结束事务**：`db_session` 是 REPEATABLE READ，第一次读就定下了
   快照。接口（另一个连接）写完之后，同一个会话再读看到的仍是旧快照 ——
   `expire_all()` 也救不了。所以下面凡是「HTTP 写 → db_session 读」的地方
   都先 `db_session.rollback()`。这不是洁癖，实测踩过。

## 时间一律用**业务日**构造

`at(-6)` 表示「业务时区 6 天前的上午 10 点」。用 UTC 直接减天数会在
北京时间 0–8 点之间算错一天 —— 而那个错法只在特定时段跑测试时才出现。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.constants import BADGE_TOTAL
from app.db.tables import User, UserBadge, UserKnowledgeStat
from app.utils.timeutil import business_date, utcnow
from tests.helpers import (
    WEEKDAY_LABELS,
    answer_n,
    at,
    current_user_id,
    make_quiz,
    set_due,
    settle,
    wrong_rows,
)


# -----------------------------------------------------------------------------
# 鉴权：四个接口都不许匿名访问
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/users/me/dashboard",
        "/api/v1/users/me/knowledge-tree",
        "/api/v1/users/me/wrong-questions",
        "/api/v1/users/me/badges",
    ],
)
def test_archive_endpoints_require_auth(db_client, path: str) -> None:
    resp = db_client.get(path)

    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == 4010


# =============================================================================
# 04·3 数据看板
# =============================================================================
def test_dashboard_is_seven_bars_ending_today(db_client, auth_headers) -> None:
    """柱状图恒为最近 7 天，最后一根是今天，日期升序。"""
    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["range"] == "7d"
    assert len(body["bars"]) == 7

    today = business_date()
    expected_dates = [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]
    assert [bar["date"] for bar in body["bars"]] == expected_dates

    for index, bar in enumerate(body["bars"]):
        day = today - timedelta(days=6 - index)
        assert bar["label"] == WEEKDAY_LABELS[day.weekday()]
        assert bar["count"] == 0


def test_dashboard_counts_only_the_last_seven_days(
    db_client, db_session, auth_headers
) -> None:
    """第 8 天前的答题不进柱子，也不进 `week_answers`。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"))  # 一次结算写 2 行作答

    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=at(0),
    )
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("wrong", "wrong"), finished_at=at(-6),
    )
    # 第 7 天前的一次：落在窗口之外
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("wrong", "wrong"), finished_at=at(-7),
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["week_answers"] == 4, "窗口是 [今天-6, 今天]，第 7 天前的要排除"
    assert [bar["count"] for bar in body["bars"]] == [2, 0, 0, 0, 0, 0, 2]


def test_dashboard_week_delta_is_none_without_a_previous_period(
    db_client, db_session, auth_headers
) -> None:
    """上一周期一题都没有时不给对比 —— `None`，不是 0%、也不是 +100%。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0))

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["week_answers"] == 1
    assert body["week_delta_percent"] is None
    assert body["accuracy_delta"] is None
    assert body["duration_delta_ms"] is None


def test_dashboard_week_delta_percent_compares_equal_length_windows(
    db_client, db_session, auth_headers
) -> None:
    """上一周期 10 道、本周 12 道 → +20%。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)

    answer_n(db_client, auth_headers, db_session, quiz, times=10, day=-8, outcomes=("correct",))
    answer_n(db_client, auth_headers, db_session, quiz, times=12, day=-1, outcomes=("correct",))

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["week_answers"] == 12
    assert body["week_delta_percent"] == 20


def test_dashboard_accuracy_is_weighted_by_question_count(
    db_client, db_session, auth_headers
) -> None:
    """正确率按**题量加权**，不是「每局正确率的算术平均」。

    一局 4/4 与一局 1/2：加权是 5/6 = 83%，算术平均则会被算成 75%。
    按题量加权才是「我做对了多少题」这个说法的本意。
    """
    user_id = current_user_id(db_client, auth_headers)
    long_quiz = make_quiz(db_session, user_id, title="长卷轴", kps=("甲", "乙", "丙", "丁"))
    short_quiz = make_quiz(db_session, user_id, title="短卷轴", kps=("戊", "己"))

    settle(
        db_client, auth_headers, db_session, long_quiz,
        outcomes=("correct",) * 4, finished_at=at(-2),
    )
    settle(
        db_client, auth_headers, db_session, short_quiz,
        outcomes=("correct", "wrong"), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["accuracy"] == 83, "5 / 6 = 83%"


def test_dashboard_accuracy_delta_is_percentage_points(
    db_client, db_session, auth_headers
) -> None:
    """正确率的变化是**百分点之差**，不是百分比之差。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"))

    # 上一周期：1/2 = 50%
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=at(-9),
    )
    # 本周期：2/2 = 100%
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "correct"), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["accuracy"] == 100
    assert body["accuracy_delta"] == 50, "100 − 50 = 50 个百分点"


def test_dashboard_duration_delta_is_positive_when_slower(
    db_client, db_session, auth_headers
) -> None:
    """用时变化：正数 = **变慢**（文案由前端按符号拼，语义由后端定死）。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)

    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct",), finished_at=at(-9), duration_ms=30_000,
    )
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct",), finished_at=at(-1), duration_ms=45_000,
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["avg_duration_ms"] == 45_000
    assert body["duration_delta_ms"] == 15_000


def test_dashboard_domains_exclude_never_answered_ones(
    db_client, db_session, auth_headers
) -> None:
    """看板的领域条只列**答过题**的领域 —— 0% 的进度条不传达任何信息。"""
    user_id = current_user_id(db_client, auth_headers)
    answered = make_quiz(db_session, user_id, title="答过的", kps=("RAG 基本定义",))
    make_quiz(db_session, user_id, title="没答过的", kps=("完全没碰的领域",))

    settle(
        db_client, auth_headers, db_session, answered,
        outcomes=("wrong",), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert [item["name"] for item in body["domains"]] == ["RAG 基本定义"]
    assert body["domains"][0]["mastery"] == 0
    assert body["domains"][0]["total_count"] == 1


def test_dashboard_domains_sorted_by_mastery_then_name(
    db_client, db_session, auth_headers
) -> None:
    """同掌握度时按名称排序 —— 顺序必须稳定，否则每次刷新顺序都在跳。

    用「文献检索 / 注意力机制」而不是「甲 / 乙」：这两个名字在**码点序与拼音序
    下顺序一致**，所以这条用例断言的是「稳定」，不会顺带把某个语言环境下的
    排序规则钉进测试里（那属于库的排序规则，不属于业务）。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("注意力机制", "文献检索"))

    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "correct"), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert [item["name"] for item in body["domains"]] == ["文献检索", "注意力机制"]


def test_dashboard_has_data_false_for_a_brand_new_user(db_client, auth_headers) -> None:
    """新用户：`has_data=False`，前端据此出空态而不是画一排 0。"""
    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["has_data"] is False
    assert body["range_has_data"] is False
    assert body["week_answers"] == 0
    assert body["domains"] == []


def test_dashboard_range_has_data_tells_history_apart_from_the_window(
    db_client, db_session, auth_headers
) -> None:
    """「有档案」与「这个区间有记录」是两件事，前端要靠它决定要不要显示 0。

    一个 20 天前玩过、最近一周没来的用户：`has_data=True`（他确实有档案，
    不该看到「还没有开始冒险」），但 7 天窗口是空的 —— 而空窗口里正确率与
    平均用时都是 0，直接渲染就是「正确率 0% · 用时 0 秒」，读起来像考砸了。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-20))

    week = db_client.get(
        "/api/v1/users/me/dashboard?range=7d", headers=auth_headers
    ).json()["data"]
    month = db_client.get(
        "/api/v1/users/me/dashboard?range=30d", headers=auth_headers
    ).json()["data"]

    assert week["has_data"] is True, "他有档案"
    assert week["range_has_data"] is False, "但这一周确实没来"
    assert week["accuracy"] == 0 and week["avg_duration_ms"] == 0, "空窗口的两个数都是 0"
    assert month["range_has_data"] is True, "30 天窗口里那一局在"


def test_dashboard_30d_widens_the_window_but_bars_stay_seven(
    db_client, db_session, auth_headers
) -> None:
    """`range` 只影响正确率 / 用时的窗口，柱子恒为 7 根（原型图注的要求）。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"))

    # 20 天前的一局：7 天窗口外、30 天窗口内
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=at(-20),
    )
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "correct"), finished_at=at(-1),
    )

    week = db_client.get(
        "/api/v1/users/me/dashboard?range=7d", headers=auth_headers
    ).json()["data"]
    month = db_client.get(
        "/api/v1/users/me/dashboard?range=30d", headers=auth_headers
    ).json()["data"]

    assert week["accuracy"] == 100, "7 天窗口只看最后一局"
    assert month["accuracy"] == 75, "30 天窗口把 20 天前那局也算进来（3 / 4）"
    assert len(week["bars"]) == len(month["bars"]) == 7
    assert week["bars"] == month["bars"]
    assert month["range"] == "30d"


def test_dashboard_rejects_an_unknown_range(db_client, auth_headers) -> None:
    resp = db_client.get("/api/v1/users/me/dashboard?range=1y", headers=auth_headers)

    assert resp.status_code == 400
    assert resp.json()["code"] == 4000


def test_dashboard_shows_only_your_own_data(
    db_client, db_session, auth_headers, other_auth_headers
) -> None:
    """另一个用户的数据一行都不能漏进来。"""
    other_id = current_user_id(db_client, other_auth_headers)
    other_quiz = make_quiz(db_session, other_id, title="别人的卷轴", kps=("别人的领域",))
    settle(
        db_client, other_auth_headers, db_session, other_quiz,
        outcomes=("correct",), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/dashboard", headers=auth_headers).json()["data"]

    assert body["has_data"] is False
    assert body["domains"] == []
    assert body["week_answers"] == 0


# =============================================================================
# 04·4 知识树
# =============================================================================
def test_tree_lists_never_answered_domains_as_not_started(
    db_client, db_session, auth_headers
) -> None:
    """领了卷轴但没答的领域是**未开始**，不是「0% 掌握」（方案 §8.3 先判空）。"""
    user_id = current_user_id(db_client, auth_headers)
    make_quiz(db_session, user_id, title="待挑战的卷轴", kps=("评测",))

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]

    assert [node["name"] for node in body["nodes"]] == ["评测"]
    node = body["nodes"][0]
    assert node["state"] == "not_started"
    assert node["total_count"] == 0
    assert node["correct_count"] == 0
    assert node["mastery"] == 0
    assert body["not_started_count"] == 1
    assert body["lit_count"] == 0
    assert body["growing_count"] == 0


def test_tree_state_thresholds(db_client, db_session, auth_headers) -> None:
    """90% 点亮；89% 仍是进行中（阈值是 `>=`，边界必须钉住）。"""
    user_id = current_user_id(db_client, auth_headers)
    lit_quiz = make_quiz(db_session, user_id, title="点亮卷轴", kps=("甲",))
    growing_quiz = make_quiz(db_session, user_id, title="进行中卷轴", kps=("乙",))

    # 甲：9 对 1 错 → 90% → 点亮
    answer_n(db_client, auth_headers, db_session, lit_quiz, times=9, day=-1, outcomes=("correct",))
    settle(db_client, auth_headers, db_session, lit_quiz, outcomes=("wrong",), finished_at=at(-1))

    # 乙：8 对 1 错 → 8/9 = 88.9 → 89% → 进行中
    answer_n(
        db_client, auth_headers, db_session, growing_quiz,
        times=8, day=-1, outcomes=("correct",),
    )
    settle(
        db_client, auth_headers, db_session, growing_quiz,
        outcomes=("wrong",), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]
    by_name = {node["name"]: node for node in body["nodes"]}

    assert by_name["甲"]["mastery"] == 90
    assert by_name["甲"]["state"] == "lit"
    assert by_name["乙"]["mastery"] == 89
    assert by_name["乙"]["state"] == "growing"
    assert body["lit_count"] == 1
    assert body["growing_count"] == 1


def test_tree_counts_add_up_to_nodes(db_client, db_session, auth_headers) -> None:
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"))
    make_quiz(db_session, user_id, title="没答的", kps=("丙",))
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=at(-1),
    )

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]

    assert len(body["nodes"]) == 3
    assert (
        body["lit_count"] + body["growing_count"] + body["not_started_count"]
        == len(body["nodes"])
    )


def test_tree_suggestion_points_at_the_most_promising_growing_domain(
    db_client, db_session, auth_headers
) -> None:
    """建议点名**最接近点亮**的那个领域，并把领域名单独给出供前端高亮。"""
    user_id = current_user_id(db_client, auth_headers)
    # 一个领域一份单题卷轴，好让两个领域的正确率互不牵连
    jia = make_quiz(db_session, user_id, title="甲卷", kps=("甲",))
    yi = make_quiz(db_session, user_id, title="乙卷", kps=("乙",))

    # 甲 1/2 = 50%、乙 3/4 = 75% → 建议点名乙（更接近点亮）
    settle(db_client, auth_headers, db_session, jia, outcomes=("correct",), finished_at=at(-1))
    settle(db_client, auth_headers, db_session, jia, outcomes=("wrong",), finished_at=at(-1))
    answer_n(db_client, auth_headers, db_session, yi, times=3, day=-1, outcomes=("correct",))
    settle(db_client, auth_headers, db_session, yi, outcomes=("wrong",), finished_at=at(-1))

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]
    by_name = {node["name"]: node for node in body["nodes"]}

    assert by_name["乙"]["mastery"] == 75
    assert body["next_target"] == "乙"
    assert "乙" in body["suggestion"]
    assert "75" in body["suggestion"]


def test_tree_suggestion_names_a_not_started_domain_when_nothing_is_growing(
    db_client, db_session, auth_headers
) -> None:
    """没有「进行中」时，建议指向一个尚未开始的领域。"""
    user_id = current_user_id(db_client, auth_headers)
    make_quiz(db_session, user_id, kps=("评测",))

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]

    assert body["next_target"] == "评测"
    assert "评测" in body["suggestion"]


def test_tree_says_nothing_when_there_is_nothing_to_suggest(
    db_client, db_session, auth_headers
) -> None:
    """全部点亮（或根本没有领域）时宁可不说，也不编一句「继续加油」。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1))

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]

    assert body["nodes"][0]["state"] == "lit"
    assert body["suggestion"] == ""
    assert body["next_target"] is None


def test_tree_is_empty_for_a_new_user(db_client, auth_headers) -> None:
    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]

    assert body["nodes"] == []
    assert body["suggestion"] == ""
    assert body["next_target"] is None


def test_tree_shows_only_your_own_domains(
    db_client, db_session, auth_headers, other_auth_headers
) -> None:
    other_id = current_user_id(db_client, other_auth_headers)
    make_quiz(db_session, other_id, title="别人的卷轴", kps=("别人的领域",))

    body = db_client.get("/api/v1/users/me/knowledge-tree", headers=auth_headers).json()["data"]

    assert body["nodes"] == []


def test_tree_and_growth_writer_agree(db_client, db_session, auth_headers) -> None:
    """读接口与写接口必须对同一份数据给出同一套数字。

    先走真实的结算写入，再用服务直读（不经 HTTP）—— 比的是两侧的口径，
    不是「路由层有没有把数字凑对」。
    """
    from app.services import archive_service

    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲",))
    for outcome in ("correct", "correct", "correct", "correct", "wrong"):
        settle(db_client, auth_headers, db_session, quiz, outcomes=(outcome,), finished_at=at(-1))

    # REPEATABLE READ：接口（另一连接）写过之后，本会话要先结束事务才看得到
    db_session.rollback()
    stat = db_session.query(UserKnowledgeStat).one()
    node = archive_service.knowledge_tree(db_session, db_session.get(User, user_id)).nodes[0]

    assert (stat.total_count, stat.correct_count) == (5, 4), "写入侧：5 题 4 对"
    assert (node.total_count, node.correct_count, node.mastery) == (5, 4, 80)
    assert node.state == "growing"


# =============================================================================
# 04·7 旧识重温（错题本）
# =============================================================================
def test_wrong_questions_are_queued_by_a_wrong_answer(
    db_client, db_session, auth_headers
) -> None:
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, title="RAG 闯关", kps=("向量检索",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(0))

    body = db_client.get("/api/v1/users/me/wrong-questions", headers=auth_headers).json()["data"]

    assert body["total_count"] == 1
    assert body["due_count"] == 0, "刚答错的题 1 天后才到期"
    item = body["items"][0]
    assert item["knowledge_point"] == "向量检索"
    assert item["quiz_title"] == "RAG 闯关"
    assert item["wrong_count"] == 1
    assert item["stage"] == 0
    assert item["due"] is False
    assert "第 1 题" in item["stem"]


def test_wrong_questions_due_filter_returns_only_due_ones(
    db_client, db_session, auth_headers
) -> None:
    """`due=1` 只回到期的；不传则回全部（含未到期）。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"))
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("wrong", "wrong"), finished_at=at(0),
    )

    db_session.rollback()
    rows = wrong_rows(db_session, user_id)
    set_due(db_session, rows[0], days=-1)  # 已过期 → 到期
    set_due(db_session, rows[1], days=3)  # 3 天后

    all_items = db_client.get(
        "/api/v1/users/me/wrong-questions", headers=auth_headers
    ).json()["data"]
    due_items = db_client.get(
        "/api/v1/users/me/wrong-questions?due=1", headers=auth_headers
    ).json()["data"]

    assert all_items["total_count"] == 2
    assert all_items["due_count"] == 1
    assert len(all_items["items"]) == 2

    assert due_items["due_count"] == 1
    assert due_items["total_count"] == 2, "队列总数与筛选无关，始终是队列的真实大小"
    assert len(due_items["items"]) == 1
    assert due_items["items"][0]["due"] is True


def test_wrong_questions_sorted_by_next_review(db_client, db_session, auth_headers) -> None:
    """按到期时间升序 —— 原型的顺序是「今天到期、今天到期、明天、3 天后」。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙", "丙"))
    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("wrong", "wrong", "wrong"), finished_at=at(0),
    )

    db_session.rollback()
    rows = wrong_rows(db_session, user_id)
    set_due(db_session, rows[0], days=3)  # 甲
    set_due(db_session, rows[1], days=1)  # 乙
    set_due(db_session, rows[2], days=-2)  # 丙 → 最紧急

    body = db_client.get("/api/v1/users/me/wrong-questions", headers=auth_headers).json()["data"]

    assert [item["knowledge_point"] for item in body["items"]] == ["丙", "乙", "甲"]


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (-3, "已经到期"),
        (0, "今天"),
        (1, "明天"),
        (4, "4 天后"),
    ],
)
def test_wrong_question_due_label_is_derived_in_business_timezone(
    db_client, db_session, auth_headers, days: int, expected: str
) -> None:
    """到期说法由后端按**业务时区**算：客户端时区不同的人也会看到同样的天数。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(0))

    db_session.rollback()
    set_due(db_session, wrong_rows(db_session, user_id)[0], days=days)

    body = db_client.get("/api/v1/users/me/wrong-questions", headers=auth_headers).json()["data"]

    assert body["items"][0]["next_review_label"] == expected


def test_wrong_question_next_review_at_carries_a_utc_offset(
    db_client, db_session, auth_headers
) -> None:
    """日期串必须带偏移量，否则 JS 会按本地时间解释，跨零点就错一天。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(0))

    body = db_client.get("/api/v1/users/me/wrong-questions", headers=auth_headers).json()["data"]

    assert body["items"][0]["next_review_at"].endswith("+00:00")


def test_mastered_wrong_questions_leave_the_queue(
    db_client, db_session, auth_headers
) -> None:
    """连续答对到「移出阶段」即离开队列，也不再出现在列表里。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(-3))
    # 连续两次答对 → 阶段推进到移出阈值
    for _ in range(2):
        settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1))

    db_session.rollback()
    assert wrong_rows(db_session, user_id)[0].mastered is True, "写入侧：应已移出队列"

    body = db_client.get("/api/v1/users/me/wrong-questions", headers=auth_headers).json()["data"]

    assert body["total_count"] == 0
    assert body["items"] == []


def test_wrong_questions_show_only_yours(
    db_client, db_session, auth_headers, other_auth_headers
) -> None:
    other_id = current_user_id(db_client, other_auth_headers)
    quiz = make_quiz(db_session, other_id, title="别人的卷轴", kps=("别人的领域",))
    settle(db_client, other_auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(0))

    body = db_client.get("/api/v1/users/me/wrong-questions", headers=auth_headers).json()["data"]

    assert body["total_count"] == 0


# =============================================================================
# 04·9 勋章墙
# =============================================================================
def test_badges_return_all_eighteen_in_registry_order(db_client, auth_headers) -> None:
    """未解锁的也带名称与条件（原型要求「保留轮廓与名称，让用户知道还能追求什么」）。"""
    body = db_client.get("/api/v1/users/me/badges", headers=auth_headers).json()["data"]

    assert body["total"] == BADGE_TOTAL == 18
    assert body["unlocked_count"] == 0
    assert len(body["items"]) == 18
    assert body["items"][0] == {
        "key": "first_quest",
        "name": "初次启程",
        "desc": "完成首局挑战",
        "icon": "启",
        "tier": "gold",
        "unlocked": False,
        "unlocked_at": None,
    }


def test_badges_reflect_unlocked_rows(db_client, db_session, auth_headers) -> None:
    user_id = current_user_id(db_client, auth_headers)
    moment = utcnow()
    db_session.add(UserBadge(user_id=user_id, badge_key="first_quest", unlocked_at=moment))
    db_session.add(
        UserBadge(user_id=user_id, badge_key="hundred_questions", unlocked_at=moment)
    )
    db_session.commit()

    body = db_client.get("/api/v1/users/me/badges", headers=auth_headers).json()["data"]
    unlocked = {item["key"] for item in body["items"] if item["unlocked"]}

    assert unlocked == {"first_quest", "hundred_questions"}
    assert body["unlocked_count"] == 2


def test_badge_unlocked_at_carries_a_utc_offset(db_client, db_session, auth_headers) -> None:
    user_id = current_user_id(db_client, auth_headers)
    db_session.add(
        UserBadge(user_id=user_id, badge_key="first_quest", unlocked_at=utcnow())
    )
    db_session.commit()

    body = db_client.get("/api/v1/users/me/badges", headers=auth_headers).json()["data"]
    item = next(entry for entry in body["items"] if entry["key"] == "first_quest")

    assert item["unlocked_at"].endswith("+00:00")
