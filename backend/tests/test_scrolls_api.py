"""历史卷轴列表 / 详情 / 删除的测试（原型 04 的 5 / 6 屏）。

## 口径：一条记录 = **一次挑战**，不是一份卷轴

原型 04·5 每条写「正确率 80% · 5 题」而详情页带「重做」按钮，所以列表项
只能是「一局」；同一份卷轴重做三次就有三条记录（方案 §5.5）。本文件第一条
用例就把这件事钉死 —— 它是后面所有断言的前提，写错了别的都会跟着歪。

## 删除是**软删除**，而且必须不影响统计

需求 FR-B5：删除后从列表消失、但正确率 / 累计 XP / 等级不变。
正确率是**实时聚合**出来的，所以硬删会连带 `CASCADE` 掉 `answers`，
用户看到的是自己的成绩被改写。这条约束值一个专门的用例 ——
它正是「软删」这个决定存在的唯一理由。

## 数据全部由**真实写入路径**产生

挑战走 `POST /attempts`，与线上同形。两条必须记住的约定（见 `tests/helpers.py`）：
卷轴要先 `commit`；HTTP 写完再用 `db_session` 读之前要先 `rollback()`。
"""

from __future__ import annotations

from app.core.constants import SCROLL_PAGE_SIZE_MAX
from app.utils.timeutil import business_date
from tests.helpers import at, current_user_id, make_quiz, settle

SCROLLS = "/api/v1/users/me/scrolls"

#: 「今天」一个**必定已经过去**的时刻，给需要断言精确时刻的用例用。
#:
#: 别用 `at(0)`（默认今天 10:00）：`POST /attempts` 会把晚于服务端当前
#: 时刻的交卷时间夹到「现在」（见 `attempt_service._resolve_timing` 的防作弊
#: 守卫）。于是测试若在 **10:00 之前**运行，`at(0)` 就被夹走，断言里的
#: 时刻与「用时」都会跟着漂移 —— 这些用例只在下午才通过。这是 2026-09-20
#: 上午 09:21 跑闸门时抓到的（同一个坑 `test_badge_service` 已用
#: 「昨天 23:00」绕过，见那里的说明）。
#:
#: 0 点是业务日里唯一**无论几点运行都已过去**的整点，又仍属于「今天」，
#: 所以它可以承载「今天 HH:MM」这类精确断言。
TODAY_EARLY = at(0, hour=0)


def _scrolls(client, headers, **params) -> dict:
    resp = client.get(SCROLLS, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _detail(client, headers, attempt_id: str):
    return client.get(f"{SCROLLS}/{attempt_id}", headers=headers)


def _delete(client, headers, attempt_id: str):
    return client.delete(f"{SCROLLS}/{attempt_id}", headers=headers)


# -----------------------------------------------------------------------------
# 鉴权：三个接口都不许匿名访问
# -----------------------------------------------------------------------------
def test_scrolls_require_auth(db_client) -> None:
    assert db_client.get(SCROLLS).status_code == 401
    assert db_client.get(f"{SCROLLS}/1").status_code == 401
    assert db_client.delete(f"{SCROLLS}/1").status_code == 401


# -----------------------------------------------------------------------------
# 04·5 列表
# -----------------------------------------------------------------------------
def test_scrolls_empty_archive_returns_zero_not_an_error(db_client, auth_headers) -> None:
    """一次都没挑战过时是**空列表**，不是报错（新用户第一屏就是这个）。"""
    body = _scrolls(db_client, auth_headers)

    assert body["total"] == 0
    assert body["items"] == []
    assert body["domains"] == []
    assert body["has_more"] is False


def test_one_row_per_attempt_not_per_quiz(db_client, db_session, auth_headers) -> None:
    """同一份卷轴挑战两次 → **两条**记录，`attempt_no` 依次为 1、2。

    这条是整张表的语义基准：列表项的主键是 `attempt_id`，详情 / 重做 /
    删除都以它为准。若按 `quiz_id` 去重，重做过的卷轴就只剩一条，
    「重做」按钮点进去之后历史被覆盖。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, title="RAG 入门闯关")

    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(0))

    body = _scrolls(db_client, auth_headers)

    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert {item["attempt_no"] for item in body["items"]} == {1, 2}
    assert len({item["attempt_id"] for item in body["items"]}) == 2


def test_scrolls_are_newest_first(db_client, db_session, auth_headers) -> None:
    """最新的一局排在最前 —— 用户翻历史卷轴先看到的是刚才那局。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)

    settle(db_client, auth_headers, db_session, quiz, outcomes=("wrong",), finished_at=at(-3))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1))

    body = _scrolls(db_client, auth_headers)
    labels = [item["finished_label"] for item in body["items"]]

    assert labels[0].startswith("今天")
    assert labels[1].startswith("昨天")
    # 超过两天就不再报时刻，改报日期 —— 那一局的「几点」已经没有信息量
    three_days_ago = business_date(at(-3))
    assert labels[2] == f"{three_days_ago.month} 月 {three_days_ago.day} 日"


