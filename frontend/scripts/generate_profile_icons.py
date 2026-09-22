"""生成「我的档案」入口行的 6 个线条图标，并写出 `src/assets/profile-icons/index.ts`。

## 为什么要换掉原来的单字

入口行左侧原本是一个 28px 的方块，里面放一个汉字（树 / 题 / 账 / 印 / 卡 / 设）。
那是最早期照抄设计系统 `.ico` 占位的做法，单字读起来像标签而不是图标 ——
本次换成描边线条图标，方块的底色与尺寸都不动（只换里面那一个孩子）。

## 为什么是 data URI（同 `generate_badge_icons.py`）

小程序没有 `<svg>` 组件，项目里渲染矢量图形一律走 data URI。
两条小程序端限制在这里同样被避开：写死 `width`/`height`（不用百分比）、
不用 `<style>`（全部写成表现属性）。

## 用法

    python frontend/scripts/generate_profile_icons.py

产物 `src/assets/profile-icons/index.ts` 由脚本覆盖，**不要手工改**。
"""

from __future__ import annotations

import base64
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "src" / "assets" / "profile-icons" / "index.ts"

#: 线条颜色 = tokens 的 `$ink2`（#6b5a45，淡墨）。画在 `$paper2` 方块上对比清晰。
INK = "#6B5A45"
WIDTH = "1.8"

#: 图标名 -> 路径片段（20×20 视图框，纯描边）
ICONS: dict[str, str] = {
    # 知识树（04·4）
    "knowledgeTree": (
        '<path d="M10 3.2 15.6 10h-3.4l4 4.8H3.8l4-4.8H4.4Z"/>'
        '<path d="M10 14.8v3"/>'
    ),
    # 错题本（04·7）—— 一页带叉的纸
    "review": (
        '<path d="M4.8 2.9h6.6l3.8 3.8V17H4.8Z"/>'
        '<path d="M11.2 2.9v3.9h3.9"/>'
        '<path d="M7.8 10.4l4.4 4.4M12.2 10.4l-4.4 4.4"/>'
    ),
    # 历史卷轴（04·5）—— 一本账
    "scrolls": (
        '<path d="M4.8 5.2h10.4v11.6H4.8Z"/>'
        '<path d="M7.6 3.2v3.2M12.4 3.2v3.2"/>'
        '<path d="M7.4 9h5.2M7.4 11.6h5.2M7.4 14.2h3.2"/>'
    ),
    # 勋章墙（04·9）—— 一枚挂着的勋章
    "badges": (
        '<circle cx="10" cy="8" r="4.1"/>'
        '<path d="M7.3 11.4 5.9 17.4l4.1-2.1 4.1 2.1-1.4-6"/>'
    ),
    # 公会卡（04·2）—— 一张卡
    "card": (
        '<path d="M3.4 5.4h13.2v9.2H3.4Z"/>'
        '<path d="M3.4 8.8h13.2"/>'
        '<path d="M6.4 12h3.2"/>'
    ),
    # 设置（07·5）—— 两条带滑块的轨道
    "settings": (
        '<path d="M3.8 6.6h12.4M3.8 13.4h12.4"/>'
        '<circle cx="7.8" cy="6.6" r="1.9"/>'
        '<circle cx="12.6" cy="13.4" r="1.9"/>'
    ),
}


def render(body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">'
        f'<g fill="none" stroke="{INK}" stroke-width="{WIDTH}" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</g>'
        "</svg>"
    )


def data_uri(svg: str) -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


HEADER = """// ⚠️ 本文件由 frontend/scripts/generate_profile_icons.py 自动生成，请勿手工修改。
//
// 「我的档案」（04·1）入口行的 6 个线条图标。原来那 6 个 28px 方块里放的是
// 单个汉字（树 / 题 / 账 / 印 / 卡 / 设）—— 换成描边图标后方块的底色与尺寸不变。
//
// 线条色 = tokens 的 `$ink2`（#6b5a45），画在 `$paper2` 方块上。
// 为什么是 base64 的 data URI：小程序没有 <svg> 组件，项目里渲染矢量图形
// 一律走 data URI（同 `assets/sprites`、`assets/badges`）。
// 重新生成：python frontend/scripts/generate_profile_icons.py

/** 入口行图标名 */
export type ProfileIconName =
  | 'knowledgeTree'
  | 'review'
  | 'scrolls'
  | 'badges'
  | 'card'
  | 'settings';

/** 图标名 -> data URI */
export const PROFILE_ICONS: Record<ProfileIconName, string> = {
"""


def main() -> None:
    lines: list[str] = [HEADER]
    for name, body in ICONS.items():
        lines.append(f"  {name}:\n    '{data_uri(render(body))}',\n")
    lines.append("};\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(ICONS)} icons)")


if __name__ == "__main__":
    main()
