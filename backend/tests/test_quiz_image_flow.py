"""题目配图的**接链**用例（`add-question-image-generation` 第 5 组）。

这一层守的是「配图怎么进到用户看得见的地方」，而不是配图怎么生成
（那是 `test_image_*.py` 的事）。四件事：

## 一、不勾选配图时，一切与今天**逐位一致**

`generate_images` 默认 `false` ⇒ 生图替身**一次都不该被调用**、题目的
`image_url` 全为 `None`、第二步的文案一字不差、任务照常成功。
这是「只做增量」的硬证据：若哪天有人在默认路径上顺手把生图接上了，这里会响。

## 二、生图出任何事都不能影响出题（design D8）

三种情况都要验：单张失败（部分带图）、整段失败（一道都不带图）、
替身**抛异常**（契约上它不该抛，所以这里是第二道兜底）。
三种情况下任务都必须是 `succeeded`，题库都必须是完整的。

## 三、配额扣在实际成功张数上

预扣 5 张、只成了 3 张 ⇒ 出题结束后用量是 **3** 而不是 5。
出题整体失败 / 被取消 ⇒ **全额退回**（design D6：结算在任务成功之后）。
这两条不验的话，「用户为没拿到的图买单」不会有人发现。

## 四、配额预检必须在**建任务之前**

超额时 `task_service.create_task` 的调用次数必须是 **0**。
只看返回码是不够的 —— 先建任务再校验同样会返回一个错误码，
但用户已经拿到了一个注定失败的 task_id（同 `test_quiz_kb.py` 的纪律）。

## ⚠️ 接口用例一律用 `db_client`

不要用 `client` 配 `auth_headers`：`client` 的 `get_db` **没有**被改到测试库，
而鉴权依赖会真的去查库。那样请求会打到**业务库**上（而且 token 对应的用户
在那边不存在，于是拿到一个与用例意图无关的 4010）。
"""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError, ErrorCode
from app.db.tables import QuestionRecord
from app.llm import image as image_flow
from app.llm import quiz_chain
from app.llm.image import ImageOutcome
from app.llm.image import selector as image_select
from app.llm.image.selector import ImageSelection
from app.llm.output_schemas import QuizDraft, draft_to_quiz
from app.models.quiz import Question, Quiz
from app.services import (
    image_quota_service,
    quiz_repository,
    quiz_service,
    review_service,
    task_service,
)
from tests.helpers import make_user

GENERATE_URL = "/api/v1/quiz/generate"
VALID_INPUT = "我想系统学习监督学习的基本原理和常见算法"

#: 对象存储上的**永久**地址长这样（腾讯云 COS 默认域名）
COS_URL = "https://knowsaga-1250000000.cos.ap-guangzhou.myqcloud.com/questions/abc/1.jpg"


# -----------------------------------------------------------------------------
# 夹具
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def image_harness(
    image_env, monkeypatch: pytest.MonkeyPatch, sample_quiz_payload: dict  # noqa: ANN001
):
    """本文件每条用例都在「配图已开启 + 假凭据」的环境里跑。

    与 KB 夹具组同一套理由（见 `conftest.py`）：**不**做成全局 autouse，
    但在本文件里是显式的 —— 这里的每一条都在验这条能力。

    ⚠️ 顺手把出题链、配图判断与生图段**三个**外部调用点都钉成替身。
    这不是多余的：本文件有走 HTTP 的用例，而 `POST /quiz/generate` 会把任务丢进
    **真的后台线程**。若某条用例忘了替换它们，那一跑就会真的去请求 DeepSeek / 百炼 ——
    实测踩过一次（日志里一串 `401 Authorization Required`，那是真实请求，红线）。
    默认替身让「忘了替换」不再有后果；个别用例仍可用自己的 `monkeypatch`
    覆盖它（monkeypatch 按注册逆序还原，不会互相干扰）。

    ⚠️ 配图判断（`app/llm/image/selector.py`，2026-09-26 加）是**另一个**调用点：
    生图走百炼，判断走 DeepSeek，而本机 `.env` 里的 `DEEPSEEK_API_KEY` 是真的。
    所以这里必须显式钉住，否则本文件每条用例都会真的发一次模型请求。
    钉成「全都配」（`ids=None`）⇒ 既有用例的语义与接入判断之前**逐位一致**。
    """
    image_env()
    stub = Quiz.model_validate(
        {**copy.deepcopy(sample_quiz_payload), "user_input": VALID_INPUT}
    )
    monkeypatch.setattr(quiz_chain, "generate_quiz", lambda **_: stub)
    monkeypatch.setattr(
        image_flow,
        "generate_for_questions",
        lambda questions, *, settings, on_progress=None: ImageOutcome(
            urls={}, attempted=0, succeeded=0
        ),
    )
    monkeypatch.setattr(
        image_select,
        "select_for_images",
        lambda questions, *, settings, llm_factory=None: ImageSelection(
            ids=None, reason=image_select.REASON_FALLBACK
        ),
    )


