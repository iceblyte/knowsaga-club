"""配图**判断题**的用例（`add-question-image-generation` 第 18 组）。

这一层守的是「哪些题值得配图」这个判断本身，与「图怎么生成」（`test_image_*.py`）
和「图怎么进到用户看得见的地方」（`test_quiz_image_flow.py`）都不是一回事。

## 为什么不给每道题都配图

配图是**按张花钱**的：一套 5 道题全配，其中往往有 2–3 道是抽象概念、纯逻辑或
文字表述题 —— 画出来的东西对理解没有增益，甚至与题目无关（2026-09-26 的人眼
验收里，抽象题会随机画成花、枫叶、灯泡）。所以先让模型判一次，只给真正
「画得出来且有助于理解」的题生成。

## 三条硬契约（都在这份用例里钉住）

1. **判断失败绝不等于「不配图」，而是「全都配」**。
   判断是**省钱手段**，不是功能前提。模型挂了 / 超时 / 没配 Key 时回退到
   接入本功能之前的行为（全部配图），而不是让用户勾了配图却一张都拿不到。
   这也是为什么返回值里用 `ids is None`（全配）而不是空集合来表达「没判成」。

2. **空集合与「没判成」是两件不同的事**。
   模型明确说「都不需要」⇒ `ids == frozenset()` ⇒ 一道都不配；
   模型没说出结果 ⇒ `ids is None` ⇒ 全都配。
   把两者混成一个值，会让「模型故障」静默表现成「用户拿不到图」。

3. **判断题只看得到题干、题型与知识点**，看不到选项、答案与解析。
   与 `llm/image/prompt.py` 同一条纪律：任何"答案侧"的信息不进这条链路，
   就没有泄题的可能（判断题的输出会影响画什么）。

## 它必须**不抛异常**

`quiz_service` 是在后台线程里调它的，抛出去就是任务永远停在 running。
所以这里的每一条失败路径都断言「返回了降级结果」而不是「抛了异常」。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.core.exceptions import ai_generation_failed
from app.llm.image import selector
from app.llm.output_schemas import ImageSelectionDraft
from app.models.quiz import Question


# -----------------------------------------------------------------------------
# 替身
# -----------------------------------------------------------------------------
class FakeLlm:
    """结构化输出的替身：零网络，返回预设的 `include_raw=True` 形状。

    刻意保留 `include_raw` 的那三个键（`parsed` / `raw` / `parsing_error`）——
    `fallback.classify_result` 就是按它们判定的，替身给个简化形状会让
    「解析失败」「空响应」这些分支变成测不到的死代码。
    """

    def __init__(
        self,
        *,
        parsed: Any = None,
        parsing_error: Any = None,
        explode: bool = False,
    ) -> None:
        self.calls: list[Any] = []
        self._parsed = parsed
        self._parsing_error = parsing_error
        self._explode = explode

    def invoke(self, prompt: Any) -> dict[str, Any]:  # noqa: ANN401
        self.calls.append(prompt)
        if self._explode:
            raise RuntimeError("替身故意爆炸：验第二道兜底")
        return {"parsed": self._parsed, "raw": None, "parsing_error": self._parsing_error}

    def rendered_text(self) -> str:
        """把最后一次收到的提示词摊成一段纯文本（供断言用）。"""
        assert self.calls, "替身一次都没被调用"
        messages = self.calls[-1]
        parts: list[str] = []
        for message in getattr(messages, "messages", messages):
            content = getattr(message, "content", message)
            parts.append(content if isinstance(content, str) else str(content))
        return "\n".join(parts)


def _questions(sample_questions: list[dict]) -> list[Question]:
    return [Question.model_validate(item) for item in sample_questions]


def _run(
    *,
    settings: Settings,
    questions: list[Question],
    llm: FakeLlm | None = None,
) -> tuple[selector.ImageSelection, FakeLlm]:
    """跑一次判断，返回结果与替身。"""
    spy = llm or FakeLlm(parsed=ImageSelectionDraft(ids=[]))
    result = selector.select_for_images(
        questions, settings=settings, llm_factory=lambda: spy
    )
    return result, spy


# -----------------------------------------------------------------------------
# 一、开关关着就不判断（零成本）
# -----------------------------------------------------------------------------
def test_disabled_switch_skips_the_model(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关掉判断 ⇒ 一次模型都不调，语义回到「全部配图」。"""
    settings = image_env(IMAGE_SELECT_ENABLED="false")
    result, spy = _run(
        settings=settings,
        questions=_questions(sample_questions),
    )

    assert spy.calls == []
    assert result.selects_all is True
    assert result.reason == selector.REASON_DISABLED


# -----------------------------------------------------------------------------
# 二、正常判断
# -----------------------------------------------------------------------------
def test_selected_ids_are_returned(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型给出题号子集 ⇒ 原样（去重后）返回。"""
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=["q1", "q1", "q4"]))
    result, _ = _run(
        settings=image_env(),
        questions=_questions(sample_questions),
        llm=spy,
    )

    assert result.ids == frozenset({"q1", "q4"})
    assert result.reason == selector.REASON_JUDGED
    assert result.selects_all is False


def test_unknown_ids_are_dropped(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型编出来的题号必须丢掉 —— 否则上层会去找一道不存在的题。"""
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=["q1", "q99", "  q2  ", "zzz"]))
    result, _ = _run(
        settings=image_env(),
        questions=_questions(sample_questions),
        llm=spy,
    )

    assert result.ids == frozenset({"q1", "q2"})


