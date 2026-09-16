"""文本清洗测试（Phase 1.1）—— TDD 红灯先行。

约定的契约：

    clean_input(text, *, truncate=True) -> str
        完整清洗管道：剔除控制字符 → 归一空白 → 去首尾空白；truncate=True 时截断到 MAX_INPUT_LEN

    validate_input(text) -> str
        清洗后做长度校验；不合规抛 AppError(code=4001)；合规则返回清洗后的文本（不截断）
"""

from __future__ import annotations

import pytest

from app.core.exceptions import AppError, ErrorCode
from app.utils.text_cleaner import (
    MAX_INPUT_LEN,
    MIN_INPUT_LEN,
    clean_input,
    normalize_whitespace,
    strip_control_chars,
    validate_input,
)


# ---------------------------------------------------------------- 长度常量
def test_length_bounds_are_sane() -> None:
    """原型：按钮在 8 字激活、计数器上限 200。"""
    assert MIN_INPUT_LEN == 8
    assert MAX_INPUT_LEN == 200


# ---------------------------------------------------------------- 控制字符
def test_strip_control_chars_removes_c0_and_c1() -> None:
    """除 \\n 与 \\t 外，C0(0x00-0x1F) 与 C1(0x7F-0x9F) 控制字符都要剔除。"""
    dirty = "RAG\x00是\x01什么\x7f？\x9f它\x1b吃\x0c文档"
    cleaned = strip_control_chars(dirty)
    assert "\x00" not in cleaned
    assert "\x01" not in cleaned
    assert "\x7f" not in cleaned
    assert "\x9f" not in cleaned
    assert "\x1b" not in cleaned
    assert "\x0c" not in cleaned
    assert "RAG是什么？它吃文档" in cleaned


def test_strip_control_chars_keeps_newline_and_tab() -> None:
    """换行与制表符是正文结构，必须保留。"""
    cleaned = strip_control_chars("第一行\n第二行\t缩进")
    assert "\n" in cleaned
    assert "\t" in cleaned


def test_strip_control_chars_removes_zero_width() -> None:
    """零宽字符（\\u200b/\\u200c/\\u200d/\\ufeff）肉眼不可见，但会污染题干长度。"""
    cleaned = strip_control_chars("向量\u200b检索\ufeff入门\u200d")
    assert "\u200b" not in cleaned
    assert "\ufeff" not in cleaned
    assert "\u200d" not in cleaned
    assert cleaned == "向量检索入门"


# ---------------------------------------------------------------- 空白归一
def test_normalize_whitespace_full_width_to_half() -> None:
    """中文输入法极易打出全角空格，必须归一为半角。"""
    assert normalize_whitespace("RAG\u3000是什么") == "RAG 是什么"


def test_normalize_whitespace_collapses_runs() -> None:
    """连续空白压缩为单个空格。"""
    assert normalize_whitespace("RAG     与    传统搜索") == "RAG 与 传统搜索"


def test_normalize_whitespace_strips_edges() -> None:
    assert normalize_whitespace("   \n  RAG  \n\n  ") == "RAG"


def test_normalize_whitespace_collapses_blank_lines() -> None:
    """段落分隔（≥2 个连续换行）压缩成单个换行，避免 prompt 里出现大段空白。"""
    assert normalize_whitespace("第一段\n\n\n\n第二段") == "第一段\n第二段"


def test_normalize_whitespace_single_newline_becomes_space() -> None:
    """单个换行视同普通空白，折叠为空格（输入框里的软换行不该带进 prompt）。"""
    assert normalize_whitespace("我想学习\n什么是 RAG") == "我想学习 什么是 RAG"


# ---------------------------------------------------------------- 完整管道
def test_clean_input_end_to_end() -> None:
    dirty = "  \u3000 我想学习   什么是\u200b RAG \n\n\n 以及它与传统搜索的区别 \x00 "
    cleaned = clean_input(dirty)
    # 零宽字符剔除、全角空格归一、连续空格折叠、段落换行保留、首尾空白去除
    assert cleaned == "我想学习 什么是 RAG\n以及它与传统搜索的区别"


def test_clean_input_truncates_to_max() -> None:
    """超长输入默认截断，保证送进 prompt 的长度可控。"""
    cleaned = clean_input("啊" * 500)
    assert len(cleaned) == MAX_INPUT_LEN


def test_clean_input_can_skip_truncation() -> None:
    cleaned = clean_input("啊" * 500, truncate=False)
    assert len(cleaned) == 500


def test_clean_input_handles_empty_and_whitespace_only() -> None:
    assert clean_input("") == ""
    assert clean_input("    \u3000 \n ") == ""


# ---------------------------------------------------------------- 校验
def test_validate_input_rejects_too_short() -> None:
    with pytest.raises(AppError) as ei:
        validate_input("RAG 是")  # 5 字
    assert ei.value.code == ErrorCode.INVALID_INPUT


def test_validate_input_rejects_empty() -> None:
    with pytest.raises(AppError) as ei:
        validate_input("     ")
    assert ei.value.code == ErrorCode.INVALID_INPUT


def test_validate_input_accepts_exactly_min() -> None:
    text = "啊" * MIN_INPUT_LEN
    assert validate_input(text) == text


def test_validate_input_accepts_exactly_max() -> None:
    text = "啊" * MAX_INPUT_LEN
    assert len(validate_input(text)) == MAX_INPUT_LEN


def test_validate_input_rejects_too_long() -> None:
    """超过上限直接报错，而不是静默截断 —— 用户需要知道自己超了。"""
    with pytest.raises(AppError) as ei:
        validate_input("啊" * (MAX_INPUT_LEN + 1))
    assert ei.value.code == ErrorCode.INVALID_INPUT


def test_validate_input_length_counted_after_cleaning() -> None:
    """长度按清洗后的文本计算：8 个「啊」+ 一堆空白，应当通过。"""
    text = "  \u3000 啊" * 8 + "  \n\n "
    assert len(validate_input(text)) >= MIN_INPUT_LEN


def test_validate_input_rejects_whitespace_padding_short_text() -> None:
    """用空白凑长度不算数 —— 清洗后只有 3 字，必须拒绝。"""
    with pytest.raises(AppError) as ei:
        validate_input("啊" * 3 + " " * 200)
    assert ei.value.code == ErrorCode.INVALID_INPUT


def test_validate_input_normalizes_and_returns() -> None:
    result = validate_input("  我想学习\u3000什么是   RAG    ")
    assert result == "我想学习 什么是 RAG"
