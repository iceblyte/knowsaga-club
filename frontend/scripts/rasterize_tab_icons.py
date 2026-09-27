#!/usr/bin/env python
"""把 `src/assets/icons/svg/*.svg` 光栅化成 81×81 PNG，**按主题各出一套**，
供 `custom-tab-bar` 使用。

用法：
    python frontend/scripts/rasterize_tab_icons.py

产物：
    frontend/src/assets/icons/png/<theme>/<key>-<normal|active>.png
    5 套主题 × 5 个图标 × 2 个状态 = 50 张（每张约 0.7 KB）

## 颜色从哪里来（不手抄，两处都读真源）

| 主题 | `normal` 用 | `active` 用 | 读自 |
| --- | --- | --- | --- |
| `paper`（默认） | `$ink3` 的兜底字面量 | `$magic-ink` 的兜底字面量 | `src/styles/tokens.scss` |
| 其余 4 套 | `--k-ink-3` | `--k-magic-ink` | `src/styles/_themes.scss`（生成物） |

为什么是这两个令牌：标签栏里**文字与图标必须同色**（原型就是这样），而
`custom-tab-bar/index.scss` 的未选中色是 `$ink3`、选中色是 `$magic-ink`。
注意选中用的是 `magic-ink`（主色的**文字档**）而**不是** `magic`（填充档）——
浅色品牌（青柠）的 `$magic` = #70C000 压在自己的标签栏底上只有 2.12:1，
而配方为浅色品牌专门求解了 `magic-ink`。图标若取 `magic` 就会把那个坑
在资源层重新挖一遍。

读不到令牌时**直接报错**，不退回硬编码色 —— 静默兜底正是这张表要防的事。

## 各主题的图标色与标签栏底（非文本图形，门槛 3:1）

    paper      #9A8870 2.93:1（既有 sub-AA，同原型） / #2F6BD8 4.27:1
    indigo     #6D665E 5.02:1                        / #1E4B8F 7.58:1
    vermilion  #696971 5.04:1                        / #18181B 16.40:1
    midnight   #8F959F 4.63:1                        / #E0A455 6.39:1
    lime       #6D6D6D 4.83:1                        / #497C00 4.70:1

## 为什么必须转 PNG

微信官方 `image` 组件文档（developers.weixin.qq.com/miniprogram/dev/component/image.html）
写明支持 JPG / PNG / SVG / WEBP / GIF，但同时给了三条 SVG 限制：

    1. 使用 svg 格式且 mode=scaleToFill 时，WebView 会居中（除非加 preserveAspectRatio="none"）
    2. svg 格式不支持百分比单位
    3. svg 格式不支持 <style> element

而我们抽取出来的图标 SVG **只有 viewBox、没有 width/height**，在 WebView 渲染内核下
内在尺寸靠 viewBox 推导，属于文档未兜底的路径。标签栏图标是固定 81×81 的位图场景，
直接给像素图可以一次性消掉这个不确定性。

## 为什么自带光栅化器

这份脚本**只用 Python 标准库**（re / zlib / struct / math），不依赖 cairosvg、Pillow、
node 侧的 @resvg/resvg-js。原因是标签栏图标是**一次性产出、随仓库提交**的静态资源，
没必要为此在构建链里再压一个原生依赖；而这个环境里 npm 安装不稳定，
一个离线可跑的脚本反而更可靠。

## 覆盖范围（够用即可，刻意不做通用 SVG 渲染器）

图标集经实测只用到这些能力，脚本也只实现这些：
    · 元素：<path>、<circle>
    · 路径指令：M m L l H h V v C c S s Z z（**没有弧线 A**，有的话本脚本会显式报错而不是静默画错）
    · 描边：全部是 stroke（fill="none"）、stroke-linecap/linejoin 均为 round、stroke-width 固定

把「不支持」变成「报错」而不是「悄悄画错」，是这份脚本唯一的设计原则。
"""

from __future__ import annotations

import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SVG_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "icons" / "svg"
PNG_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "icons" / "png"

