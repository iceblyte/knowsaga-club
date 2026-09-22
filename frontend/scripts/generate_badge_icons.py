"""生成 18 枚勋章的 SVG 图案，并写出 `src/assets/badges/index.ts`。

## 为什么要有这个脚本

勋章原来在界面上是一个**汉字**放在圆底里（`BadgeSpec.icon`，如「启」「连」「百」）。
那是设计系统早期的临时做法：圆底 + 单字读起来像标签，不像一枚值得收集的徽章。
本次改成真正的图案（缎带 + 圆盘 + 徽记），18 枚各自不同。

## 为什么是「生成」而不是手写 18 个文件

图案的骨架完全一致，只有三样东西在变：**配色**（金 / 稀紫 / 未解锁灰）、
**徽记**（圆心那个符号）、以及标题文字。把骨架写一遍、徽记写成 18 个小片段，
比手抄 18 份 SVG 更不容易出现「某两枚的描边粗细不一样」这种瑕疵。
`prototype/` 里没有勋章图案可抄，所以这里是一份**新增的视觉资产**。

## 为什么落成 base64 的 data URI

小程序没有 `<svg>` 组件（`pages/profile/knowledge-tree` 的文件头写过这件事），
项目里渲染矢量图形一律走 data URI —— 精灵（`scripts/extract_sprites.py`）与
装饰（`scripts/extract_decorations.py`）都是这么做的。这里沿用同一条路：
`<Image src={dataUri}>`，H5 与微信两端都能画。

两条小程序端 `image` 对 SVG 的限制在这个脚本里被**主动避开**：
① 不用百分比单位（`width`/`height` 写死 64）；② 不用 `<style>`（全部写成
表现属性）。所以这里没有 `<style>` 块，也没有 `%`。

## 用法

    python frontend/scripts/generate_badge_icons.py

产物 `src/assets/badges/index.ts` 由脚本覆盖，**不要手工改**。
"""

from __future__ import annotations

import base64
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "src" / "assets" / "badges" / "index.ts"

# -----------------------------------------------------------------------------
# 调色板：与设计系统 tokens.scss 的三档勋章语义对齐（金 / 稀紫 / 未解锁）
# -----------------------------------------------------------------------------
#: (底色, 高光, 描边与缎带, 徽记)
PALETTES: dict[str, tuple[str, str, str, str]] = {
    "gold": ("#E7B44A", "#F7DC93", "#A9772A", "#6E4A12"),
    "rare": ("#9B7BE0", "#C7B3F6", "#6647A8", "#3F2478"),
    # 未解锁：整体降饱和，徽记与底色接近 —— 远看是一枚「还没点亮」的牌
    "off": ("#CFC4B2", "#E5DDCF", "#9A8870", "#8D7C66"),
}

# -----------------------------------------------------------------------------
# 徽记：圆心 (32, 36)、半径约 11 的小符号。每个函数返回一段 SVG 片段。
# -----------------------------------------------------------------------------
CX, CY = 32.0, 36.0


def _star(points: int = 5, outer: float = 11.0, inner: float = 4.6) -> str:
    """正多角星。用极坐标算，避免手抄一串小数。"""
    coords: list[str] = []
    for i in range(points * 2):
        radius = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / points
        coords.append(f"{CX + radius * math.cos(angle):.2f} {CY + radius * math.sin(angle):.2f}")
    return f'<path d="M{" L".join(coords)}Z" fill="{{ink}}"/>'


def _rays(count: int, inner: float, outer: float, width: float) -> str:
    """从圆心向外的一圈短棒（太阳 / 光芒）。用 rotate 绕圆心转，不手算坐标。"""
    parts: list[str] = []
    for i in range(count):
        angle = i * (360.0 / count)
        parts.append(
            f'<rect x="{CX - width / 2:.2f}" y="{CY - outer:.2f}" width="{width:.2f}" '
            f'height="{outer - inner:.2f}" rx="{width / 2:.2f}" fill="{{ink}}" '
            f'transform="rotate({angle:.1f} {CX} {CY})"/>'
        )
    return "".join(parts)


