"""一局结束后的**自我比较**判定（变更 `replace-percentile-with-self-comparison`）。

## 这里锁什么

替换掉「与他人最佳成绩比百分位」之后，结算页与冒险日志页那一格改成讲
「比过去的自己怎么样」。判定分两层，本文件两层都锁：

| 层 | 函数 | 要不要库 |
|---|---|---|
| 判定 | `judge` | **不要** —— 纯函数，喂进三个数就能验六种状态与优先级 |
| 取数 | `for_attempt` | 要 —— 三条查询的**筛选口径**（只取本人 / 只看已完成 / 基准只取该局之前） |

分层不是洁癖：这个能力的全部业务规则都在 `judge` 里，把它写成纯函数之后
「状态怎么判」可以用参数化用例钉死，而取数那一层只剩「取哪些行」。

## 比较量是**答对题数**，不是正确率

用正确率比会把百分比立刻请回来 —— 而这一格的全部意义就是不说百分比
（见 `openspec/changes/replace-percentile-with-self-comparison/design.md` D4）。
所以下面所有用例里的数字都是「答对几题」，`total` 只在文案里出现。
"""

from __future__ import annotations

import pytest

from app.db.tables import Attempt
from app.models.attempt import AttemptScorePoint
from app.services import progress_service
from app.utils.timeutil import utcnow
from tests.helpers import current_user_id, make_quiz


def _pt(correct: int, total: int = 5) -> AttemptScorePoint:
    """造一个「历史某一局」的成绩点。"""
    return AttemptScorePoint(correct=correct, total=total)


# -----------------------------------------------------------------------------
# 1. 判定的六种状态（纯函数）
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("correct_count", "previous", "best", "expected", "why"),
    [
        # 首局：没有任何历史 → 没有可比的对象，不给差值
        (3, None, None, "first", "此前一局都没有"),
        # 严格高于历史最好 → 刷新纪录
        (5, _pt(4), _pt(4), "record", "比历史最好多答对 1 题"),
        # 等于历史最好 → 追平（**不是** record）
        (4, _pt(2), _pt(4), "tie_best", "与历史最好并列"),
        # 未刷纪录时，才轮到与**上一局**比
        (3, _pt(2), _pt(4), "better", "比上一局多答对 1 题"),
        (3, _pt(3), _pt(4), "same", "与上一局答对一样多"),
        (2, _pt(3), _pt(4), "worse", "比上一局少答对 1 题"),
    ],
)
def test_judge_six_states(
    correct_count: int,
    previous: AttemptScorePoint | None,
    best: AttemptScorePoint | None,
    expected: str,
    why: str,
) -> None:
    assert (
        progress_service.judge(
            correct_count=correct_count, previous=previous, best=best
        )
        == expected
    ), why


# -----------------------------------------------------------------------------
# 2. 优先级冲突：同时满足多个条件时取哪一个
# -----------------------------------------------------------------------------
def test_judge_record_beats_same_as_previous() -> None:
    """刷新纪录时，哪怕与上一局答对一样多，也必须是 `record`。

    「与上一局持平」在刷新纪录这一刻是无关信息 —— 用户真正的新状态是
    「这是你目前最好的一局」。
    """
    assert (
        progress_service.judge(correct_count=5, previous=_pt(5), best=_pt(4)) == "record"
    )


def test_judge_tie_best_beats_worse_than_previous() -> None:
    """追平历史最好时，哪怕比上一局**少**答对，也不能报 `worse`。

    这是优先级里最容易写错的一处：先判「与上一局比」再判「与最好比」，
    用户就会在追平自己最好成绩的那一局看到「比上一局少答对 1 题」——
    一句真话，但完全说错了重点。
    """
    assert (
        progress_service.judge(correct_count=4, previous=_pt(5), best=_pt(4)) == "tie_best"
    )


def test_judge_first_beats_everything() -> None:
    """没有任何历史时一定是 `first` —— 不许从空基准里推出一句比较。"""
    assert progress_service.judge(correct_count=0, previous=None, best=None) == "first"