# 图标色的两个真源
TOKENS_SCSS = REPO_ROOT / "frontend" / "src" / "styles" / "tokens.scss"
THEMES_SCSS = REPO_ROOT / "frontend" / "src" / "styles" / "_themes.scss"
THEMES_JSON = REPO_ROOT / "shared" / "ui-themes.json"

# 微信标签栏图标的推荐尺寸
OUT_SIZE = 81
# 超采样倍数：先在 4 倍网格上判定覆盖，再盒式降采样得到抗锯齿边缘
SUPERSAMPLE = 4

# 贝塞尔曲线离散化段数。图标里的曲线都很短（最长约 10 个用户单位），
# 24 段在 4 倍网格下的弦高误差远小于半个子像素，肉眼看不出折线。
BEZIER_STEPS = 24

NUMBER_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
TOKEN_RE = re.compile(r"[MmLlHhVvCcSsZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


class UnsupportedSvg(Exception):
    """遇到本脚本没有实现的 SVG 能力时抛出 —— 宁可失败，也不要静默画错。"""


# -----------------------------------------------------------------------------
# 路径解析
# -----------------------------------------------------------------------------
def _cubic_points(p0, p1, p2, p3, steps: int) -> list[tuple[float, float]]:
    """三次贝塞尔离散化（不含起点 p0）。"""
    out: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        a = mt * mt * mt
        b = 3.0 * mt * mt * t
        c = 3.0 * mt * t * t
        d = t * t * t
        out.append(
            (
                a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
            )
        )
    return out


def parse_path(d: str) -> list[list[tuple[float, float]]]:
    """把 path 的 `d` 解析成若干条折线（每条折线是一串点）。

    返回值用于描边：每条折线相邻两点构成一个线段。
    """
    tokens = TOKEN_RE.findall(d)
    if not tokens:
        return []

    subpaths: list[list[tuple[float, float]]] = []
    cur_sub: list[tuple[float, float]] = []

    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_ctrl: tuple[float, float] | None = None
    prev_cmd = ""

    i = 0
    cmd = ""

    def flush() -> None:
        nonlocal cur_sub
        if len(cur_sub) >= 2:
            subpaths.append(cur_sub)
        cur_sub = []

    def numbers(n: int) -> list[float] | None:
        """尝试从当前位置取 n 个数字；取不到则返回 None（用于隐式重复结束）。"""
        nonlocal i
        if i + n > len(tokens):
            return None
        chunk = tokens[i : i + n]
        for t in chunk:
            if not NUMBER_RE.fullmatch(t):
                return None
        i += n
        return [float(t) for t in chunk]

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in ("Z", "z"):
                if cur_sub:
                    cur_sub.append(start)
                    flush()
                cur = start
                prev_ctrl = None
                prev_cmd = cmd
                continue
        else:
            # 隐式重复上一个指令。M 之后的重复是 L，m 之后是 l。
            if prev_cmd in ("M", "m"):
                cmd = "L" if prev_cmd == "M" else "l"
            elif prev_cmd == "":
                raise UnsupportedSvg(f"path 以数字开头，缺少指令: {d!r}")
            else:
                cmd = prev_cmd

        upper = cmd.upper()
        rel = cmd.islower()
        ox, oy = (cur if rel else (0.0, 0.0))

        if upper == "M":
            args = numbers(2)
            if args is None:
                raise UnsupportedSvg(f"M 缺少参数: {d!r}")
            cur = (args[0] + ox, args[1] + oy)
            start = cur
            flush()
            cur_sub = [cur]
            prev_ctrl = None
        elif upper == "L":
            args = numbers(2)
            if args is None:
                raise UnsupportedSvg(f"L 缺少参数: {d!r}")
            cur = (args[0] + ox, args[1] + oy)
            cur_sub.append(cur)
            prev_ctrl = None
        elif upper == "H":
            args = numbers(1)
            if args is None:
                raise UnsupportedSvg(f"H 缺少参数: {d!r}")
            cur = (args[0] + ox, cur[1])
            cur_sub.append(cur)
            prev_ctrl = None
        elif upper == "V":
            args = numbers(1)
            if args is None:
                raise UnsupportedSvg(f"V 缺少参数: {d!r}")
            cur = (cur[0], args[0] + oy)
            cur_sub.append(cur)
            prev_ctrl = None
        elif upper == "C":
            args = numbers(6)
            if args is None:
                raise UnsupportedSvg(f"C 缺少参数: {d!r}")
            c1 = (args[0] + ox, args[1] + oy)
            c2 = (args[2] + ox, args[3] + oy)
            end = (args[4] + ox, args[5] + oy)
            if not cur_sub:
                cur_sub = [cur]
            cur_sub.extend(_cubic_points(cur, c1, c2, end, BEZIER_STEPS))
            cur = end
            prev_ctrl = c2
        elif upper == "S":
            args = numbers(4)
            if args is None:
                raise UnsupportedSvg(f"S 缺少参数: {d!r}")
            # 第一控制点是上一控制点关于当前点的镜像；若上一条不是曲线，则等于当前点
            if prev_ctrl is not None and prev_cmd.upper() in ("C", "S"):
                c1 = (2 * cur[0] - prev_ctrl[0], 2 * cur[1] - prev_ctrl[1])
            else:
                c1 = cur
            c2 = (args[0] + ox, args[1] + oy)
            end = (args[2] + ox, args[3] + oy)
            if not cur_sub:
                cur_sub = [cur]
            cur_sub.extend(_cubic_points(cur, c1, c2, end, BEZIER_STEPS))
            cur = end
            prev_ctrl = c2
        elif upper == "A":
            raise UnsupportedSvg(
                "图标里出现了弧线指令 A —— 本脚本没有实现椭圆弧。"
                "请改用其它图标或补实现后再跑（不会静默跳过）。"
            )
        else:
            raise UnsupportedSvg(f"未支持的路径指令 {cmd!r}: {d!r}")

        prev_cmd = cmd

    flush()
    return subpaths


# -----------------------------------------------------------------------------
# 光栅化
# -----------------------------------------------------------------------------
def _stamp_segment(
    grid: bytearray,
    w: int,
    h: int,
    a: tuple[float, float],
    b: tuple[float, float],
    radius: float,
) -> None:
    """把「一条带圆头圆角的粗线段」盖进二值网格（1 = 命中）。

    判定方式用「点到线段的距离 ≤ 半径」—— 它天然等价于 round linecap + round linejoin，
    也正是这组图标的描边设置，所以不需要额外处理端点与拐角。
    """
    minx = math.floor(min(a[0], b[0]) - radius)
    maxx = math.ceil(max(a[0], b[0]) + radius)
    miny = math.floor(min(a[1], b[1]) - radius)
    maxy = math.ceil(max(a[1], b[1]) + radius)

    minx = max(0, minx)
    miny = max(0, miny)
    maxx = min(w - 1, maxx)
    maxy = min(h - 1, maxy)

    ax, ay = a
    dx = b[0] - ax
    dy = b[1] - ay
    len_sq = dx * dx + dy * dy
    r_sq = radius * radius

    for py in range(miny, maxy + 1):
        cy = py + 0.5
        row = py * w
        for px in range(minx, maxx + 1):
            cx = px + 0.5
            if len_sq <= 1e-12:
                d_sq = (cx - ax) ** 2 + (cy - ay) ** 2
            else:
                t = ((cx - ax) * dx + (cy - ay) * dy) / len_sq
                if t <= 0.0:
                    d_sq = (cx - ax) ** 2 + (cy - ay) ** 2
                elif t >= 1.0:
                    d_sq = (cx - b[0]) ** 2 + (cy - b[1]) ** 2
                else:
                    qx = ax + t * dx
                    qy = ay + t * dy
                    d_sq = (cx - qx) ** 2 + (cy - qy) ** 2
            if d_sq <= r_sq:
                grid[row + px] = 1


def _stamp_ring(
    grid: bytearray,
    w: int,
    h: int,
    cx: float,
    cy: float,
    r: float,
    radius: float,
) -> None:
    """把「一个描边圆」盖进网格（环带：r±radius）。"""
    inner = max(0.0, r - radius)
    outer = r + radius
    minx = max(0, math.floor(cx - outer))
    maxx = min(w - 1, math.ceil(cx + outer))
    miny = max(0, math.floor(cy - outer))
    maxy = min(h - 1, math.ceil(cy + outer))
    inner_sq = inner * inner
    outer_sq = outer * outer
    for py in range(miny, maxy + 1):
        dy = py + 0.5 - cy
        row = py * w
        for px in range(minx, maxx + 1):
            dx = px + 0.5 - cx
            d_sq = dx * dx + dy * dy
            if inner_sq <= d_sq <= outer_sq:
                grid[row + px] = 1


def render_svg(svg_text: str, out_size: int, supersample: int) -> list[bytes]:
    """渲染成 PNG 的 RGBA 扫描行（不含每行的 filter byte）。"""
    vb = re.search(r'viewBox="([^"]+)"', svg_text)
    if not vb:
        raise UnsupportedSvg("缺少 viewBox，无法确定用户坐标系")
    nums = [float(n) for n in NUMBER_RE.findall(vb.group(1))]
    if len(nums) != 4:
        raise UnsupportedSvg(f"viewBox 不是 4 个数: {vb.group(1)!r}")
    vx, vy, vw, vh = nums
    if vw <= 0 or vh <= 0:
        raise UnsupportedSvg("viewBox 宽高必须为正")

    scale = out_size / vw
    work = out_size * supersample

    grid = bytearray(work * work)

    # 收集描边颜色（这组图标整份文件只有一个颜色）
    colors: set[str] = set()

    for m in re.finditer(r"<circle\b([^>]*)>", svg_text):
        attrs = _attrs(m.group(1))
        if (attrs.get("fill") or "none") != "none":
            raise UnsupportedSvg("只实现了描边图形；<circle> 的 fill 不是 none")
        stroke = attrs.get("stroke", "")
        colors.add(stroke)
        radius = _num(attrs, "stroke-width", 1.0) / 2.0
        _stamp_ring(
            grid,
            work,
            work,
            (_num(attrs, "cx") - vx) * scale * supersample,
            (_num(attrs, "cy") - vy) * scale * supersample,
            _num(attrs, "r") * scale * supersample,
            radius * scale * supersample,
        )

    for m in re.finditer(r"<path\b([^>]*)>", svg_text):
        attrs = _attrs(m.group(1))
        if (attrs.get("fill") or "none") != "none":
            raise UnsupportedSvg("只实现了描边路径；<path> 的 fill 不是 none")
        colors.add(attrs.get("stroke", ""))
        radius = _num(attrs, "stroke-width", 1.0) / 2.0
        radius_px = radius * scale * supersample
        for sub in parse_path(attrs.get("d", "")):
            pts = [
                ((x - vx) * scale * supersample, (y - vy) * scale * supersample)
                for x, y in sub
            ]
            for i in range(len(pts) - 1):
                _stamp_segment(grid, work, work, pts[i], pts[i + 1], radius_px)

    if not colors:
        raise UnsupportedSvg("没有找到任何带描边的 path/circle")
    if len(colors) > 1:
        raise UnsupportedSvg(f"图标内出现多种描边色 {sorted(colors)}，本脚本只支持单色")
    r, g, b = _parse_color(next(iter(colors)))

    # 盒式降采样：4×4 子像素的平均覆盖度 → alpha
    rows: list[bytes] = []
    ss = supersample
    inv = 1.0 / (ss * ss)
    for oy in range(out_size):
        buf = bytearray()
        base_y = oy * ss
        for ox in range(out_size):
            base_x = ox * ss
            hits = 0
            for yy in range(base_y, base_y + ss):
                row = yy * work
                for xx in range(base_x, base_x + ss):
                    hits += grid[row + xx]
            alpha = int(round(hits * inv * 255))
            buf += bytes((r, g, b, alpha))
        rows.append(bytes(buf))
    return rows


def _attrs(s: str) -> dict[str, str]:
    return {k: v for k, v in re.findall(r'([a-zA-Z-]+)="([^"]*)"', s)}


def _num(attrs: dict[str, str], key: str, default: float | None = None) -> float:
    if key not in attrs:
        if default is None:
            raise UnsupportedSvg(f"缺少必需属性 {key}")
        return default
    return float(attrs[key])


def _parse_color(spec: str) -> tuple[int, int, int]:
    """只支持 #RRGGBB / #RGB（这组图标的颜色由抽取脚本烘焙，一定是十六进制）。"""
    s = spec.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or not all(c in "0123456789abcdefABCDEF" for c in s):
        raise UnsupportedSvg(f"只支持十六进制颜色，收到 {spec!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


# -----------------------------------------------------------------------------
# 主题图标色（读真源，不手抄）
# -----------------------------------------------------------------------------
# `$ink3: var(--k-ink-3, #9a8870); // 更淡墨` —— 只取有兜底字面量的那种写法，
# 别名（`$x: $y;`）与函数值（`$grain: url(…)`）都拿不到，正好不该拿。
VAR_FALLBACK_RE = re.compile(
    r"^\$([a-z0-9-]+)\s*:\s*var\(\s*--k-[a-z0-9-]+\s*,\s*(#[0-9a-fA-F]{6})\s*\)",
    re.M,
)
THEME_BLOCK_RE = re.compile(r"\.ui-theme--([a-z0-9-]+)\s*\{(.*?)\}", re.S)
VAR_DECL_RE = re.compile(r"--k-([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})")


def read_default_tokens(path: Path = TOKENS_SCSS) -> dict[str, str]:
    """tokens.scss 里 `$name: var(--k-x, #hex);` 的兜底字面量 = 默认主题的真值。"""
    if not path.is_file():
        raise UnsupportedSvg(f"找不到 {path}")
    return {m.group(1): m.group(2) for m in VAR_FALLBACK_RE.finditer(path.read_text(encoding="utf-8"))}


def read_theme_blocks(path: Path = THEMES_SCSS) -> dict[str, dict[str, str]]:
    """`_themes.scss` 里每个 `.ui-theme--<id>` 块的 `--k-*: #hex`。"""
    if not path.is_file():
        raise UnsupportedSvg(f"找不到 {path}（先生成：npm run gen:theme）")
    return {
        m.group(1): {k: v for k, v in VAR_DECL_RE.findall(m.group(2))}
        for m in THEME_BLOCK_RE.finditer(path.read_text(encoding="utf-8"))
    }


def read_theme_ids(path: Path = THEMES_JSON) -> list[str]:
    """`shared/ui-themes.json` 里的主题 id（顺序即设置页展示顺序，paper 之外的那 4 套）。"""
    if not path.is_file():
        raise UnsupportedSvg(f"找不到主题真源 {path}")
    ids = [t["id"] for t in json.loads(path.read_text(encoding="utf-8"))["themes"]]
    if not ids:
        raise UnsupportedSvg(f"{path} 里 themes 为空")
    return ids


def icon_colors() -> list[tuple[str, str, str]]:
    """`[(theme_id, normal_hex, active_hex), …]`，`paper` 在最前（与 UI_THEME_IDS 同序）。

    顺序不是随便定的：`assets/icons/tab.ts` 按这个顺序生成，而设置页也按
    `UI_THEME_IDS` 的顺序展示 —— 两边都从「paper + JSON」推出来才不会错位。
    """
    tokens = read_default_tokens()
    for name in ("ink3", "magic-ink"):
        if name not in tokens:
            raise UnsupportedSvg(
                f"{TOKENS_SCSS} 里没找到 ${name} 的 var() 兜底字面量 —— "
                "默认主题的图标色必须从 tokens.scss 读出来，不能在这里写死。"
            )

    out: list[tuple[str, str, str]] = [("paper", tokens["ink3"], tokens["magic-ink"])]
    blocks = read_theme_blocks()
    for theme_id in read_theme_ids():
        block = blocks.get(theme_id)
        if block is None:
            raise UnsupportedSvg(f"{THEMES_SCSS} 里没有 .ui-theme--{theme_id} 块（先跑 npm run gen:theme）")
        missing = [name for name in ("ink-3", "magic-ink") if name not in block]
        if missing:
            raise UnsupportedSvg(f"主题 {theme_id} 缺少令牌 {missing}，图标取不到颜色")
        out.append((theme_id, block["ink-3"], block["magic-ink"]))
    return out


def recolor_svg(svg_text: str, color: str) -> str:
    """把图标里烘焙的描边色换成目标色。

    `svg/*.svg` 是**默认主题**的矢量副本（整个人工核对也看它），所以每生成
    一套主题就要换一次色。只替换十六进制字面量 —— `fill="none"` /
    `stroke="none"` 这类关键字动不到，`render_svg` 的单色断言仍然成立。
    """
    changed = 0
    for attr in ("stroke", "fill"):
        svg_text, n = re.subn(rf'{attr}="#[0-9a-fA-F]{{6}}"', f'{attr}="{color}"', svg_text)
        changed += n
    if changed == 0:
        raise UnsupportedSvg("SVG 里没有任何十六进制颜色可替换 —— 颜色约定变了？")
    return svg_text


# -----------------------------------------------------------------------------
# PNG 编码（真彩 + Alpha，8 位）
# -----------------------------------------------------------------------------
def encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 = None
        raw += row
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def main() -> int:
    svgs = sorted(SVG_DIR.glob("*.svg"))
    if not svgs:
        print(f"[x] 没找到源 SVG：{SVG_DIR}")
        return 1

    # 先做完全部校验再动盘 —— 半途失败会留下「一半主题是新色、一半是旧色」的
    # 产物，那比直接失败难查得多。
    plan: list[tuple[Path, str]] = []
    for svg_path in svgs:
        if svg_path.stem.endswith("-active"):
            state = "active"
        elif svg_path.stem.endswith("-normal"):
            state = "normal"
        else:
            print(f"[x] 无法判定状态（文件名既不以 -normal 也不以 -active 结尾）：{svg_path.name}", file=sys.stderr)
            return 1
        plan.append((svg_path, state))

    try:
        colors = icon_colors()
    except UnsupportedSvg as exc:
        print(f"[x] {exc}", file=sys.stderr)
        return 1

    PNG_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    total_bytes = 0
    for theme_id, normal_hex, active_hex in colors:
        out_dir = PNG_DIR / theme_id
        out_dir.mkdir(parents=True, exist_ok=True)
        theme_bytes = 0
        for svg_path, state in plan:
            color = active_hex if state == "active" else normal_hex
            svg_text = recolor_svg(svg_path.read_text(encoding="utf-8"), color)
            rows = render_svg(svg_text, OUT_SIZE, SUPERSAMPLE)
            png = encode_png(OUT_SIZE, OUT_SIZE, rows)
            (out_dir / f"{svg_path.stem}.png").write_bytes(png)
            theme_bytes += len(png)
            written += 1
        total_bytes += theme_bytes
        print(
            f"[ok] {theme_id:<10} normal={normal_hex} active={active_hex}"
            f"  {len(plan)} 个 PNG / {theme_bytes} B -> {out_dir.relative_to(REPO_ROOT)}"
        )

    # 清掉旧的「平铺」布局（png/*.png）——主题化之前只有这一层，
    # 留着会让人以为还有一份没主题的图标在用。
    stale = sorted(p for p in PNG_DIR.glob("*.png") if p.is_file())
    for path in stale:
        path.unlink()
        print(f"[--] 删除旧布局残留 {path.relative_to(REPO_ROOT)}")

    print(
        f"\n共生成 {written} 个 PNG（{OUT_SIZE}×{OUT_SIZE}，{total_bytes} B）"
        f"：{len(colors)} 套主题 × {len(plan)} 个状态文件"
    )
    print(f"目录：{PNG_DIR.relative_to(REPO_ROOT)}/<theme>/")
    print("接着跑 `node frontend/scripts/check_icon_parity.mjs` 核对产物色值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