MOTIFS: dict[str, str] = {
    # 初次启程 —— 一道向上的箭形
    "chevron": '<path d="M23 28 32 36.5 41 28l3.2 3.2L32 43.4 20.8 31.2Z" fill="{ink}"/>',
    # 五连答对 —— 三根递升的柱
    "bars": (
        '<rect x="23.5" y="32" width="4.4" height="11" rx="2" fill="{ink}"/>'
        '<rect x="29.8" y="26" width="4.4" height="17" rx="2" fill="{ink}"/>'
        '<rect x="36.1" y="29.5" width="4.4" height="13.5" rx="2" fill="{ink}"/>'
    ),
    # 百题达成 —— 四宫格
    "grid": (
        '<rect x="24" y="28" width="7" height="7" rx="2" fill="{ink}"/>'
        '<rect x="33" y="28" width="7" height="7" rx="2" fill="{ink}"/>'
        '<rect x="24" y="37" width="7" height="7" rx="2" fill="{ink}"/>'
        '<rect x="33" y="37" width="7" height="7" rx="2" fill="{ink}"/>'
    ),
    # 满分通关 —— 星
    "star": _star(),
    # 七日不辍 —— 环
    "ring": (
        f'<circle cx="{CX}" cy="{CY}" r="7.6" fill="none" stroke="{{ink}}" stroke-width="3.6"/>'
    ),
    # 深夜求知 —— 月牙
    "moon": (
        f'<path d="M37.6 25.4a11.4 11.4 0 1 0 0 21.2 13.6 13.6 0 0 1 0-21.2Z" fill="{{ink}}"/>'
    ),
    # 卷轴百卷 —— 卷轴
    "scroll": (
        '<rect x="25" y="27.5" width="14" height="17" rx="2.4" fill="none" '
        'stroke="{ink}" stroke-width="2.4"/>'
        '<rect x="28.6" y="32" width="6.8" height="2.4" rx="1.2" fill="{ink}"/>'
        '<rect x="28.6" y="37" width="6.8" height="2.4" rx="1.2" fill="{ink}"/>'
    ),
    # 神秘成就 —— 菱形宝石
    "diamond": '<path d="M32 25 41 36 32 47 23 36Z" fill="{ink}"/>',
    # 卷轴收藏家 —— 三本叠放
    "stack": (
        '<rect x="23" y="27" width="18" height="4.4" rx="2.2" fill="{ink}"/>'
        '<rect x="23" y="33.8" width="18" height="4.4" rx="2.2" fill="{ink}"/>'
        '<rect x="23" y="40.6" width="18" height="4.4" rx="2.2" fill="{ink}"/>'
    ),
    # 多选高手 —— 双勾
    "checks": (
        '<path d="M22 33.5l4.6 4.6 8-9" fill="none" stroke="{ink}" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M28 39.5l4.6 4.6 9.4-11" fill="none" stroke="{ink}" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 判断达人 —— 天平
    "scale": (
        '<path d="M32 25.5v21" fill="none" stroke="{ink}" stroke-width="2.6" '
        'stroke-linecap="round"/>'
        '<path d="M22.5 29.5h19" fill="none" stroke="{ink}" stroke-width="2.6" '
        'stroke-linecap="round"/>'
        '<circle cx="22.5" cy="36.5" r="5" fill="none" stroke="{ink}" stroke-width="2.6"/>'
        '<circle cx="41.5" cy="36.5" r="5" fill="none" stroke="{ink}" stroke-width="2.6"/>'
    ),
    # 错题终结者 —— 闪电
    "bolt": '<path d="M34.6 23.5 23.4 39.5h6.4l-2.4 9.5 11.8-16.6h-6.6Z" fill="{ink}"/>',
    # 初见森林 —— 一棵树
    "tree": (
        '<path d="M32 24.5 39 34.5h-4.4l5.4 8.5H24l5.4-8.5H25Z" fill="{ink}"/>'
        '<rect x="30.2" y="42.5" width="3.6" height="4.5" rx="1.4" fill="{ink}"/>'
    ),
    # 知识树满枝 —— 三棵树
    "forest": (
        '<path d="M24.5 31 30 39.5h-11Z" fill="{ink}"/>'
        '<path d="M32 25 40 39.5H24Z" fill="{ink}"/>'
        '<path d="M39.5 31 45 39.5H34Z" fill="{ink}"/>'
        '<rect x="22.5" y="41" width="19" height="3.6" rx="1.8" fill="{ink}"/>'
    ),
    # 一日千里 —— 太阳
    "sun": (
        f'<circle cx="{CX}" cy="{CY}" r="6" fill="{{ink}}"/>' + _rays(8, 8.2, 12.4, 2.6)
    ),
    # 月余不辍 —— 日历
    "calendar": (
        '<rect x="23" y="28.5" width="18" height="16" rx="3" fill="none" stroke="{ink}" '
        'stroke-width="2.4"/>'
        '<path d="M23 34.5h18" fill="none" stroke="{ink}" stroke-width="2.4"/>'
        '<rect x="26.6" y="25" width="2.6" height="5" rx="1.3" fill="{ink}"/>'
        '<rect x="34.8" y="25" width="2.6" height="5" rx="1.3" fill="{ink}"/>'
        '<rect x="27.4" y="38" width="3.4" height="3.4" rx="1.2" fill="{ink}"/>'
        '<rect x="33.2" y="38" width="3.4" height="3.4" rx="1.2" fill="{ink}"/>'
    ),
    # 闪电通卷 —— 星与光（用星 + 光芒区分于普通闪电）
    "flash": _star(outer=9.6, inner=4.2) + _rays(6, 11.4, 14.6, 2.4),
    # 早起冒险者 —— 日出
    "sunrise": (
        f'<path d="M25.5 40a6.5 6.5 0 0 1 13 0Z" fill="{{ink}}"/>'
        '<rect x="20.5" y="41.6" width="23" height="3" rx="1.5" fill="{ink}"/>'
        '<rect x="30.7" y="24.5" width="2.6" height="5.4" rx="1.3" fill="{ink}"/>'
        '<rect x="22.4" y="28.6" width="2.6" height="5.4" rx="1.3" fill="{ink}" '
        'transform="rotate(-45 23.7 31.3)"/>'
        '<rect x="38.6" y="28.6" width="2.6" height="5.4" rx="1.3" fill="{ink}" '
        'transform="rotate(45 39.9 31.3)"/>'
    ),
}

#: 勋章 key → 徽记。key 与后端 `badge_service.BADGES` 的注册表一一对应。
BADGE_MOTIFS: dict[str, str] = {
    "first_quest": "chevron",
    "five_in_a_row": "bars",
    "hundred_questions": "grid",
    "perfect_clear": "star",
    "seven_day_streak": "ring",
    "midnight_learner": "moon",
    "hundred_scrolls": "scroll",
    "secret_achievement": "diamond",
    "scroll_collector": "stack",
    "multiple_master": "checks",
    "judge_master": "scale",
    "wrong_question_slayer": "bolt",
    "first_forest": "tree",
    "full_knowledge_tree": "forest",
    "fifty_a_day": "sun",
    "thirty_day_streak": "calendar",
    "lightning_clear": "flash",
    "early_riser": "sunrise",
}


def render(motif: str, palette: tuple[str, str, str, str]) -> str:
    base, light, dark, ink = palette
    body = MOTIFS[motif].format(ink=ink)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        # 缎带：两条斜向下收的带子，画在圆盘之下
        f'<path d="M19 4 29.5 19.5 24.5 25 14 9.5Z" fill="{dark}"/>'
        f'<path d="M45 4 34.5 19.5 39.5 25 50 9.5Z" fill="{dark}"/>'
        # 圆盘：外圈描边 + 内圈提亮，形成一点金属层次
        f'<circle cx="32" cy="36" r="22" fill="{base}"/>'
        f'<circle cx="32" cy="36" r="22" fill="none" stroke="{dark}" stroke-width="3"/>'
        f'<circle cx="32" cy="36" r="16.6" fill="{light}"/>'
        f'<circle cx="32" cy="36" r="16.6" fill="none" stroke="{base}" stroke-width="1.6"/>'
        # 左上角高光弧
        f'<path d="M19.5 27.5a17 17 0 0 1 9.5-7.5" fill="none" stroke="#FFFFFF" '
        f'stroke-width="2.4" stroke-linecap="round" opacity="0.55"/>'
        f"{body}"
        "</svg>"
    )


