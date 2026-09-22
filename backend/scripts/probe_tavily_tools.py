"""一次性探查脚本：验证 `langchain-tavily` 的两个官方工具在本项目里真能用。

**它不接进出题链**，只在真实 key 与真实网络下回答六个问题 ——
这六个答案会直接决定 `app/llm/search/` 的截断常量、错误判定与 country 策略：

1. DeepSeek（思考模式已关）能否在 `bind_tools` 后返回带 `tool_calls` 的 `AIMessage`？
2. `tavily_search` 真实命中后，**单条 `content` 多长**、**分段标记长什么样**？
3. `tavily_extract` 返回的 `raw_content` **单页多长**、**响应体里到底有没有 `title`**？
4. 0 命中时是**抛异常**还是**返回空数组**？
5. HTTP 失败时是 **`{"error": ...}`** 还是**抛异常**？
6. 同一个中文主题，`country="china"` 与不设 country 的**命中差异**有多大？

## 用法

    cd backend
    ./.venv/Scripts/python.exe scripts/probe_tavily_tools.py                 # 全部六项
    ./.venv/Scripts/python.exe scripts/probe_tavily_tools.py --only 3,4      # 只补测某几项
    ./.venv/Scripts/python.exe scripts/probe_tavily_tools.py --out report.txt

需要根 `.env` 里有可用的 `TAVILY_API_KEY` 与 `DEEPSEEK_API_KEY`。
会消耗少量 Tavily 额度（全量约 8–10 次调用；`--only` 只花被选中那几项的）。

⚠️ **一定要用 `--out` 落盘，不要靠 PowerShell 的 `*>` 重定向** —— PS 会用控制台编码
（中文 Windows 为 GBK）去解码本进程的 UTF-8 字节流，中文标题会变成乱码且**不可逆**
（部分字节落进 PUA，回解会失败）。`--out` 由脚本自己按 UTF-8 写，往返无损。

## 为什么不写成 pytest 用例

它**必须联网且必须花真实额度**，与「pytest 里 LLM 一律 mock」的项目红线冲突。
探查结论会落到 `docs/MVP开发计划.md`，此后代码侧只用 mock 覆盖。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.llm.langchain_factory import build_chat_model  # noqa: E402

# 一个「模型训练数据必然覆盖不到」的英文新概念，与用户上报的场景一致
NEW_CONCEPT_EN = "Harness Engineering"
# 一个中文侧的新概念主题
NEW_CONCEPT_ZH = "具身智能 世界模型 最新进展"
# ⚠️ 第一版用 Tavily 自己的文档页，上游回「No extracted results found」（该站不允许抓取）。
#    换成第一轮 search 真实命中、且正文可抓的页面 —— 否则验不到 raw_content 与 title。
TARGET_URL = "https://milvus.io/blog/harness-engineering-ai-agents.md"
# 备用抓取目标（Wikipedia 正文长、结构稳定，用来量「大体量页面」的上界）
TARGET_URL_2 = "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"

SEP = "=" * 78


# ---------------------------------------------------------------- 报告输出
class _Tee:
    """同时写控制台与报告文件。控制台写失败（编码/管道）不该拖垮报告。"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, text: str):
        for st in self._streams:
            try:
                st.write(text)
            except Exception:  # noqa: BLE001
                pass
        return len(text)

    def flush(self):
        for st in self._streams:
            try:
                st.flush()
            except Exception:  # noqa: BLE001
                pass


def _parse_argv() -> tuple[set[int], Path | None]:
    only: set[int] = set()
    out: Path | None = None
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = {int(x) for x in argv[i + 1].split(",") if x.strip().isdigit()}
        elif a == "--out" and i + 1 < len(argv):
            out = Path(argv[i + 1])
    return only, out


ONLY, OUT_PATH = _parse_argv()


def head(n: int, title: str) -> None:
    print(f"\n{SEP}\n[{n}] {title}\n{SEP}")


def safe(fn, *args, **kwargs):
    """执行并返回 (ok, value_or_traceback)。绝不因探查项失败而中断整份报告。"""
    try:
        return True, fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - 探查脚本要看到一切异常形态
        return False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"


def describe_markers(text: str) -> str:
    """报告上游 `chunks_per_source` 留下的分段标记形态。"""
    return (
        f"<chunk 标记={'<chunk' in text} / [...]={'[...]' in text} / "
        f"省略号「…」={'…' in text}"
    )


