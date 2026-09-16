#!/usr/bin/env python
"""把原型 HTML 导出成可读的结构文本，便于逐屏比对实现。

用法：
    python tools/read_proto.py 02-挑战副本.html            # 打印全部屏
    python tools/read_proto.py 02-挑战副本.html --out f.txt # 写入文件
    python tools/read_proto.py 01-核心闭环.html --screen 3  # 只打印第 3 屏

处理内容：
- 内联 <svg> 折叠为 [SVG:label]，避免刷屏
- 去掉 class 之外的 inline style（保留结构）
- 在标签边界处换行，形成缩进可读的层级
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_DIR = REPO_ROOT / "prototype"


def _svg_repl(m: re.Match[str]) -> str:
    svg = m.group(0)
    label = re.search(r'aria-label="([^"]+)"', svg)
    vb = re.search(r'viewBox="([^"]+)"', svg)
    wh = re.search(r'width="([^"]+)"\s+height="([^"]+)"', svg)
    parts = []
    if label:
        parts.append(label.group(1))
    if wh:
        parts.append(f"{wh.group(1)}x{wh.group(2)}")
    if vb:
        parts.append(f"vb={vb.group(1)}")
    return f"[SVG:{' '.join(parts)}]" if parts else "[SVG]"


def prettify(segment: str) -> str:
    """把一段 HTML 整理成可读文本。"""
    s = re.sub(r"<style\b.*?</style>", "", segment, flags=re.S)
    s = re.sub(r"<script\b.*?</script>", "", s, flags=re.S)
    s = re.sub(r"<svg\b.*?</svg>", _svg_repl, s, flags=re.S)
    # 折叠 style 属性值，只留关键声明
    s = re.sub(r'\sstyle="([^"]*)"', lambda m: f' style="{m.group(1).strip()}"', s)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    # 标签边界换行 + 简单缩进
    s = re.sub(r">\s*<", ">\n<", s)
    lines: list[str] = []
    depth = 0
    for raw in s.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^</", line):
            depth = max(0, depth - 1)
        lines.append("  " * depth + line)
        if re.match(r"^<[a-zA-Z]", line) and not re.match(
            r"^<[^>]+/>$", line
        ) and not re.match(r"^<(br|img|input|hr)\b", line):
            if "</" not in line:
                depth += 1
    return "\n".join(lines)


def split_screens(html: str) -> list[tuple[str, str]]:
    """按 <figure> 切屏，返回 (标题, 内容) 列表。"""
    out: list[tuple[str, str]] = []
    for fig in re.split(r"<figure\b", html)[1:]:
        title_m = re.search(r"<b>([^<]+)</b>", fig)
        title = title_m.group(1) if title_m else "(无标题)"
        out.append((title, prettify(fig)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("filename", help="prototype/ 下的 html 文件名")
    ap.add_argument("--out", help="输出到文件")
    ap.add_argument("--screen", type=int, help="只输出第 N 屏（从 1 开始）")
    ap.add_argument("--list", action="store_true", help="只列出屏标题")
    args = ap.parse_args()

    path = PROTOTYPE_DIR / args.filename
    if not path.is_file():
        print(f"[x] 文件不存在: {path}")
        return 1

    screens = split_screens(path.read_text(encoding="utf-8"))

    if args.list:
        for i, (title, _) in enumerate(screens, 1):
            print(f"{i:2}. {title}")
        return 0

    if args.screen:
        if not 1 <= args.screen <= len(screens):
            print(f"[x] 屏号超范围（共 {len(screens)} 屏）")
            return 1
        title, body = screens[args.screen - 1]
        text = f"{'=' * 74}\n第 {args.screen} 屏 · {title}\n{'=' * 74}\n{body}\n"
    else:
        chunks = [
            f"{'=' * 74}\n第 {i} 屏 · {t}\n{'=' * 74}\n{b}\n"
            for i, (t, b) in enumerate(screens, 1)
        ]
        text = "\n".join(chunks)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] 已写入 {args.out}（{len(text)} 字符，{len(screens)} 屏）")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