def test_finished_label_uses_business_timezone_days(
    db_client, db_session, auth_headers
) -> None:
    """「今天 / 昨天 / M 月 D 日」按**业务日**算，跨年才带年份。

    今天那一行用 `TODAY_EARLY`（今天 00:00）而不是 `at(0)` —— 理由见该常量的说明。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)

    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=TODAY_EARLY)
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-8))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-400))

    labels = [item["finished_label"] for item in _scrolls(db_client, auth_headers)["items"]]

    assert labels[0] == "今天 00:00"
    assert labels[1] == "昨天 10:00"

    eight_days_ago = business_date(at(-8))
    assert labels[2] == f"{eight_days_ago.month} 月 {eight_days_ago.day} 日"

    long_ago = business_date(at(-400))
    assert labels[3] == f"{long_ago.year} 年 {long_ago.month} 月 {long_ago.day} 日"


def test_scroll_item_carries_what_the_row_shows(db_client, db_session, auth_headers) -> None:
    """一条记录带齐原型那一行要用的数字：标题、正确率、题数、用时。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, title="向量检索入门", kps=("甲", "乙"))

    settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=TODAY_EARLY, duration_ms=45_000,
    )

    item = _scrolls(db_client, auth_headers)["items"][0]

    assert item["title"] == "向量检索入门"
    assert item["total_count"] == 2
    assert item["correct_count"] == 1
    assert item["accuracy"] == 50
    assert item["duration_ms"] == 45_000
    assert item["attempt_no"] == 1
    assert item["quiz_id"] == str(quiz.id)
    assert item["finished_at"].endswith("+00:00"), "时间必须带 UTC 偏移"


def test_scrolls_pagination_reports_full_total(db_client, db_session, auth_headers) -> None:
    """分页时 `total` 仍是**全量**条数（页脚「共 N 份卷轴」要用它）。

    `size` 故意取 2 而总数是 3 —— 若 `total` 写成当前页长度，
    页脚会随翻页从 3 变成 1，越翻越少。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)

    for offset in range(3):
        settle(
            db_client, auth_headers, db_session, quiz,
            outcomes=("correct",), finished_at=at(-offset),
        )

    first = _scrolls(db_client, auth_headers, size=2)
    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert first["has_more"] is True

    second = _scrolls(db_client, auth_headers, page=2, size=2)
    assert second["total"] == 3
    assert len(second["items"]) == 1
    assert second["has_more"] is False


def test_scrolls_default_page_size_is_twenty(db_client, auth_headers) -> None:
    """默认页大小取自常量，重命名时不会两处不一致。"""
    body = _scrolls(db_client, auth_headers)

    assert body["size"] == 20
    assert body["page"] == 1


def test_scrolls_reject_oversized_page(db_client, auth_headers) -> None:
    """超过上限直接报参数错，而不是**静默截断** —— 静默截断会让
    「我明明要了 500 条却只拿到 50 条」变成一个查不出来的现象。"""
    resp = db_client.get(
        SCROLLS, headers=auth_headers, params={"size": SCROLL_PAGE_SIZE_MAX + 1}
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == 4000


def test_scrolls_unknown_domain_returns_empty_but_keeps_chips(
    db_client, db_session, auth_headers
) -> None:
    """筛到一个没有记录的领域 → 空列表，但 chips 不变（否则无法切回去）。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("RAG",))
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0))

    body = _scrolls(db_client, auth_headers, domain="不存在的领域")

    assert body["items"] == []
    assert body["total"] == 0
    assert body["domains"] == ["RAG"]