# ---------------------------------------------------------------- 构造工具
def build_tools(country: str | None, *, tag: str, exact_match: bool = False):
    """按给定实例级参数构造两个官方工具。

    ⚠️ 上游把 `country` / `max_results` / `exact_match` / `include_answer` /
    `include_raw_content` / `include_usage` / `auto_parameters` / `include_favicon` /
    `include_image_descriptions` 列为 **`forbidden_params`** ——
    这些**只能在构造实例时给**，调用时传会直接抛错（见 `TavilySearch._run`）。
    """
    from langchain_tavily import TavilyExtract, TavilySearch
    from langchain_tavily._utilities import (
        TavilyExtractAPIWrapper,
        TavilySearchAPIWrapper,
    )

    s = get_settings()
    search = TavilySearch(
        # 显式把 key 交给 APIWrapper：不依赖构造期的环境变量回退
        api_wrapper=TavilySearchAPIWrapper(tavily_api_key=s.tavily_api_key),
        max_results=5,
        country=country,
        exact_match=exact_match,
        include_answer=False,
        include_raw_content=False,
        include_images=False,
        include_image_descriptions=False,
        include_favicon=False,
        include_usage=False,
        auto_parameters=False,
        handle_tool_error=True,
        name="tavily_search",
        description=f"[{tag}] 关键词检索",
    )
    extract = TavilyExtract(
        # ⚠️ 上游这个字段名是 `apiwrapper`（没有下划线），不是 `api_wrapper`
        apiwrapper=TavilyExtractAPIWrapper(tavily_api_key=s.tavily_api_key),
        extract_depth="basic",
        format="markdown",
        include_favicon=False,
        include_usage=False,
        handle_tool_error=True,
        name="tavily_extract",
        description=f"[{tag}] 按网址读取整页",
    )
    return search, extract


# ---------------------------------------------------------------- 六项探查
def probe_1_bind_tools(search, extract) -> None:
    """① DeepSeek 关闭思考后，能否在 bind_tools 下返回 tool_calls。"""
    head(1, "DeepSeek bind_tools 后是否返回 tool_calls")
    ok, res = safe(
        lambda: build_chat_model("quiz")
        .bind_tools([search, extract])
        .invoke(f"我需要了解「{NEW_CONCEPT_EN}」这个概念的准确含义，请先联网检索资料。")
    )
    if not ok:
        print(res)
        return
    calls = getattr(res, "tool_calls", None) or []
    print(f"tool_calls 数量 = {len(calls)}")
    for c in calls:
        print(f"  - name={c.get('name')} args={c.get('args')}")
    print(f"content 长度 = {len(getattr(res, 'content', '') or '')}")
    print("结论①：bind_tools 可用" if calls else "结论①：**未返回 tool_calls**，需检查 Prompt")


def probe_2_search_shape(search) -> None:
    """② 单条 content 体积 + 分段标记形态（决定截断常量与清洗规则）。"""
    head(2, "tavily_search 单条 content 的字符数与分段标记")
    ok, res = safe(search.invoke, {"query": NEW_CONCEPT_EN})
    if not ok:
        print(res)
        return
    print(f"返回类型 = {type(res).__name__}")
    if not isinstance(res, dict):
        print(f"非预期返回：{str(res)[:400]}")
        return
    print(f"顶层键 = {list(res.keys())}")
    if "error" in res:
        print(f"!! 返回了 error 键：{res['error']!r}")
        return
    results = res.get("results") or []
    print(f"命中条数 = {len(results)}")
    lens = []
    for i, r in enumerate(results[:3], 1):
        content = r.get("content", "") or ""
        lens.append(len(content))
        print(
            f"  #{i} title={r.get('title')!r}\n"
            f"      url={r.get('url')}\n"
            f"      content 字符数={len(content)}  {describe_markers(content)}\n"
            f"      score={r.get('score')}\n"
            f"      include_raw_content=False 时 raw_content 的值 = {r.get('raw_content')!r}"
        )
    if results:
        first = results[0].get("content") or ""
        idx = first.find("[...]")
        if idx >= 0:
            print(
                "      「[...]」上下文（前后各 90 字符）：\n"
                f"        ...{first[max(0, idx - 90): idx + 95]!r}..."
            )
        else:
            print("      content 中未出现字面「[...]」")
    print(f"结论②：单条 content 约 {lens[0] if lens else 0} 字符，共 {len(results)} 条")


