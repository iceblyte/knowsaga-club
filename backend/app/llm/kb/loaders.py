"""文档解析：把上传的原文件抽成纯文本。

## 为什么不装 `langchain-community` 用它现成的三个加载器

原计划是 `PyPDFLoader` / `Docx2txtLoader` / `TextLoader`。装依赖时发现
这三个类都在 **`langchain-community`** 里 —— 它不在本项目的依赖树上，
也不被任何已装的 langchain 包依赖（实测 `importlib.util.find_spec` 返回 `None`）。
要拿到它们就得再拖进一个体量不小的包，而它做的事只是：

    pypdf.PdfReader(path) → 逐页 extract_text()
    docx2txt.process(path)
    path.read_text(encoding=...)

**而且现成件并不比这三十行更合用**：`TextLoader` 不做编码兜底（GBK 的 txt
会直接抛 `UnicodeDecodeError`），`PyPDFLoader` 也不校验「抽出来是不是空的」
（扫描件会安静地给你一份空文档）。这两件正好是本层必须守住的事，
所以自己写反而更短、也更准。

## 只收四种格式

`.pdf` / `.docx` / `.md` / `.txt`。`.doc` 不收：`docx2txt` 只认 OOXML 包，
`.doc` 是另一个二进制格式，收下它只会在解析阶段变成一句「解析失败」——
不如在准入阶段说清楚（design D11）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: 允许上传的扩展名（小写，含点）。改动这里必须同步改加载器映射与准入文案。
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".md", ".txt"})

#: 文本类扩展名：解码顺序一样，走同一个加载器。
_TEXT_EXTENSIONS: frozenset[str] = frozenset({".md", ".txt"})

#: 解码尝试顺序。为什么要兜底见 `_decode_text`。
_TEXT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030")


class UnsupportedFormatError(ValueError):
    """扩展名不在准入清单里。"""


class DocumentParseError(RuntimeError):
    """解析失败。

    与 `EmbeddingError` 同一条约定：**刻意不抛 `AppError`** ——
    这个异常产生在后台解析线程里，那里没有请求上下文，统一错误信封无从谈起。
    调用方（`kb_service`）把它转成文档的失败状态与可展示文案。

    ⚠️ **`str(这个异常)` 会原样进 `knowledge_documents.error_message`，
    也就是给用户看**（spec：面向用户的一句话与面向排查的细节分开存放）。
    所以抛它的时候只允许放**我们逐条写过的、面向人的句子**：
    第三方异常的类型与原文（`BadZipFile: File is not a zip file`）进日志，
    不进这里 —— 它对用户没有任何意义，还可能带出内部信息。
    """


#: 解析库抛异常时给用户看的那句话（技术细节进日志，见 `load_document`）。
_BROKEN_FILE = "这份文件没能解析成功，它可能已损坏或加密"


@dataclass(frozen=True)
class LoadedDocument:
    """一份解析好的文档。

    Attributes:
        text: 抽取出的纯文本（已去过首尾空白，但不做分块 —— 分块是下一层的事）。
        page_count: PDF 的页数；其它格式为 `None`。
            为什么不用 `0` 表示「不适用」：`0` 页在 PDF 里是个有意义的值
            （虽然那本来就是失败），把「不适用」和「确实是 0」压成同一个数
            会让排查时看不出区别。
    """

    text: str
    page_count: int | None = None


def ext_of(filename: str) -> str:
    """取小写扩展名（含点）；取不到时返回空串。

    ⚠️ **先取路径最后一段，再找最后一个点**。直接用 `rpartition(".")` 会把
    `dir.d/notes` 的扩展名算成 `.d/notes`。客户端可能把完整路径塞进文件名
    （`Taro.uploadFile` 的临时路径就是这样），所以这一步不能省。

    返回空串而不是抛异常：准入判定要的是一个能当布尔用的值。
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    _, dot, suffix = name.rpartition(".")
    if not dot:
        return ""
    return f".{suffix}".lower()


def is_supported_ext(filename: str) -> bool:
    """扩展名是否在准入清单里。"""
    return ext_of(filename) in SUPPORTED_EXTENSIONS