def test_judge_tie_is_not_record() -> None:
    """并列**不算**刷新纪录。

    与旧百分位口径同源的一条：4 个人都考 100 分，你也考 100 分，
    那叫并列第一，不是「超过了他们」。换到纵向比较里，「追平」与
    「刷新」是两句不同的话 —— 刷新那句会带一个「多答对 N 题」的差值，
    而并列时这个差值是 0，说出来就是「比之前最好的一局多答对 0 题」。
    """
    state = progress_service.judge(correct_count=5, previous=_pt(5), best=_pt(5))
    assert state == "tie_best"


def test_judge_ignores_total_count() -> None:
    """判定只看**答对题数**，`total` 不参与 —— 它只用来在文案里给分母。

    这里的构造刻意是一个「按正确率会得出相反结论」的例子：本局 2 / 5（40%）
    在正确率上高于上一局的 3 / 20（15%），但答对题数少 1，所以状态是 `worse`。
    这是知情接受的取舍，换来的东西是这一格永远不出现百分比
    （见 design.md 的 Risks 与 D4）。
    """
    assert (
        progress_service.judge(correct_count=2, previous=_pt(3, total=20), best=_pt(5, total=20))
        == "worse"
    )


# -----------------------------------------------------------------------------
# 3. 取数口径（要库）
# -----------------------------------------------------------------------------
# 这一层唯一容易错的地方就是「取哪些行」。下面的用例逐条钉住筛选条件，
# 因为每一条错了都不会报错，只会让用户看到一句**看起来很正常**的错话。
@pytest.fixture
def uid(db_client, auth_headers) -> int:  # noqa: ANN001
    """当前登录用户的数据库 id（不猜「第一个用户」，见 tests/helpers）。"""
    return current_user_id(db_client, auth_headers)


@pytest.fixture
def other_uid(db_client, other_auth_headers) -> int:  # noqa: ANN001
    """第二个用户的 id，专供「别人的成绩不算我的历史」用例。"""
    return current_user_id(db_client, other_auth_headers)


@pytest.fixture
def quiz(db_session, uid: int):  # noqa: ANN201
    return make_quiz(db_session, uid, kps=("RAG 基本定义",))


@pytest.fixture
def other_quiz(db_session, other_uid: int):  # noqa: ANN201
    return make_quiz(db_session, other_uid, kps=("RAG 基本定义",))


def _mk(
    session,
    *,
    user_id: int,
    quiz_id: int,
    correct: int,
    total: int = 5,
    status: str = "finished",
):
    """直接插一行 `attempts`（造历史）。

    走 ORM 而不是走接口，是为了能精确控制 `status` 与 `deleted_at` ——
    这两个字段正是下面几条用例要验的筛选条件，而接口造不出「未完成的一局」。
    """
    moment = utcnow()
    row = Attempt(
        user_id=user_id,
        quiz_id=quiz_id,
        attempt_no=1,
        started_at=moment,
        finished_at=moment,
        duration_ms=60_000,
        correct_count=correct,
        wrong_count=total - correct,
        partial_count=0,
        total_count=total,
        accuracy=round(correct * 100 / total) if total else 0,
        max_xp=100,
        xp_gained=0,
        coins_gained=0,
        avg_seconds_per_question=10,
        status=status,
    )
    session.add(row)
    session.flush()
    return row


def test_for_attempt_first_has_no_baseline(db_session, uid: int) -> None:
    """首局：三个字段全空、两个差值都是 0 —— 不从空基准里推一句比较出来。"""
    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=3, before_attempt_id=None
    )

    assert progress.state == "first"
    assert progress.attempt_count == 1
    assert progress.best is None
    assert progress.previous is None
    assert progress.delta_vs_prev == 0
    assert progress.delta_vs_best == 0