@pytest.fixture
def no_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    """把后台执行整个吞掉。

    只想验「**提交那一刻**的副作用」的用例用它 —— 比 `inline_submit` 更准确：
    inline 会把整条出题链跑完，于是提交时预扣的额度立刻被结算掉，
    反而看不出「预扣发生在提交时」这件事。
    """

    def _drop(_fn):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(quiz_service, "_submit", _drop)


class SpyImages:
    """生图段的替身：产出确定的假地址，**零网络、零上游**。

    刻意用真实形状的 `ImageOutcome`（含 `attempted` / `reason`），
    而不是一个简化形状 —— 上层要按 `attempted` 区分「没启用」与「全挂了」，
    替身给个 dict 就会把那条分支变成测不到的死代码。
    """

    def __init__(self, *, succeed: int | None = None, explode: bool = False) -> None:
        self.calls = 0
        self.asked: list[str] = []
        self._succeed = succeed
        self._explode = explode

    def __call__(self, questions, *, settings, on_progress=None):  # noqa: ANN001, ANN202
        from app.llm.image import REASON_DONE, REASON_ERROR, REASON_PARTIAL

        self.calls += 1
        self.asked = [question.id for question in questions]
        if self._explode:
            raise RuntimeError("替身故意爆炸：验第二道兜底")

        total = len(questions)
        succeed = total if self._succeed is None else max(0, min(self._succeed, total))
        urls = {
            question.id: f"{COS_URL}?seq={index}"
            for index, question in enumerate(questions[:succeed], start=1)
        }
        for index in range(1, total + 1):
            if on_progress is not None:
                on_progress(index, total)

        if succeed == total:
            reason = REASON_DONE
        elif succeed == 0:
            reason = REASON_ERROR
        else:
            reason = REASON_PARTIAL
        return ImageOutcome(urls=urls, attempted=total, succeeded=succeed, reason=reason)


