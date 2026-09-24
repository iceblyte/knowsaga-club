"""文档解析与扩展名准入的契约（`add-private-knowledge-base` 第 4 组）。

## 为什么测试用**真文件**而不是 mock 解析库

本组的外部依赖是 `pypdf` 与 `docx2txt` —— 它们都是**纯计算**（读字节、抽文本），
不发网络请求，所以「测试里不许打真实 LLM」那条红线**不适用**。
反过来，把它们 mock 掉就等于只测了「我们自己写的那几行」，
而真正会出问题的是「这两种格式的实际字节长什么样」——
本文件里的 `.pdf` / `.docx` 都是按 OOXML / PDF 规范**手工构造**的最小合法样本，
交给真库解析。这样「加载器选对了但库用错了」这类错误才会暴露。

## 为什么「抽不到文本」必须判失败

扫描件 PDF（只有图、没有文字层）是最常见的输入。它的 `extract_text()`
返回空串而**不报错** —— 顺着这条线走下去，用户会得到一个「解析成功」
但**一条都检索不到**的空知识库，而且界面上一切正常。
所以「全空白」在加载器这一层就要变成异常。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.llm.kb.loaders import (
    SUPPORTED_EXTENSIONS,
    DocumentParseError,
    UnsupportedFormatError,
    ext_of,
    is_supported_ext,
    load_document,
)


# ---------------------------------------------------------------- 样本构造
def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _make_pdf(path: Path, pages_text: list[str]) -> Path:
    """手写一份最小合法 PDF（每页一段用 Helvetica 绘制的文字）。

    为什么要自己拼：生成 PDF 的常用库（reportlab 等）会引入一个新的重依赖，
    只为一个测试样本不值得。而「按规范拼出交叉引用表」这件事本身只有三十行。
    """
    page_ids = [4 + 2 * index for index in range(len(pages_text))]
    content_ids = [5 + 2 * index for index in range(len(pages_text))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)

    objects: list[tuple[int, str]] = [
        (1, "<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages_text)} >>"),
        (3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    for index, text in enumerate(pages_text):
        objects.append(
            (
                page_ids[index],
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_ids[index]} 0 R >>",
            )
        )
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET"
        objects.append(
            (content_ids[index], f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        )
    objects.sort()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for object_id, body in objects:
        offsets[object_id] = len(out)
        out += f"{object_id} 0 obj\n{body}\nendobj\n".encode("latin-1")

    xref_position = len(out)
    max_id = max(object_id for object_id, _ in objects)
    out += f"xref\n0 {max_id + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for object_id in range(1, max_id + 1):
        out += f"{offsets[object_id]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode()
    return _write(path, bytes(out))


def _make_docx(path: Path, paragraphs: list[str]) -> Path:
    """手写一份最小合法 .docx（只有 `word/document.xml` 的 zip 包）。"""
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return path


# ---------------------------------------------------------------- 扩展名准入
def test_supported_extensions_are_exactly_the_four_admitted() -> None:
    """准入清单就是这四种 —— 加一种必须是有意为之（加载器也要跟着加）。"""
    assert SUPPORTED_EXTENSIONS == frozenset({".pdf", ".docx", ".md", ".txt"})


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("note.md", ".md"),
        ("note.MD", ".md"),
        ("NOTE.Pdf", ".pdf"),
        ("机器学习导论.docx", ".docx"),
        # 多点文件名：只看**最后**一个点后面的部分
        ("ai.rag.notes.md", ".md"),
        # 客户端可能塞路径进来（D11：文件名只用于准入，扩展名是唯一取用点）
        ("C:/Users/ice/我的资料.pdf", ".pdf"),
        ("dir.d/notes.pdf", ".pdf"),
    ],
)
def test_ext_of_normalizes(filename: str, expected: str) -> None:
    assert ext_of(filename) == expected


@pytest.mark.parametrize("filename", ["README", "", "no_extension_at_all"])
def test_ext_of_returns_empty_when_there_is_no_extension(filename: str) -> None:
    """**根本没有**扩展名时返回空串，而不是抛异常 —— 准入判定要拿它当布尔用。

    ⚠️ 注意与下面那条的区别：「没有扩展名」与「扩展名不在清单里」是两种输入，
    但对准入是同一个结果。把它们混成一条断言，会让「`.zip` 明明取到了扩展名」
    这种事实被一个 `== ""` 的断言掩盖过去。
    """
    assert ext_of(filename) == ""
    assert not is_supported_ext(filename)


@pytest.mark.parametrize("filename", ["archive.zip", "photo.png", "legacy.doc", "video.mp4"])
def test_unsupported_extensions_are_rejected(filename: str) -> None:
    """扩展名取得出来、但不在准入清单里 —— 同样拒收。"""
    assert ext_of(filename) != ""
    assert not is_supported_ext(filename)


def test_legacy_doc_is_not_admitted() -> None:
    """旧的 `.doc` 明确不收。

    `docx2txt` 只认 OOXML 包（.docx），`.doc` 是另一个二进制格式。
    收下它会在解析阶段变成「解析失败」，那不如在准入阶段就照实说清楚。
    """
    assert not is_supported_ext("论文.doc")


# ---------------------------------------------------------------- 纯文本
def test_load_markdown_keeps_content(tmp_path: Path) -> None:
    source = "# RAG\n\n先检索，再生成。\n"
    _write(tmp_path / "note.md", source.encode("utf-8"))

    loaded = load_document(tmp_path / "note.md", filename="note.md")

    assert "先检索，再生成。" in loaded.text
    assert loaded.page_count is None, "纯文本没有页的概念，不能编一个出来"


def test_load_txt_utf8(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "中文内容测试".encode("utf-8"))

    loaded = load_document(tmp_path / "a.txt", filename="a.txt")

    assert "中文内容测试" in loaded.text


def test_load_txt_gbk_falls_back(tmp_path: Path) -> None:
    """GBK 编码的 `.txt` 必须能读出来。

    Windows 上「另存为 txt」默认就是 GBK，而中文用户手里的资料大量来自这一步。
    只按 UTF-8 硬解会抛 `UnicodeDecodeError`，症状是「这份文件一直解析失败」，
    而文件本身完全正常。
    """
    _write(tmp_path / "gbk.txt", "这是国标编码的内容".encode("gbk"))

    loaded = load_document(tmp_path / "gbk.txt", filename="gbk.txt")

    assert "这是国标编码的内容" in loaded.text


def test_load_txt_utf8_bom_is_stripped(tmp_path: Path) -> None:
    """带 BOM 的 UTF-8 不能把 BOM 当正文 —— 它会变成片段开头的不可见字符。"""
    _write(tmp_path / "bom.txt", "\ufeff正文在此".encode("utf-8"))

    loaded = load_document(tmp_path / "bom.txt", filename="bom.txt")

    assert loaded.text.startswith("正文在此")


# ---------------------------------------------------------------- PDF
def test_load_pdf_extracts_every_page_in_order(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "doc.pdf", ["First page text", "Second page text"])

    loaded = load_document(tmp_path / "doc.pdf", filename="doc.pdf")

    assert loaded.page_count == 2
    assert "First page text" in loaded.text
    assert "Second page text" in loaded.text
    assert loaded.text.index("First page text") < loaded.text.index("Second page text")


def test_pdf_without_text_layer_fails(tmp_path: Path) -> None:
    """只有图没有文字层的 PDF（扫描件）必须**判失败**，不能算「解析成功」。

    它的 `extract_text()` 返回空串而不报错，顺着走下去用户会得到一个
    界面上一切正常、却一条也检索不到的空知识库。
    """
    _make_pdf(tmp_path / "scan.pdf", [""])

    with pytest.raises(DocumentParseError):
        load_document(tmp_path / "scan.pdf", filename="scan.pdf")


# ---------------------------------------------------------------- DOCX
def test_load_docx_extracts_paragraphs(tmp_path: Path) -> None:
    _make_docx(tmp_path / "doc.docx", ["第一段：RAG 原理", "第二段：向量检索"])

    loaded = load_document(tmp_path / "doc.docx", filename="doc.docx")

    assert "第一段：RAG 原理" in loaded.text
    assert "第二段：向量检索" in loaded.text
    assert loaded.page_count is None


def test_fake_docx_fails_instead_of_riding_through(tmp_path: Path) -> None:
    """扩展名写 `.docx` 但内容不是 OOXML 包时判失败（D11：文件名只管准入）。

    准入阶段信客户端给的文件名，这里验证「信」的代价被**解析器自己的校验**兜住了 ——
    冒充的文件不会变成一个「已就绪」的文档。
    """
    _write(tmp_path / "fake.docx", b"this is definitely not a zip container")

    with pytest.raises(DocumentParseError):
        load_document(tmp_path / "fake.docx", filename="fake.docx")


def test_fake_pdf_fails_instead_of_riding_through(tmp_path: Path) -> None:
    _write(tmp_path / "fake.pdf", b"%PDF-not-really")

    with pytest.raises(DocumentParseError):
        load_document(tmp_path / "fake.pdf", filename="fake.pdf")


# ---------------------------------------------------------------- 空白与缺失
@pytest.mark.parametrize(("name", "data"), [("blank.txt", b"   \n\n  "), ("empty.md", b"")])
def test_whitespace_only_text_fails(tmp_path: Path, name: str, data: bytes) -> None:
    _write(tmp_path / name, data)

    with pytest.raises(DocumentParseError):
        load_document(tmp_path / name, filename=name)


def test_missing_file_fails_as_parse_error(tmp_path: Path) -> None:
    """文件不见了也归一成 `DocumentParseError`。

    调用方（解析线程）只需要捕一种异常就能把文档判为失败；
    分别处理 `FileNotFoundError` / `ValueError` / pypdf 的一串异常类型，
    必然漏掉一种，而漏掉的那种会让解析线程静默死掉、状态永远停在「解析中」。
    """
    with pytest.raises(DocumentParseError):
        load_document(tmp_path / "nope.md", filename="nope.md")


def test_unsupported_extension_rejected_by_loader(tmp_path: Path) -> None:
    """准入之外再拦一道：即使被绕过，加载器也不会去猜怎么解析。"""
    _write(tmp_path / "a.zip", b"PK\x03\x04")

    with pytest.raises(UnsupportedFormatError):
        load_document(tmp_path / "a.zip", filename="a.zip")