def test_empty_selection_means_no_images(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型明确说「都不需要」⇒ 空集合（**不是** `None`，那表示全都要）。"""
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=[]))
    result, _ = _run(
        settings=image_env(),
        questions=_questions(sample_questions),
        llm=spy,
    )

    assert result.ids == frozenset()
    assert result.ids is not None
    assert result.selects_all is False
    assert result.reason == selector.REASON_JUDGED


def test_selecting_every_question_is_still_a_judgement(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型把 5 道题全选了 ⇒ 与「全部配图」结果相同，但 reason 是「判过」。"""
    ids = [item["id"] for item in sample_questions]
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=ids))
    result, _ = _run(
        settings=image_env(),
        questions=_questions(sample_questions),
        llm=spy,
    )

    assert result.ids == frozenset(ids)
    assert result.reason == selector.REASON_JUDGED


def test_empty_questions_short_circuit(
    image_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没有题目 ⇒ 不调模型，返回空集合（没有要配的图）。"""
    result, spy = _run(settings=image_env(), questions=[])

    assert spy.calls == []
    assert result.ids == frozenset()


# -----------------------------------------------------------------------------
# 三、提示词的形状（跨文件契约）
# -----------------------------------------------------------------------------
def test_prompt_carries_only_stem_type_and_knowledge_point(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """选项文字 / 答案 / 解析**都不得**出现在提示词里。"""
    questions = _questions(sample_questions)
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=[]))
    _run(settings=image_env(), questions=questions, llm=spy)

    text = spy.rendered_text()
    # 题干与知识点必须在（判断的依据）
    assert questions[0].stem in text
    assert questions[0].knowledge_point in text
    assert questions[0].type in text

    for question in questions:
        for option in question.options:
            assert option.text not in text, f"{question.id} 的选项文字漏进提示词了"
        assert question.explanation not in text, f"{question.id} 的解析漏进提示词了"
    # 答案的 key 单独出现（如 "A"）没法用子串断言 —— 答案的**文字**已经在选项里查过了


def test_prompt_demands_json(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """json_mode 是 DeepSeek 的官方硬要求：提示词里**必须**出现 json 字样。"""
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=[]))
    _run(
        settings=image_env(),
        questions=_questions(sample_questions),
        llm=spy,
    )

    assert "json" in spy.rendered_text().lower()


def test_prompt_lists_every_question(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每道题都要出现在清单里 —— 漏掉的那道永远不会被选中。"""
    questions = _questions(sample_questions)
    spy = FakeLlm(parsed=ImageSelectionDraft(ids=[]))
    _run(settings=image_env(), questions=questions, llm=spy)

    text = spy.rendered_text()
    for question in questions:
        assert question.id in text


# -----------------------------------------------------------------------------
# 四、降级：判断没成 ⇒ 全部配图（不是「不配」）
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"parsed": None}, id="空响应"),
        pytest.param({"parsing_error": ValueError("结构化解析失败")}, id="解析失败"),
        pytest.param({"explode": True}, id="调用抛异常"),
    ],
)
def test_failure_falls_back_to_everything(
    image_env, sample_questions, monkeypatch: pytest.MonkeyPatch, kwargs: dict
) -> None:
    """三种失败形态都必须**回退到全部配图**，且不抛异常。"""
    spy = FakeLlm(**kwargs)
    result, _ = _run(
        settings=image_env(),
        questions=_questions(sample_questions),
        llm=spy,
    )

    assert result.selects_all is True, "判断失败时必须回退为全部配图"
    assert result.reason == selector.REASON_FALLBACK


def test_factory_failure_falls_back(
    image_env, sample_questions
) -> None:
    """连**构造模型**就抛（最典型的是没配 `DEEPSEEK_API_KEY`）⇒ 同样回退，不冒泡。

    ⚠️ 这里注入一个「构造即抛」的工厂，而**不是**靠 `delenv("DEEPSEEK_API_KEY")`：
    本机 `.env` 里就有真 Key，那样写会让这条用例真的发出一次 DeepSeek 请求
    （实测踩到过：返回了合法的空选题结果，用例因此以「判定成功」失败）。
    单测**绝不允许**打通真实上游。
    """

    def _explode():  # noqa: ANN202
        raise ai_generation_failed("未配置 DEEPSEEK_API_KEY，无法调用大模型")

    result = selector.select_for_images(
        _questions(sample_questions), settings=image_env(), llm_factory=_explode
    )

    assert result.selects_all is True
    assert result.reason == selector.REASON_FALLBACK


# -----------------------------------------------------------------------------
# 五、配置
# -----------------------------------------------------------------------------
def test_config_defaults(image_env) -> None:
    """默认**开着**判断（省钱手段应当默认生效），超时比出题链短。"""
    settings = image_env()

    assert settings.image_select_enabled is True
    assert settings.image_select_timeout_seconds > 0
    assert settings.image_select_timeout_seconds < settings.quiz_timeout_seconds