def data_uri(svg: str) -> str:
    """base64 编码 —— 与 `extract_sprites.py` 同一口径。"""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


HEADER = """// ⚠️ 本文件由 frontend/scripts/generate_badge_icons.py 自动生成，请勿手工修改。
//
// 18 枚勋章的图案（缎带 + 圆盘 + 徽记），三档配色与后端 `BadgeSpec.tier` 对应：
//   gold   金   —— 普通成就
//   rare   稀紫 —— 稀有成就
//   off    灰   —— 未解锁（后端不下发 `off`，是前端按 `unlocked` 选的档）
//
// key 与后端 `backend/app/services/badge_service.py` 的 `BADGES` 注册表一一对应。
// 后端**新增**勋章时这里不会有对应图案 —— 调用方（`components/BadgeIcon`）
// 会退回显示后端的单字 `icon`，不会出现一个空白的圆。
//
// 为什么是 base64 的 data URI：小程序没有 <svg> 组件，项目里渲染矢量图形
// 一律走 data URI（同 `assets/sprites`、`assets/decorations`）。
// 重新生成：python frontend/scripts/generate_badge_icons.py

/** 图案档位 */
export type BadgeArtTier = 'gold' | 'rare' | 'off';

/** 勋章 key -> { 档位: data URI } */
export const BADGE_ART: Record<string, Record<BadgeArtTier, string>> = {
"""


def main() -> None:
    tiers: tuple[BadgeArtTier, ...] = ("gold", "rare", "off")
    lines: list[str] = [HEADER]
    for key, motif in BADGE_MOTIFS.items():
        lines.append(f"  {key}: {{\n")
        for tier in tiers:
            uri = data_uri(render(motif, PALETTES[tier]))
            lines.append(f"    {tier}:\n      '{uri}',\n")
        lines.append("  },\n")
    lines.append("};\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(BADGE_MOTIFS)} badges)")


if __name__ == "__main__":
    main()