def test_scrolls_domain_filter_matches_any_question_in_the_attempt(
    db_client, db_session, auth_headers
) -> None:
    """领域筛选取「这一局**涉及过**该知识点」，不是「整局都属于它」。"""
    user_id = current_user_id(db_client, auth_headers)
    mixed = make_quiz(db_session, user_id, title="混合卷轴", kps=("甲", "乙"))
    only_b = make_quiz(db_session, user_id, title="纯乙卷轴", kps=("乙",))

    settle(db_client, auth_headers, db_session, mixed, outcomes=("correct",) * 2, finished_at=at(-1))
    settle(db_client, auth_headers, db_session, only_b, outcomes=("correct",), finished_at=at(0))

    body = _scrolls(db_client, auth_headers, domain="甲")

    assert body["total"] == 1
    assert body["items"][0]["title"] == "混合卷轴"
    # chips 是**全量**的，不受当前筛选影响
    assert set(body["domains"]) == {"甲", "乙"}


# -----------------------------------------------------------------------------
# 04·6 详情
# -----------------------------------------------------------------------------
def test_scroll_detail_returns_every_question_with_the_users_answer(
    db_client, db_session, auth_headers
) -> None:
    """逐题明细：题干、选项、正确答案、**当时选的**、判定结果、讲解。

    `selected` 是历史快照的一部分 —— 详情页要能重看「我当初选了 B，
    正确答案是 A」。少了它，这一屏就退化成一份普通题目列表。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"), types=("single", "judge"))

    settled = settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=TODAY_EARLY,
    )
    attempt_id = settled["attempt_id"]

    body = _detail(db_client, auth_headers, attempt_id).json()["data"]

    assert body["attempt_id"] == attempt_id
    assert body["total_count"] == 2
    assert body["correct_count"] == 1
    assert body["wrong_count"] == 1
    assert body["partial_count"] == 0
    assert body["finished_label"] == "今天 00:00"
    assert body["attempt_no"] == 1

    assert [q["seq"] for q in body["questions"]] == [1, 2]
    first, second = body["questions"]

    assert first["type"] == "single"
    assert first["outcome"] == "correct"
    assert first["selected"] == first["answer"]
    assert first["earned_xp"] == first["max_xp"] > 0
    assert first["explanation"] == "测试用解析"
    assert len(first["options"]) >= 3

    assert second["type"] == "judge"
    assert second["outcome"] == "wrong"
    assert second["selected"] != second["answer"]
    assert second["answer"] == ["T"], "判断题的正确答案是 T/F"
    assert second["earned_xp"] == 0
    assert second["max_xp"] > 0


def test_scroll_detail_is_not_found_for_another_users_attempt(
    db_client, other_auth_headers, db_session, auth_headers
) -> None:
    """越权读别人的卷轴 → 4005「内容不存在」，**不是 403**。

    若为越权单独设码，攻击者就能靠错误码差异探测「这条记录存在吗」。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    settled = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )

    resp = _detail(db_client, other_auth_headers, settled["attempt_id"])

    assert resp.status_code == 404
    assert resp.json()["code"] == 4005


def test_scroll_detail_is_not_found_for_a_missing_attempt(db_client, auth_headers) -> None:
    resp = _detail(db_client, auth_headers, "999999999")

    assert resp.status_code == 404
    assert resp.json()["code"] == 4005


def test_scroll_detail_rejects_a_non_numeric_id(db_client, auth_headers) -> None:
    """路径参数不是数字 → 参数错误，而不是被当成「不存在」。"""
    resp = _detail(db_client, auth_headers, "abc")

    assert resp.status_code == 400
    assert resp.json()["code"] == 4000


# -----------------------------------------------------------------------------
# 删除（软删除）
# -----------------------------------------------------------------------------
def test_delete_removes_the_row_from_the_list(db_client, db_session, auth_headers) -> None:
    """删掉一局之后列表里看不到它，但另一局还在。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)

    keep = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )
    drop = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1)
    )

    resp = _delete(db_client, auth_headers, drop["attempt_id"])
    assert resp.status_code == 200
    assert resp.json()["data"] == {"attempt_id": drop["attempt_id"], "deleted": True}

    body = _scrolls(db_client, auth_headers)

    assert body["total"] == 1
    assert [item["attempt_id"] for item in body["items"]] == [keep["attempt_id"]]


def test_delete_hides_the_detail_too(db_client, db_session, auth_headers) -> None:
    """删掉的记录连详情也读不到 —— 否则「从列表消失」还能从详情页绕回来。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    settled = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )

    _delete(db_client, auth_headers, settled["attempt_id"])

    resp = _detail(db_client, auth_headers, settled["attempt_id"])
    assert resp.status_code == 404
    assert resp.json()["code"] == 4005