def probe_3_extract_shape(extract) -> None:
    """③ 单页 raw_content 体积 + 有没有 title（决定标题兜底与每轮预算）。"""
    head(3, "tavily_extract 单页 raw_content 体积与响应里有没有 title")
    # 两路都要看：`invoke()` 是**模型看到的东西**（handle_tool_error 会改形态），
    # `_run()` 是**上游原始返回**（dict）。只看一路会把「调用失败」误读成「返回了字符串」。
    for label, url in (("主目标", TARGET_URL), ("备用(Wikipedia)", TARGET_URL_2)):
        print(f"\n--- {label}: {url} ---")
        ok_raw, raw = safe(extract._run, urls=[url])
        print(f"[a] 上游原始返回 _run(): ok={ok_raw} type={type(raw).__name__}")
        if not ok_raw:
            print(f"    异常 = {str(raw)[:300]}")
        elif isinstance(raw, dict):
            print(f"    顶层键 = {list(raw.keys())}")
            if "error" in raw:
                print(f"    !! error 键 = {raw['error']!r}")
            results = raw.get("results") or []
            print(f"    结果条数 = {len(results)} / failed_results = {raw.get('failed_results')}")
            for i, r in enumerate(results[:2], 1):
                rc = r.get("raw_content") or ""
                md_line = next(
                    (ln.strip() for ln in rc.splitlines() if ln.strip().startswith("#")), ""
                )
                print(
                    f"    #{i} 该条键 = {list(r.keys())}\n"
                    f"        **有 title 键吗** = {'title' in r} / url = {r.get('url')}\n"
                    f"        raw_content 字符数 = {len(rc)}\n"
                    f"        {describe_markers(rc)}\n"
                    f"        首个 markdown 标题行（标题兜底①） = {md_line[:120]!r}\n"
                    f"        URL host（标题兜底②） = {urlparse(r.get('url') or url).netloc!r}\n"
                    f"        首行 = {(rc.splitlines() or [''])[0][:140]!r}"
                )
        else:
            print(f"    raw 内容 = {str(raw)[:400]}")

        ok, res = safe(extract.invoke, {"urls": [url]})
        print(f"[b] invoke() 返回: ok={ok} type={type(res).__name__}")
        if not ok:
            print(f"    {str(res)[:400]}")
        elif isinstance(res, str):
            print(f"    ⚠️ 返回字符串（而不是 dict）—— 观察它到底是错误文本还是正文：\n{res[:400]}")
        else:
            print(f"    顶层键 = {list(res.keys())}")
            if "error" in res:
                print(f"    !! error 键 = {res['error']!r}（模型看到的是「调用失败」而非资料）")
            else:
                rl = res.get("results") or []
                size = len((rl[0].get("raw_content") or "")) if rl else 0
                print(f"    结果条数 = {len(rl)}，单页 raw_content 约 {size} 字符")
    print("结论③：见上面两路的实测值（单页体积决定每轮取材的注入预算）")


def probe_4_zero_hits(s) -> None:
    """④ 真正的 0 命中时，是抛异常还是返回空数组（决定降级判定点）。"""
    head(4, "0 命中：抛异常还是空数组")
    # ⚠️ 四个**无效用例**先记下来，别再犯：
    #   x `include_domains=[".invalid 域名"]` → Tavily 回 400（验到的是 HTTP 失败，不是 0 命中）
    #   x `include_domains=["arxiv.org"]` + 乱码关键词 → 仍回 5 条（域名限定没起过滤作用）
    #   x `start_date=未来` → 回 400 `start_date cannot be in the future`
    #   x `exact_match=True` + 不带引号的短语 → 回 400
    #     `exact_match=true requires a quoted phrase in the query`
    # 真正能搜空的办法：`exact_match=True`（实例级参数）+ **带引号**的必然不存在的短语。
    gibberish = '"zqxwvbk pmnlqrst uvwxyz 483920 718264"'
    for label, kwargs, exact in (
        ("exact_match=True + 引号短语（预期 0 命中）", {"query": gibberish}, True),
        ("exact_match=True + 真实引号短语（对照组）", {"query": f'"{NEW_CONCEPT_EN}"'}, True),
    ):
        only_search, _ = build_tools(None, tag=label, exact_match=exact)
        ok, res = safe(only_search.invoke, kwargs)
        if not ok:
            print(f"  [{label}] **抛了异常**：{str(res)[:300]}")
            continue
        if isinstance(res, str):
            print(f"  [{label}] 返回**字符串**：{res[:300]}")
            continue
        if not isinstance(res, dict):
            print(f"  [{label}] 非预期类型 {type(res).__name__}：{str(res)[:300]}")
            continue
        if "error" in res:
            print(f"  [{label}] 返回 error 键：{res['error']!r}")
            continue
        n = len(res.get("results") or [])
        rest = {k: v for k, v in res.items() if k != "results"}
        print(f"  [{label}] dict，results 条数={n}，其余字段={rest}")
        if n == 0:
            print("  ⇒ 结论④：**0 命中时正常返回、results 为空数组**（不抛异常）")


