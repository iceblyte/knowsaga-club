#!/usr/bin/env python
"""从 prototype/*.html 抽取底部标签栏图标，生成 Taro 可用的资源模块。

产物：
    frontend/src/assets/icons/svg/*.svg  —— 原始矢量副本（人工核对用，也是光栅化的输入）
    frontend/src/assets/icons/tab.ts     —— 主题 -> 图标集 -> PNG 模块引用

## 两步流水线（顺序不能反）

    python frontend/scripts/extract_tab_icons.py     # 原型 → svg/*.svg + tab.ts
    python frontend/scripts/rasterize_tab_icons.py   # svg/*.svg → png/<theme>/*.png

`tab.ts` 里 import 的 PNG 由第二步产出，所以第二步没跑之前构建会报找不到文件。

## 为什么要烘焙两份颜色（而且每套主题各来一遍）

图标在原型里用 `class="fi"` 描边、颜色跟随 `currentColor`。但 data URI / 静态资源
里没有 CSS 继承上下文，`currentColor` 不会生效，所以**每个状态各烘焙一份颜色**。

模板主题化之后又多了第二层：**颜色在像素里，CSS 变量够不到它**。所以第二步会
按主题各出一套位图，本文件则把「主题 → 图标集」的映射一起生成出来。

    svg/*.svg（本脚本产出）  只保留**默认主题 paper** 的烘焙色（#9A8870 / #2F6BD8），
                            作为矢量副本供人工核对；其余主题由第二步换色得到。
    png/<theme>/*.png        5 套主题各 10 张，颜色取自各主题的
                            `--k-ink-3` / `--k-magic-ink`（与标签栏文字同色）。

⚠️ 选 `magic-ink` 而不是 `magic`：前者是主色的「文字档」。浅色品牌（青柠）的
`$magic` = #70C000 压在自己的标签栏底上只有 2.12:1，配方专门求解了 `magic-ink`；
图标若取 `magic` 就在资源层把那个坑重挖了一遍。

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

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_DIR = REPO_ROOT / "prototype"
SOURCE_HTML = PROTOTYPE_DIR / "01-核心闭环.html"
OUT_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "icons"
SVG_OUT_DIR = OUT_DIR / "svg"
PNG_OUT_DIR = OUT_DIR / "png"
THEMES_JSON = REPO_ROOT / "shared" / "ui-themes.json"

# 默认主题 paper 的烘焙色（= tokens.scss 里 $ink3 / $magic-ink 的兜底字面量，
# 也 = app.config.ts 的 tabBar.color / selectedColor）。
# 其余 4 套主题的色值不在这里 —— 它们在 rasterize_tab_icons.py 里从 _themes.scss 读。
COLOR_NORMAL = "#9A8870"  # $ink3
COLOR_ACTIVE = "#2F6BD8"  # $magic-ink（默认主题里与 $magic 同值）

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


def read_themes() -> list[tuple[str, str]]:
    """`[(id, name), …]`，**paper 在最前**。

    顺序必须与 `constants/ui-theme-tokens.ts` 的 `UI_THEME_IDS` 一致 —— 那边也是
    从同一份 JSON 推出来的（`gen_theme_scss.mjs` 生成），两边都靠 JSON 定序才不会错位。
    """
    if not THEMES_JSON.is_file():
        print(f"[x] 找不到主题真源 {THEMES_JSON}", file=sys.stderr)
        raise SystemExit(1)
    themes = json.loads(THEMES_JSON.read_text(encoding="utf-8"))["themes"]
    if not themes:
        print(f"[x] {THEMES_JSON} 里 themes 为空", file=sys.stderr)
        raise SystemExit(1)
    return [("paper", "纸与印")] + [(t["id"], t["name"]) for t in themes]


def render_tab_ts(entries: list[str], themes: list[tuple[str, str]]) -> str:
    """生成 `tab.ts`：`主题 -> 图标集 -> PNG`。

    PNG 引用由 ES import 写死（`types/global.d.ts` 已声明 `*.png` 模块）——
    **不用模板字符串拼路径**，否则打包器看不到依赖，资源不会进包。
    """
    lines = [
        "// ⚠️ 本文件由 frontend/scripts/extract_tab_icons.py 自动生成，请勿手工修改。",
        "//",
        "// 重新生成是**两步**，顺序不能反：",
        "//   python frontend/scripts/extract_tab_icons.py    # 原型 → svg/*.svg + 本文件",
        "//   python frontend/scripts/rasterize_tab_icons.py  # svg/*.svg → png/<theme>/*.png",
        "//",
        f"// svg/*.svg 只保留**默认主题 paper** 的烘焙色（{COLOR_NORMAL} / {COLOR_ACTIVE}），",
        "// 作为矢量副本供人工核对；各主题的位图由第二步换色光栅化得到。",
        "//",
        "// 为什么每套主题各一套 PNG：**图标颜色在像素里，CSS 变量够不到它**。",
        "// 颜色取自各主题的 --k-ink-3（未选中）/ --k-magic-ink（选中）—— 与标签栏文字同色。",
        "// ⚠️ 选中用 magic-ink（主色的文字档）而不是 magic（填充档）：浅色品牌（青柠）的",
        "// $magic = #70C000 压在自己的标签栏底上只有 2.12:1，配方专门求解了 magic-ink；",
        "// 图标若取 magic 就在资源层把那个坑重挖一遍。",
        "//",
        "// paper 那套与主题化之前的平铺版本**逐字节相同**（生成后已用 sha256 复核）——",
        "// 默认主题的图标没有发生任何变化。",
        "//",
        "// 为什么标签栏用 PNG 而不是 SVG：微信 image 组件虽然官方支持 svg，但文档同时列出",
        "// 三条限制（不支持百分比单位、不支持 <style>、mode=scaleToFill 时 WebView 会居中），",
        "// 而抽出的图标只有 viewBox、没有 width/height，尺寸推导属于文档未兜底的行为。",
        "// 标签栏是固定 81×81 的位图场景，PNG 一次性消除这个不确定性。",
        "",
        "import type { UiThemeId } from '../../constants/ui-theme-tokens'",
        "",
    ]

    for theme, _name in themes:
        for key in entries:
            stem = f"{theme}{key.capitalize()}"
            lines.append(f"import {stem}Normal from './png/{theme}/{key}-normal.png'")
            lines.append(f"import {stem}Active from './png/{theme}/{key}-active.png'")
    lines.append("")

    lines.append("/** 标签标识（顺序与 app.config.ts 的 tabBar.list 一致） */")
    lines.append("export type TabKey =")
    lines.extend(f"  | '{key}'" for key in entries)
    lines[-1] += ";"
    lines.append("")

    lines.extend(
        [
            "/** 一个标签的两个状态，各一张已烘焙颜色的 PNG */",
            "export interface TabIconPair {",
            "  normal: string",
            "  active: string",
            "}",
            "",
            "/** 一套主题下的全部标签图标 */",
            "export type TabIconSet = Record<TabKey, TabIconPair>",
            "",
            "/**",
            " * 主题 -> 图标集。",
            " *",
            " * 用 `Record<UiThemeId, …>` 而不是 `Partial<…>`：漏掉一套主题时 `tsc` 当场报错，",
            " * 不会等到运行时才发现某个主题下图标全空白。",
            " */",
            "export const TAB_ICONS: Record<UiThemeId, TabIconSet> = {",
        ]
    )
    for theme, name in themes:
        lines.append(f"  // {name}")
        lines.append(f"  {theme}: {{")
        for key in entries:
            stem = f"{theme}{key.capitalize()}"
            lines.append(f"    // {TAB_LABELS[key]}")
            lines.append(
                f"    {key}: {{ normal: {stem}Normal, active: {stem}Active }},"
            )
        lines.append("  },")
    lines.extend(
        [
            "}",
            "",
            "/**",
            " * 取某套主题的标签图标集。",
            " *",
            " * 兜底到 `paper`：`UiThemeId` 是闭集，类型上到不了兜底分支；但本地镜像",
            " * （`knowsaga.uiTheme`）可能是旧版本写下的脏值，运行时兜一层，好过把",
            " * `undefined` 交给 `<Image src>` 渲染成空白。",
            " */",
            "export function tabIconsOf(theme: UiThemeId): TabIconSet {",
            "  return TAB_ICONS[theme] ?? TAB_ICONS.paper",
            "}",
            "",
        ]
    )

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
    return "\n".join(lines)


def main() -> int:
    if not SOURCE_HTML.is_file():
        print(f"[x] 找不到原型文件: {SOURCE_HTML}", file=sys.stderr)
        return 1

    icons = extract_icons()
    if not icons:
        return 1

    themes = read_themes()

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

    (OUT_DIR / "tab.ts").write_text(render_tab_ts(entries, themes), encoding="utf-8")

    total = len(entries) * 2 * len(themes)
    print(
        f"[ok] 导出 {len(entries)} 个标签图标 × {len(themes)} 套主题"
        f"（{total} 个 PNG 引用）-> {OUT_DIR.name}/tab.ts"
    )
    for theme, name in themes:
        marks = []
        for key in entries:
            for state in ("normal", "active"):
                if not (PNG_OUT_DIR / theme / f"{key}-{state}.png").is_file():
                    marks.append(f"{key}-{state}")
        status = "10/10 ok" if not marks else f"缺 {len(marks)} 张：{', '.join(marks[:4])}"
        print(f"     {theme:<10} {name:<8} {status}")
    print(
        "     svg/ 是默认主题的矢量副本；tab.ts 引用的是 png/<theme>/，"
        "缺失时请先跑 rasterize_tab_icons.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