@pytest.fixture
def spy_images(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """替换生图段并留档。返回一个「造替身」的小工厂。"""

    def _install(*, succeed: int | None = None, explode: bool = False) -> SpyImages:
        spy = SpyImages(succeed=succeed, explode=explode)
        monkeypatch.setattr(image_flow, "generate_for_questions", spy)
        return spy

    return _install


@pytest.fixture
def spy_create_task(monkeypatch: pytest.MonkeyPatch) -> list[dict]:  # noqa: ANN001
    """记录 `task_service.create_task` 的调用（**真的建**，只是留一份记录）。

    不换成「什么都不做」的假货：留档的同时让真实路径继续跑 ——
    这样「合法请求确实建出了任务」仍然是被验过的，只多了一个计数器。
    """
    calls: list[dict] = []
    real = task_service.create_task

    def _spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append({"args": args, "kwargs": kwargs})
        return real(*args, **kwargs)

    monkeypatch.setattr(task_service, "create_task", _spy)
    return calls


@pytest.fixture
def quota_user(db_session):  # noqa: ANN001, ANN201
    """一个真实用户（`image_quota_usage.user_id` 有外键）。"""
    return make_user(db_session, openid=f"openid-image-{uuid4().hex[:8]}")


def _fake_quiz(sample_quiz_payload: dict) -> Quiz:
    payload = copy.deepcopy(sample_quiz_payload)
    payload["user_input"] = VALID_INPUT
    return Quiz.model_validate(payload)


def _quiz_payload_with_images(sample_questions: list[dict], urls: dict[int, str]) -> dict:
    """一份题库 payload，按题序（0 起）给指定题目挂上配图。"""
    return {
        "quiz_id": f"quiz_{uuid4().hex[:8]}",
        "title": "RAG 入门闯关",
        "summary": "围绕 RAG 基础概念与应用场景生成的题库",
        "source_type": "text",
        "user_input": VALID_INPUT,
        "knowledge_points": None,
        "questions": [
            dict(question, image_url=urls.get(index))
            for index, question in enumerate(copy.deepcopy(sample_questions))
        ],
    }


def _start_task(*, user_id: int, settings, question_count: int) -> str:  # noqa: ANN001
    """按**真实路径的形状**建任务（含那三步状态卡）。

    不能省掉 `steps`：本文件有几条用例要读第二步的 detail，而真实入口
    （`submit_quiz_request`）建任务时就带上了 `_initial_steps`。
    用一个空 steps 的任务去验进度文案，等于在没有那块画布的地方找字。
    """
    provider = quiz_service.get_search_provider(settings)
    request = quiz_service._build_search_request(VALID_INPUT, settings)
    steps = quiz_service._initial_steps(provider, request, question_count)
    return task_service.create_task("quiz", user_id=user_id, steps=steps).task_id


def _run_quiz(
    *,
    task_id: str,
    user_id: int,
    settings,  # noqa: ANN001
    quiz: Quiz,
    image_hold=None,  # noqa: ANN001
    generate=None,  # noqa: ANN001
) -> None:
    """跑一次后台出题（同步调用，不起线程）。

    生图替身由调用方装；`generate` 不传就用固定题库 —— 传进来才能验
    「出题本身失败」那条路径（那时的失败必须让配额全额退回）。
    """
    quiz_service.run_quiz_generation(
        task_id,
        user_id=user_id,
        user_input=VALID_INPUT,
        question_count=len(quiz.questions),
        difficulty="mixed",
        settings=settings,
        generate=generate or (lambda **_: quiz),
        image_hold=image_hold,
    )


def _used(session, *, user_id: int) -> int:  # noqa: ANN001
    from app.services import image_quota_service as svc

    return svc.used_today(session, user_id=user_id)


# -----------------------------------------------------------------------------
# 一、契约：Question.image_url
# -----------------------------------------------------------------------------
def test_question_image_url_defaults_to_none(sample_questions: list[dict]) -> None:
    """默认 `None` —— 存量调用方（含所有既有测试）不受影响。"""
    assert Question.model_validate(sample_questions[0]).image_url is None


def test_question_accepts_a_permanent_url(sample_questions: list[dict]) -> None:
    payload = dict(sample_questions[0], image_url=COS_URL)

    assert Question.model_validate(payload).image_url == COS_URL


def test_draft_to_quiz_strips_model_supplied_image_url(sample_quiz_payload: dict) -> None:
    """模型自己吐 `image_url` 必须被清掉。

    `Question` 是 `extra="ignore"`，但 `image_url` 是**已声明的字段** ——
    模型一旦编一个地址就会被原样收下，变成「模型编的假图片链接」，
    是最难查的一类假数据。配图只能由服务端生图段写入（design D11）。
    """
    payload = copy.deepcopy(sample_quiz_payload)
    for question in payload["questions"]:
        question["image_url"] = "https://evil.example.com/fake.jpg"

    quiz = draft_to_quiz(QuizDraft.model_validate(payload), user_input=VALID_INPUT)

    assert all(question.image_url is None for question in quiz.questions)


def test_quiz_serialization_exposes_image_url(sample_quiz_payload: dict) -> None:
    """对外契约里必须**有**这个字段 —— 前端就是靠它拿到图的。"""
    payload = copy.deepcopy(sample_quiz_payload)
    payload["questions"][0]["image_url"] = COS_URL

    dumped = Quiz.model_validate(payload).model_dump()

    assert dumped["questions"][0]["image_url"] == COS_URL
    assert dumped["questions"][1]["image_url"] is None


def test_quiz_draft_accepts_extra_unknown_fields(sample_quiz_payload: dict) -> None:
    """反面守卫：模型多吐别的字段也不该让整次出题失败（`extra="ignore"`）。"""
    payload = copy.deepcopy(sample_quiz_payload)
    payload["questions"][0]["illustration"] = {"prompt": "..."}

    quiz = draft_to_quiz(QuizDraft.model_validate(payload), user_input=VALID_INPUT)

    assert quiz.questions[0].image_url is None


# -----------------------------------------------------------------------------
# 二、仓储：落库与回读
# -----------------------------------------------------------------------------
def test_persist_quiz_writes_and_reads_back_image_url(
    db_session, quota_user, sample_questions
) -> None:  # noqa: ANN001
    quiz = Quiz.model_validate(_quiz_payload_with_images(sample_questions, {0: COS_URL}))

    stored = quiz_repository.persist_quiz(db_session, user_id=quota_user.id, quiz=quiz)

    assert stored.questions[0].image_url == COS_URL
    assert stored.questions[1].image_url is None

    # 换一条真实读取路径回读（不复用刚落库时的返回值）
    db_session.rollback()
    rows = quiz_repository.load_questions(db_session, int(stored.quiz_id))
    row = quiz_repository.get_quiz_row(db_session, int(stored.quiz_id))
    assert row is not None
    rebuilt = quiz_repository.build_quiz(row, rows)

    assert rebuilt.questions[0].image_url == COS_URL
    assert rebuilt.questions[1].image_url is None


def test_persist_quiz_clips_overlong_image_url(
    db_session, quota_user, sample_questions
) -> None:  # noqa: ANN001
    """`questions.image_url` 是 `VARCHAR(512)`：超长必须截断。

    不截断的话 MySQL 严格模式直接报错，整次出题白跑 ——
    而截断只影响这一张图的地址，题目本身照常可用。
    """
    long_url = "https://cos.example.com/" + "x" * 700
    quiz = Quiz.model_validate(_quiz_payload_with_images(sample_questions, {0: long_url}))

    quiz_repository.persist_quiz(db_session, user_id=quota_user.id, quiz=quiz)

    db_session.rollback()
    stored = db_session.execute(
        select(QuestionRecord.image_url).order_by(QuestionRecord.seq).limit(1)
    ).scalar_one()
    assert stored is not None
    assert len(stored) == quiz_repository.IMAGE_URL_MAX


def test_questions_are_stored_without_images_by_default(
    db_session, quota_user, sample_questions
) -> None:  # noqa: ANN001
    quiz = Quiz.model_validate(_quiz_payload_with_images(sample_questions, {}))

    stored = quiz_repository.persist_quiz(db_session, user_id=quota_user.id, quiz=quiz)

    assert all(question.image_url is None for question in stored.questions)


def test_review_copy_carries_the_original_image(
    db_session, quota_user, sample_questions
) -> None:  # noqa: ANN001
    """复习副本与原题**内容一致** ⇒ 配图也该跟着走（同一道题、同一张图）。"""
    quiz = Quiz.model_validate(_quiz_payload_with_images(sample_questions, {0: COS_URL}))
    stored = quiz_repository.persist_quiz(db_session, user_id=quota_user.id, quiz=quiz)

    row = db_session.get(QuestionRecord, int(stored.questions[0].id))
    assert row is not None

    assert review_service._copy_of(row).image_url == COS_URL


# -----------------------------------------------------------------------------
# 三、服务流程：不勾选配图 ⇒ 逐位不变
# -----------------------------------------------------------------------------
def test_no_images_requested_never_touches_the_generator(
    db_scope, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """`image_hold=None`（今天的默认路径）⇒ 生图替身**一次都不被调用**。"""
    spy = spy_images()
    quiz = _fake_quiz(sample_quiz_payload)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(task_id=task_id, user_id=quota_user.id, settings=settings, quiz=quiz)

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    assert spy.calls == 0
    assert task.quiz is not None
    assert all(question.image_url is None for question in task.quiz.questions)


def test_generate_step_detail_is_unchanged_without_images(
    db_scope, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """不配图时第二步的文案与接入前**一字不差**（前端零视觉漂移的守卫）。"""
    spy_images()
    quiz = _fake_quiz(sample_quiz_payload)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(task_id=task_id, user_id=quota_user.id, settings=settings, quiz=quiz)

    steps = {step.key: step for step in task_service.get_task(task_id).steps}
    assert steps["generate"].detail == f"已生成 {len(quiz.questions)} 道题"


# -----------------------------------------------------------------------------
# 四、服务流程：勾选配图
# -----------------------------------------------------------------------------
def _hold_for(db_session, *, user_id: int, count: int, settings):  # noqa: ANN001, ANN202
    """预扣并**立即提交**（模拟提交请求时的真实时点）。"""
    hold = image_quota_service.reserve(
        db_session, user_id=user_id, count=count, settings=settings
    )
    db_session.commit()
    return hold


def test_images_are_attached_and_persisted(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    spy = spy_images()
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(
        db_session, user_id=quota_user.id, count=len(quiz.questions), settings=settings
    )
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    assert spy.calls == 1
    assert spy.asked == [question.id for question in quiz.questions]
    assert task.quiz is not None
    assert all(question.image_url for question in task.quiz.questions)

    # 真的落到库里了（不是只在内存的任务对象里）
    db_session.rollback()
    stored = (
        db_session.execute(
            select(QuestionRecord.image_url).order_by(QuestionRecord.seq)
        )
        .scalars()
        .all()
    )
    assert len(stored) == len(quiz.questions)
    assert all(url for url in stored)


def test_partial_failure_keeps_the_other_images(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """5 题成了 2 张 ⇒ 那 2 题带图、其余不带；任务照常成功（design D8 规则 2）。"""
    spy_images(succeed=2)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    assert task.quiz is not None
    assert len([q for q in task.quiz.questions if q.image_url]) == 2


def test_total_failure_still_succeeds_without_images(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """一张都没成 ⇒ 全部不带图，`quiz` 照常落库、任务照常 `succeeded`（D8 规则 3）。"""
    spy_images(succeed=0)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    assert task.quiz is not None
    assert all(question.image_url is None for question in task.quiz.questions)


def test_generator_exception_does_not_break_the_quiz(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """替身**抛异常**也不能把出题搞挂 —— 生图段的第二道兜底。

    契约上 `generate_for_questions` 不抛异常，但「契约说不会抛」不等于
    「真不会抛」。这一段跑在后台线程里，漏出去就是任务永远停在 running。
    """
    spy_images(explode=True)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    assert task.quiz is not None
    assert all(question.image_url is None for question in task.quiz.questions)


def test_progress_detail_reports_image_counts(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """生图进度写进**第二步**的 detail（design D10：不新增第四步）。"""
    spy_images(succeed=3)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    steps = {step.key: step for step in task_service.get_task(task_id).steps}
    assert len(steps) == 3, "生图不许新增一步（原型的三步是裁决依据）"
    assert "配图 3 / 5" in steps["generate"].detail


# -----------------------------------------------------------------------------
# 四之二、AI 挑图：只给挑中的题生成（2026-09-26 新增，design D18）
# -----------------------------------------------------------------------------
class SpySelect:
    """配图判断的替身。`ids=None` 表示「全都配」（未判成 / 开关关着）。"""

    def __init__(self, *, ids, reason, explode: bool = False) -> None:  # noqa: ANN001
        self.calls: list[list[str]] = []
        self._ids = None if ids is None else frozenset(ids)
        self._reason = reason
        self._explode = explode

    def __call__(self, questions, *, settings, llm_factory=None):  # noqa: ANN001, ANN202
        self.calls.append([question.id for question in questions])
        if self._explode:
            raise RuntimeError("判断替身故意爆炸：验第二道兜底")
        return ImageSelection(ids=self._ids, reason=self._reason)


@pytest.fixture
def spy_select(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """替换配图判断并留档。

    `image_harness` 已经装了一个「全都配」的默认替身，这里覆盖它 ——
    monkeypatch 按注册逆序还原，两者不会互相干扰。
    """

    def _install(  # noqa: ANN202
        ids,  # noqa: ANN001
        *,
        reason=image_select.REASON_JUDGED,  # noqa: ANN001
        explode: bool = False,
    ) -> SpySelect:
        spy = SpySelect(ids=ids, reason=reason, explode=explode)
        monkeypatch.setattr(image_select, "select_for_images", spy)
        return spy

    return _install


def test_selection_narrows_the_targets(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images, spy_select
) -> None:  # noqa: ANN001
    """判断只挑中 2 道 ⇒ 生图段**只拿到这 2 道**，其余题目保持无图。

    这是省钱这件事的**唯一**证据：光有判断结果、却仍然把 5 道都丢给生图段，
    钱照样花掉，而且从外部看不出来。
    """
    spy = spy_images()
    sel = spy_select(["q1", "q3"])
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    # 判断看得到**全部**题目（否则它没法比较哪些更值得配）
    assert sel.calls == [["q1", "q2", "q3", "q4", "q5"]]
    # 生图段只拿到被挑中的那两道（这里的 id 是**落库前**的原始题号）
    assert spy.asked == ["q1", "q3"]
    assert task.quiz is not None
    # ⚠️ 按**位置**断言，不能按 id：落库之后题目 id 会被改写成数据库主键的
    # 字符串形式（见 `quiz_repository` 的模块说明），回读时已经是 "1" / "3"。
    urls = [q.image_url for q in task.quiz.questions]
    assert [url is not None for url in urls] == [True, False, True, False, False]


def test_empty_selection_generates_nothing(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images, spy_select
) -> None:  # noqa: ANN001
    """判断认为一道都不需要 ⇒ **一次生图都不该发生**，且任务照常成功。

    收尾文案必须是「没有需要配图的题」而不是「配图 0 / 5」——
    后者看起来像 5 张全失败，而这里根本没打算配。
    """
    spy = spy_images()
    spy_select([])
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded", "没人要图不等于出题失败"
    assert spy.calls == 0, "判断说都不需要 ⇒ 生图段一次都不该被调用"
    assert task.quiz is not None
    assert all(q.image_url is None for q in task.quiz.questions)

    steps = {step.key: step for step in task.steps}
    assert "没有需要配图的题" in steps["generate"].detail

    # 预扣的 5 张必须全额退回（一张都没生成）
    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 0


def test_selection_failure_falls_back_to_every_question(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images, spy_select
) -> None:  # noqa: ANN001
    """判断没成 ⇒ 回退到「全都配」，而不是「全都不配」（design D18 第 2 条契约）。"""
    spy = spy_images()
    spy_select(None, reason=image_select.REASON_FALLBACK)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    assert spy.asked == ["q1", "q2", "q3", "q4", "q5"]
    task = task_service.get_task(task_id)
    assert task.quiz is not None
    assert all(q.image_url for q in task.quiz.questions)


def test_selection_exception_does_not_break_the_quiz(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images, spy_select
) -> None:  # noqa: ANN001
    """判断替身**抛异常**也不能把出题搞挂 —— 它是后台线程里的第二道兜底。

    契约上 `selector.select_for_images` 不抛，但「契约说不会抛」不等于
    「真不会抛」。这一条与 `test_generator_exception_does_not_break_the_quiz`
    是同一个理由，只是换成了判断那一步。

    兜底策略取 selector 自己的降级语义 —— **回退「全部配图」**：
    用户是主动勾了配图的，判断器坏掉不该变成「一张都没有」。
    """
    spy = spy_images()
    spy_select(None, explode=True)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    task = task_service.get_task(task_id)
    assert task.status == "succeeded"
    assert spy.calls == 1, "判断炸了 ⇒ 回退全部配图，所以生图段仍然要被跑一次"
    assert spy.asked == ["q1", "q2", "q3", "q4", "q5"]
    assert task.quiz is not None
    assert all(q.image_url for q in task.quiz.questions)


def test_progress_detail_uses_the_selected_count_as_denominator(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images, spy_select
) -> None:  # noqa: ANN001
    """挑中 2 道、成了 2 张 ⇒ 文案是「配图 2 / 2」，不是「2 / 5」。

    分母写总题数会让用户以为还有 3 张在路上。
    """
    spy_images()
    spy_select(["q2", "q5"])
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    steps = {step.key: step for step in task_service.get_task(task_id).steps}
    assert "配图 2 / 2" in steps["generate"].detail


def test_quota_counts_only_the_selected_and_succeeded(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images, spy_select
) -> None:  # noqa: ANN001
    """预扣 5、挑中 2、成 1 ⇒ 用量是 **1**（挑图省下的钱必须体现在额度上）。"""
    spy_images(succeed=1)
    spy_select(["q2", "q4"])
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 1


def test_selecting_detail_text() -> None:
    """判断这一步有自己的文案：先显示「正在配图 0 / 5」再跳成「0 / 2」会像进度回退。"""
    assert (
        quiz_service._image_selecting_detail(5) == "已生成 5 道题 · 正在挑选值得配图的题目"
    )


# -----------------------------------------------------------------------------
# 五、配额联动
# -----------------------------------------------------------------------------
def test_quota_is_settled_by_the_actual_success_count(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """预扣 5、成了 3 ⇒ 最终用量是 **3**，不是 5。"""
    spy_images(succeed=3)
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 3


def test_quota_is_fully_refunded_when_generation_fails(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """出题整体失败 ⇒ 配额全额退回（design D6：结算在任务成功之后）。"""
    from app.core.exceptions import ai_generation_failed

    spy_images()
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )

    def _boom(**_kwargs):  # noqa: ANN202
        raise ai_generation_failed()

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
        generate=_boom,
    )

    assert task_service.get_task(task_id).status == "failed"
    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 0


def test_quota_is_fully_refunded_when_the_task_is_cancelled(
    db_scope, db_session, settings, sample_quiz_payload, quota_user, spy_images
) -> None:  # noqa: ANN001
    """用户取消 ⇒ 也该全额退回，不能白扣一次配额。"""
    spy_images()
    quiz = _fake_quiz(sample_quiz_payload)
    hold = _hold_for(db_session, user_id=quota_user.id, count=5, settings=settings)
    task_id = _start_task(
        user_id=quota_user.id, settings=settings, question_count=len(quiz.questions)
    )
    task_service.cancel_task(task_id)

    _run_quiz(
        task_id=task_id,
        user_id=quota_user.id,
        settings=settings,
        quiz=quiz,
        image_hold=hold,
    )

    assert task_service.get_task(task_id).status == "cancelled"
    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 0


# -----------------------------------------------------------------------------
# 六、提交入口：校验顺序与开关语义
# -----------------------------------------------------------------------------
def test_submit_without_images_reserves_nothing(
    no_submit, db_scope, db_session, settings, quota_user, spy_create_task
) -> None:  # noqa: ANN001
    """不勾选配图 ⇒ 配额表里一行都不该有，任务照常建出来。"""
    submission = quiz_service.submit_quiz_request(
        user_id=quota_user.id,
        user_input=VALID_INPUT,
        question_count=5,
        difficulty="mixed",
        settings=settings,
        session=db_session,
    )

    assert submission.task_id
    assert len(spy_create_task) == 1
    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 0


def test_submit_rejects_images_when_capability_is_off(
    db_client, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    """开关关着还传 `generate_images=true` ⇒ 4001 用户可见文案，而不是默默忽略。

    「默默忽略」更糟：用户以为开了配图，拿到题目才发现一张图都没有，
    而界面不会给任何解释。
    """
    from app.core.config import get_settings

    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "false")
    get_settings.cache_clear()

    resp = db_client.post(
        GENERATE_URL,
        json={"user_input": VALID_INPUT, "question_count": 5, "generate_images": True},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == ErrorCode.INVALID_INPUT
    assert "配图" in body["message"]


def test_submit_rejects_images_when_quota_is_exhausted_before_creating_a_task(
    no_submit, db_scope, db_session, image_env, quota_user, spy_create_task
) -> None:  # noqa: ANN001
    """超额 ⇒ 4290，且 **`create_task` 调用次数为 0**（预检在建任务之前）。

    只看返回码不够：先建任务再校验也会返回错误码，但用户已经拿到 task_id、
    看着进度条跑几秒，最后收到一个注定失败的任务。
    """
    settings = image_env(IMAGE_DAILY_QUOTA=1)
    _hold_for(db_session, user_id=quota_user.id, count=1, settings=settings)

    with pytest.raises(AppError) as excinfo:
        quiz_service.submit_quiz_request(
            user_id=quota_user.id,
            user_input=VALID_INPUT,
            question_count=5,
            difficulty="mixed",
            settings=settings,
            session=db_session,
            generate_images=True,
        )

    assert excinfo.value.code == ErrorCode.RATE_LIMITED
    assert len(spy_create_task) == 0, "额度不足时不许建任务"


def test_submit_reserves_quota_immediately(
    no_submit, db_scope, db_session, image_env, quota_user
) -> None:  # noqa: ANN001
    """预扣发生在**提交时**，不是出题完成时 —— 用户不必等十几秒才知道没额度。"""
    settings = image_env(IMAGE_DAILY_QUOTA=5)

    quiz_service.submit_quiz_request(
        user_id=quota_user.id,
        user_input=VALID_INPUT,
        question_count=3,
        difficulty="mixed",
        settings=settings,
        session=db_session,
        generate_images=True,
    )

    db_session.rollback()
    assert _used(db_session, user_id=quota_user.id) == 3


# -----------------------------------------------------------------------------
# 七、接口
# -----------------------------------------------------------------------------
def test_generate_images_is_accepted_and_images_land(
    db_client, db_scope, inline_submit, auth_headers, spy_images, sample_quiz_payload
) -> None:  # noqa: ANN001
    """端到端（HTTP → 后台线程 → 落库）：勾选后题库里真的带上了图。"""
    spy = spy_images()
    user_id = int(
        db_client.get("/api/v1/users/me", headers=auth_headers).json()["data"]["user"]["id"]
    )

    resp = db_client.post(
        GENERATE_URL,
        json={"user_input": VALID_INPUT, "question_count": 5, "generate_images": True},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    task = task_service.get_task(resp.json()["data"]["task_id"])
    assert task.status == "succeeded"
    assert spy.calls == 1
    assert task.quiz is not None
    assert all(question.image_url for question in task.quiz.questions)

    with db_scope() as session:
        assert _used(session, user_id=user_id) == 5


def test_generate_images_defaults_to_false(
    db_client, db_scope, inline_submit, auth_headers, spy_images
) -> None:  # noqa: ANN001
    """不传 `generate_images` ⇒ 走的是**没有配图**的那条路径（存量调用方零改动）。"""
    spy = spy_images()

    resp = db_client.post(
        GENERATE_URL,
        json={"user_input": VALID_INPUT, "question_count": 5},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    task = task_service.get_task(resp.json()["data"]["task_id"])
    assert spy.calls == 0
    assert task.quiz is not None
    assert all(question.image_url is None for question in task.quiz.questions)