def probe_5_http_error(s) -> None:
    """⑤ HTTP 失败被吞成正常返回值还是抛异常（决定采集器要不要显式判 error 键）。"""
    head(5, 'HTTP 401（错误 key）：{"error": ...} 还是抛异常')
    bad, _ = build_tools_factory_with_key("tvly-invalid-000000000000")
    ok, res = safe(bad.invoke, {"query": "test"})
    if ok:
        print(f"**没有抛异常**，返回类型={type(res).__name__}")
        print(f"值 = {str(res)[:500]}")
        print("结论⑤：失败被吞成正常返回值（采集器必须显式判 error 键）")
    else:
        print(f"**抛了异常**：{str(res)[:500]}")
        print("结论⑤：失败以异常抛出")


def build_tools_factory_with_key(key: str):
    """用指定（错误的）key 造一个 search 工具，验 HTTP 失败的形态。"""
    from langchain_tavily import TavilySearch
    from langchain_tavily._utilities import TavilySearchAPIWrapper

    return (
        TavilySearch(
            api_wrapper=TavilySearchAPIWrapper(tavily_api_key=key),
            max_results=3,
            country=None,
            handle_tool_error=True,
        ),
        None,
    )


def probe_6_country(s) -> None:
    """⑥ 中文主题下 country='china' 与不设 country 的命中差异。"""
    head(6, "中文主题：country='china' vs 不设 country 的命中差异")
    for country in ("china", None):
        # ⚠️ country 是**实例级**参数（见 _run 的 forbidden_params），
        #    必须为每一种取值单独构造工具 —— 复用同一个实例等于没测出差异
        cn_search, _ = build_tools(country, tag=f"country={country}")
        ok, res = safe(cn_search.invoke, {"query": NEW_CONCEPT_ZH})
        label = f"country={country!r}"
        if not ok:
            print(f"  {label}: 调用失败 {str(res)[:200]}")
            continue
        if not isinstance(res, dict) or "error" in res:
            print(f"  {label}: 非预期返回 {str(res)[:200]}")
            continue
        results = res.get("results") or []
        cn = sum(
            1 for r in results if any("\u4e00" <= ch <= "\u9fff" for ch in (r.get("title") or ""))
        )
        domains = [urlparse(r.get("url") or "").netloc for r in results]
        print(f"  {label}: 命中 {len(results)} 条，标题含中文 {cn} 条")
        print(f"      域名 = {domains}")
        for r in results[:3]:
            print(f"      - {r.get('title')!r}")


PROBES = {
    1: ("DeepSeek bind_tools", probe_1_bind_tools),
    2: ("search 返回形态", probe_2_search_shape),
    3: ("extract 返回形态", probe_3_extract_shape),
    4: ("0 命中形态", probe_4_zero_hits),
    5: ("HTTP 失败形态", probe_5_http_error),
    6: ("country 差异", probe_6_country),
}


def main() -> int:
    # 报告自己按 UTF-8 写盘，绕开 PowerShell 的编码破坏（见模块 docstring）
    if OUT_PATH is not None:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = OUT_PATH.open("w", encoding="utf-8", newline="\n")
        sys.stdout = _Tee(sys.stdout, fh)  # type: ignore[assignment]

    s = get_settings()
    print(f"TAVILY key 前缀 = {s.tavily_api_key[:5]!r} (len={len(s.tavily_api_key)})")
    print(f"DeepSeek model  = {s.deepseek_model} / thinking={s.deepseek_thinking}")
    print(f"本次探查项 = {sorted(ONLY) if ONLY else '全部(1-6)'}")
    if not s.tavily_api_key:
        print("!! 未配置 TAVILY_API_KEY，无法探查")
        return 2

    search, extract = build_tools(None, tag="probe")
    for n, (label, fn) in PROBES.items():
        if ONLY and n not in ONLY:
            continue
        try:
            if n == 3:
                fn(extract)
            elif n == 2:
                fn(search)
            elif n == 1:
                fn(search, extract)
            else:
                fn(s)
        except BaseException as exc:  # noqa: BLE001 - 任一项炸掉也要把报告写完
            print(f"!! 探查项 {n}（{label}）炸了：{type(exc).__name__}: {exc}")
            print(traceback.format_exc(limit=4))

    print(f"\n{SEP}\n探查结束。以上结论请原样记进 docs/MVP开发计划.md\n{SEP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