def test_delete_twice_is_not_found_the_second_time(
    db_client, db_session, auth_headers
) -> None:
    """重复删除报 4005 —— 幂等由客户端忽略该错误实现，服务端不假装成功。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    settled = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )

    assert _delete(db_client, auth_headers, settled["attempt_id"]).status_code == 200
    again = _delete(db_client, auth_headers, settled["attempt_id"])

    assert again.status_code == 404
    assert again.json()["code"] == 4005


def test_delete_is_not_found_for_another_users_attempt(
    db_client, other_auth_headers, db_session, auth_headers
) -> None:
    """越权删别人的卷轴 → 4005，且**真的没删掉**。"""
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    settled = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )

    resp = _delete(db_client, other_auth_headers, settled["attempt_id"])

    assert resp.status_code == 404
    assert resp.json()["code"] == 4005

    assert _detail(db_client, auth_headers, settled["attempt_id"]).status_code == 200


def test_delete_keeps_grades_untouched(db_client, db_session, auth_headers) -> None:
    """**这条是软删除存在的原因**（需求 FR-B5 验收标准）。

    验收标准逐字写着：「删除后该记录从列表消失，但累计 XP、正确率、等级**不变**」。
    正确率是实时聚合出来的，硬删会连带 `CASCADE` 掉 `answers`，
    用户会看到自己的成绩在「删掉一条历史」之后被改写。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id, kps=("甲", "乙"))
    settled = settle(
        db_client, auth_headers, db_session, quiz,
        outcomes=("correct", "wrong"), finished_at=at(0),
    )

    def snapshot() -> dict:
        profile = db_client.get("/api/v1/users/me", headers=auth_headers).json()["data"]
        dashboard = db_client.get(
            "/api/v1/users/me/dashboard", headers=auth_headers
        ).json()["data"]
        return {
            "xp": profile["user"]["xp_total"],
            "coins": profile["user"]["coins"],
            "level": profile["user"]["level"],
            "accuracy": profile["stats"]["avg_accuracy"],
            "dashboard_accuracy": dashboard["accuracy"],
            "week_answers": dashboard["week_answers"],
        }

    before = snapshot()
    assert _delete(db_client, auth_headers, settled["attempt_id"]).status_code == 200
    after = snapshot()

    assert after == before, "删除只移除记录，不改写任何成绩"


def test_delete_decrements_the_entry_counts(db_client, db_session, auth_headers) -> None:
    """但**条数**要跟着少 —— 「历史卷轴」那一行写的数字必须等于列表长度。

    与上一条的区别是刻意的：验收标准点名保护的是 XP / 正确率 / 等级，
    而「共 N 份冒险日志」与 pill 上的 N 是列表的另一种呈现。
    若它不跟着减，用户会看到「共 2 份」的入口点进去只有 1 条。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    first = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )
    settle(db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(-1))

    before = db_client.get("/api/v1/users/me", headers=auth_headers).json()["data"]["stats"]
    assert before["attempt_count"] == 2

    _delete(db_client, auth_headers, first["attempt_id"])

    after = db_client.get("/api/v1/users/me", headers=auth_headers).json()["data"]["stats"]
    assert after["attempt_count"] == 1
    # 原型里这两处显示同一个数，链式抽验脚本也钉着这条等式
    assert after["scroll_count"] == after["attempt_count"]
    assert after["attempt_count"] == _scrolls(db_client, auth_headers)["total"]


def test_delete_keeps_the_quiz_for_retry(db_client, db_session, auth_headers) -> None:
    """删一局历史不该把**卷轴本身**删掉 —— 重做入口仍要能取回题目。

    `attempts` 有 `ON DELETE CASCADE`，硬删会让卷轴题目一起消失。
    """
    user_id = current_user_id(db_client, auth_headers)
    quiz = make_quiz(db_session, user_id)
    settled = settle(
        db_client, auth_headers, db_session, quiz, outcomes=("correct",), finished_at=at(0)
    )

    _delete(db_client, auth_headers, settled["attempt_id"])

    retry = db_client.post(f"/api/v1/attempts/{settled['attempt_id']}/retry", headers=auth_headers)
    assert retry.status_code == 200, retry.text
