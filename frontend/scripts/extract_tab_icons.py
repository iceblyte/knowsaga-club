#!/usr/bin/env python
"""从 prototype/*.html 抽取底部标签栏图标，生成 Taro 可用的资源模块。

产物：
    frontend/src/assets/icons/svg/*.svg  —— 原始矢量副本（人工核对用，也是光栅化的输入）
    frontend/src/assets/icons/tab.ts     —— TAB_ICONS[name][state] -> PNG 模块引用

## 两步流水线（顺序不能反）

    python frontend/scripts/extract_tab_icons.py     # 原型 → svg/*.svg + tab.ts
    python frontend/scripts/rasterize_tab_icons.py   # svg/*.svg → png/*.png

`tab.ts` 里 import 的 PNG 由第二步产出，所以第二步没跑之前构建会报找不到文件。

## 为什么要烘焙两份颜色

图标在原型里用 `class="fi"` 描边、颜色跟随 `currentColor`。但 data URI / 静态资源
里没有 CSS 继承上下文，`currentColor` 不会生效，所以**每个状态各烘焙一份颜色**：
未选中 `$ink3`、选中 `$magic`（与 app.config.ts 的 tabBar.color / selectedColor 一致）。

## 为什么标签栏用 PNG 而不是 SVG

微信官方 `image` 组件文档支持 SVG，但同时列出三条限制（不支持百分比单位、
不支持 `<style>`、`mode=scaleToFill` 时 WebView 会居中）。而抽出来的图标**只有
viewBox、没有 width/height**，内在尺寸推导属于文档未兜底的行为。标签栏是固定
81×81 的位图场景，用 PNG 一次性消除这个不确定性；svg/ 目录的矢量副本继续保留，
供人工核对与后续其它尺寸复用。

用法（在仓库根目录）：
    python frontend/scripts/extract_tab_icons.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_DIR = REPO_ROOT / "prototype"
SOURCE_HTML = PROTOTYPE_DIR / "01-核心闭环.html"
OUT_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "icons"
SVG_OUT_DIR = OUT_DIR / "svg"
PNG_OUT_DIR = OUT_DIR / "png"

# 与 app.config.ts 的 tabBar.color / selectedColor 保持一致
COLOR_NORMAL = "#9A8870"  # $ink3
COLOR_ACTIVE = "#2F6BD8"  # $magic

# tab 顺序必须与 app.config.ts 的 tabBar.list 一致
TAB_KEYS = ["hall", "workshop", "report", "guild", "mine"]
TAB_LABELS = {
    "hall": "社团大厅",
    "workshop": "卷轴工坊",
    "report": "冒险日志",
    "guild": "公会社交",
    "mine": "我的",
}

# 原型里的图标语法类（见设计规范 CSS：.fi 描边 / .so 填充，颜色跟随 currentColor）
FILL_NONE = 'fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"'
FILL_SOLID = 'fill="{color}" stroke="none"'


def recolor(svg: str, color: str) -> str:
    """把 class="fi" / class="so" 替换成烘焙好的填充声明。"""
    svg = re.sub(r'class="fi"', FILL_NONE.format(color=color), svg)
    svg = re.sub(r'class="so"', FILL_SOLID.format(color=color), svg)
    svg = re.sub(r"\sclass=\"[^\"]*\"", "", svg)
    svg = re.sub(r"\s+", " ", svg).strip()
    if "xmlns=" not in svg:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


def extract_icons() -> list[str]:
    """从 01-核心闭环.html 的 .tabbar 块里按顺序取出 5 个图标。"""
    text = SOURCE_HTML.read_text(encoding="utf-8")
    start = text.find('class="tabbar"')
    if start < 0:
        print("[x] 未找到 .tabbar 块", file=sys.stderr)
        return []

    # 截到 tabbar 结束（后续是 figcaption）
    seg = text[start : start + 4000]
    end = seg.find("</figcaption>")
    if end > 0:
        seg = seg[:end]

    icons = re.findall(r"<svg\b.*?</svg>", seg, re.S)
    if len(icons) != len(TAB_KEYS):
        print(f"[!] 期望 {len(TAB_KEYS)} 个图标，实际找到 {len(icons)} 个", file=sys.stderr)
    return icons


def main() -> int:
    if not SOURCE_HTML.is_file():
        print(f"[x] 找不到原型文件: {SOURCE_HTML}", file=sys.stderr)
        return 1

    icons = extract_icons()
    if not icons:
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SVG_OUT_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[str] = []  # 按 tab 顺序收集 key

    for key, raw in zip(TAB_KEYS, icons):
        (SVG_OUT_DIR / f"{key}-normal.svg").write_text(
            recolor(raw, COLOR_NORMAL), encoding="utf-8"
        )
        (SVG_OUT_DIR / f"{key}-active.svg").write_text(
            recolor(raw, COLOR_ACTIVE), encoding="utf-8"
        )
        entries.append(key)

    # 生成的 tab.ts 以 ES import 引用 PNG（types/global.d.ts 已声明 *.png 模块）
    lines = [
        "// ⚠️ 本文件由 frontend/scripts/extract_tab_icons.py 自动生成，请勿手工修改。",
        "//",
        "// 重新生成是**两步**，顺序不能反：",
        "//   python frontend/scripts/extract_tab_icons.py    # 原型 → svg/*.svg + 本文件",
        "//   python frontend/scripts/rasterize_tab_icons.py  # svg/*.svg → png/*.png",
        "//",
        "// 标签栏图标源自 prototype/01-核心闭环.html 的内联 SVG，",
        "// 两个状态各烘焙一份颜色：未选中 " + COLOR_NORMAL + "（$ink3） / 选中 " + COLOR_ACTIVE + "（$magic）。",
        "//",
        "// 为什么标签栏用 PNG 而不是 SVG：微信 image 组件虽然官方支持 svg，但文档同时列出",
        "// 三条限制（不支持百分比单位、不支持 <style>、mode=scaleToFill 时 WebView 会居中），",
        "// 而抽出的图标只有 viewBox、没有 width/height，尺寸推导属于文档未兜底的行为。",
        "// 标签栏是固定 81×81 的位图场景，PNG 一次性消除这个不确定性；",
        "// svg/ 目录保留矢量副本供人工核对。",
        "",
    ]

    for key in entries:
        lines.append(f"import {key}Normal from './png/{key}-normal.png'")
        lines.append(f"import {key}Active from './png/{key}-active.png'")
    lines.append("")

    lines.append("/** 标签标识（顺序与 app.config.ts 的 tabBar.list 一致） */")
    lines.append("export type TabKey =")
    lines.extend(f"  | '{key}'" for key in entries)
    lines[-1] += ";"
    lines.append("")

    lines.append("/** 标签图标：name -> { normal, active }，两个状态各自一张已烘焙颜色的 PNG */")
    lines.append("export const TAB_ICONS: Record<TabKey, { normal: string; active: string }> = {")
    for key in entries:
        lines.append(f"  // {TAB_LABELS[key]}")
        lines.append(f"  {key}: {{ normal: {key}Normal, active: {key}Active }},")
    lines.append("};")
    lines.append("")

    lines.append("/** 标签中文名 */")
    lines.append("export const TAB_TEXTS: Record<TabKey, string> = {")
    for key in entries:
        lines.append(f"  {key}: '{TAB_LABELS[key]}',")
    lines.append("};")
    lines.append("")

    lines.append("/** 标签路由（与 app.config.ts 的 tabBar.list 一致） */")
    lines.append("export const TAB_PATHS: Record<TabKey, string> = {")
    for key in entries:
        lines.append(f"  {key}: 'pages/{key}/index',")
    lines.append("};")
    lines.append("")

    lines.append("export default TAB_ICONS;")
    lines.append("")

    (OUT_DIR / "tab.ts").write_text("\n".join(lines), encoding="utf-8")

    print(f"[ok] 导出 {len(entries)} 个标签图标（每 2 个状态）-> {OUT_DIR.name}/tab.ts")
    for key in entries:
        marks = []
        for state in ("normal", "active"):
            if (PNG_OUT_DIR / f"{key}-{state}.png").is_file():
                marks.append(f"{state} ok")
            else:
                marks.append(f"{state} 缺 PNG")
        print(f"     {key:<10} {', '.join(marks)}")
    print("     svg/ 为矢量副本；tab.ts 引用的是 png/，缺失时请先跑 rasterize_tab_icons.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