def _decode_text(raw: bytes) -> str:
    """按 `_TEXT_ENCODINGS` 依次尝试解码。

    为什么必须有兜底：Windows 的「另存为 txt」默认写 GBK，而中文用户手里的
    资料大量来自这一步。只按 UTF-8 硬解会抛 `UnicodeDecodeError`，
    症状是「这份文件一直解析失败」，而文件本身完全正常。

    `utf-8-sig` 排在最前：它会顺手吃掉 BOM，否则 BOM 会变成片段开头的
    一个不可见字符（检索与展示都看不出来，但确实在库里）。
    `gb18030` 是 GBK 的超集，用它而不是 `gbk` —— 生僻字不会在解码这一步就失败。

    全失败时抛 `DocumentParseError`：与其猜一个编码（猜错的症状是整份资料乱码，
    而乱码文本照样能被向量化、照样会被检索到），不如照实说解析不了。
    """
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError(
        f"文本解码失败（已尝试 {', '.join(_TEXT_ENCODINGS)}），可能是其它编码或二进制内容"
    )


def _load_text(path: Path, _filename: str) -> LoadedDocument:
    return LoadedDocument(text=_decode_text(path.read_bytes()))


def _load_pdf(path: Path, _filename: str) -> LoadedDocument:
    """逐页抽文本。页数一并返回（详情页要展示，也是排查「几页的内容检索不到」的依据）。"""
    from pypdf import PdfReader  # 惰性导入：不开这个功能就不加载

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        # 加密 PDF 的 extract_text() 会抛一串底层异常，这里给出可读原因
        raise DocumentParseError("这份 PDF 有密码保护，无法解析")
    pages = [page.extract_text() or "" for page in reader.pages]
    # 用换行连接：跨页的两段内容不该被粘成一句话，分块时也才能按段落切开
    return LoadedDocument(text="\n".join(pages), page_count=len(pages))


def _load_docx(path: Path, _filename: str) -> LoadedDocument:
    """`docx2txt` 抽段落文本。

    ⚠️ 它只认 OOXML 包（zip）。扩展名冒充成 `.docx` 的文件会在这里抛异常 ——
    这正是 D11 说的「准入信文件名、内容由解析器自己验证」的落点：
    冒充的文件不会变成一个「已就绪但内容为空」的文档。
    """
    import docx2txt  # 惰性导入

    return LoadedDocument(text=docx2txt.process(str(path)))


#: 扩展名 → 加载器。`_load_text` 覆盖 `.md` / `.txt` 两种。
_LOADERS: dict[str, Callable[[Path, str], LoadedDocument]] = {
    ".pdf": _load_pdf,
    ".docx": _load_docx,
    ".md": _load_text,
    ".txt": _load_text,
}


def load_document(path: Path, *, filename: str) -> LoadedDocument:
    """按扩展名选择加载器并解析。

    Args:
        path: 原文件在本地的落盘路径。
        filename: 客户端给的原始文件名（**只用来判扩展名**，见 design D11）。

    Returns:
        `LoadedDocument`；`text` 已去过首尾空白，且**保证非空**。

    Raises:
        UnsupportedFormatError: 扩展名不在准入清单里。
        DocumentParseError: 文件缺失 / 解码失败 / 格式与扩展名不符 /
            抽取结果全空白（扫描件 PDF 是最常见的那一种）。
    """
    extension = ext_of(filename)
    loader = _LOADERS.get(extension)
    if loader is None:
        raise UnsupportedFormatError(f"不支持的文件格式：{filename or '(空文件名)'}")

    if not path.is_file():
        raise DocumentParseError(f"原文件不存在或不是文件：{path.name}")

    try:
        loaded = loader(path, filename)
    except (UnsupportedFormatError, DocumentParseError):
        raise
    except Exception as exc:  # noqa: BLE001 - 解析库的异常类型多且会随版本变
        # 归一成一种异常的理由同 `EmbeddingError`：调用方捕一种就能给出结论，
        # 而枚举各库的异常类型必然漏掉一种，漏掉的那种会让解析状态永远停在「解析中」。
        #
        # ⚠️ 技术细节进**日志**，用户看到的是 `_BROKEN_FILE`：
        # pypdf 的 `PdfReadError`、zipfile 的 `BadZipFile` 之类原样贴给用户，
        # 既看不懂也不算「一句可展示的话」（spec 明确要求两者分开存放）。
        logger.warning("解析失败：%s（%s: %s）", path.name, type(exc).__name__, exc)
        raise DocumentParseError(_BROKEN_FILE) from exc

    text = loaded.text.strip()
    if not text:
        # 扫描件 PDF 走到这里：extract_text() 返回空串而**不报错**，
        # 顺着走下去用户会得到一个界面上正常、却一条也检索不到的空知识库。
        raise DocumentParseError("未能从文件中提取到任何文字（扫描件或图片型内容无法解析）")
    return LoadedDocument(text=text, page_count=loaded.page_count)