def test_for_attempt_no_before_id_takes_all_history(db_session, uid: int, quiz) -> None:
    """`before_attempt_id=None`（结算时的入口）= 本局还没落库，基准取**全量**。

    上一局取**紧邻**的那一条（id 最大），不是正确的最大者。
    """
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=2)
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=4)
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=0)

    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=5, before_attempt_id=None
    )

    assert progress.state == "record"
    assert progress.attempt_count == 4  # 含本局
    assert progress.best is not None and progress.best.correct == 4
    assert progress.previous is not None and progress.previous.correct == 0
    assert progress.delta_vs_prev == 5  # 5 − 0
    assert progress.delta_vs_best == 1  # 5 − 4


def test_for_attempt_only_rows_before_given_id(db_session, uid: int, quiz) -> None:
    """`before_attempt_id=N`（回看历史报告）= 基准**只含 `id < N`** 的记录。

    这条口径是「历史报告不随时间漂移」的全部依据：库里那三行 id 更大、
    成绩更好，但它们发生在这一局**之后**，不许影响这一局的比较结果。
    """
    first = _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=2)
    second = _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=4)
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=5)  # 后来的满分

    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=3, before_attempt_id=int(second.id)
    )

    assert progress.state == "record"  # 相对 second 之前的记录（只有 2 分那局）
    assert progress.attempt_count == 2
    assert progress.best is not None and progress.best.correct == 2
    assert progress.previous is not None and progress.previous.correct == 2

    # 同一局用 `None` 当基准会得到另一个答案 —— 说明这个参数真的在起作用
    as_settlement = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=3, before_attempt_id=None
    )
    assert as_settlement.state == "worse"  # 相对全量：历史最好 5、上一局 4
    assert as_settlement.attempt_count == 4
    assert int(first.id) < int(second.id)  # 造数前提：id 即写入序


def test_for_attempt_ignores_other_users(db_session, uid: int, other_uid: int, quiz, other_quiz) -> None:
    """别人的成绩**不算**我的历史 —— 这正是本次要撤掉的那种比较。"""
    _mk(db_session, user_id=other_uid, quiz_id=int(other_quiz.id), correct=5)

    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=1, before_attempt_id=None
    )

    assert progress.state == "first"
    assert progress.attempt_count == 1
    assert progress.best is None


def test_for_attempt_ignores_unfinished_attempts(db_session, uid: int, quiz) -> None:
    """未完成的一局不算历史 —— 「最好成绩」不该由一局中途退出产生。

    与旧百分位口径一致（`percentile_service` 同样只取 `status='finished'`）。
    """
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=5, status="running")

    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=1, before_attempt_id=None
    )

    assert progress.state == "first"
    assert progress.attempt_count == 1


def test_for_attempt_counts_deleted_rows(db_session, uid: int, quiz) -> None:
    """已删除的记录**照样计入** —— FR-B5：删除「仅移除记录，不影响整体统计」。

    过滤 `deleted_at` 的后果是：用户删掉一条旧记录，自己的「最好成绩」就变了，
    甚至历史报告上那句「追平了自己的最好成绩」会变成「刷新了自己的纪录」——
    正是那条需求禁止的事。
    """
    removed = _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=4)
    removed.deleted_at = utcnow()
    db_session.flush()

    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=2, before_attempt_id=None
    )

    assert progress.attempt_count == 2
    assert progress.best is not None and progress.best.correct == 4
    assert progress.state == "worse"


def test_for_attempt_best_breaks_tie_by_recency(db_session, uid: int, quiz) -> None:
    """并列最高时取**更近**的那一局。

    并列时取哪一行会决定文案里那个分母（「你的最好成绩：答对 4 / 5 题」
    还是「答对 4 / 8 题」）。不加 `id DESC` 这个次序键的话，MySQL 返回哪一行
    是**不确定的** —— 同一个用户两次刷新可能看到不同的分母。
    """
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=4, total=5)
    _mk(db_session, user_id=uid, quiz_id=int(quiz.id), correct=4, total=8)

    progress = progress_service.for_attempt(
        db_session, user_id=uid, correct_count=1, before_attempt_id=None
    )

    assert progress.best is not None
    assert (progress.best.correct, progress.best.total) == (4, 8)
    assert progress.delta_vs_best == -3  # 1 − 4：非 record 时为负
