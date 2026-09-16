#!/usr/bin/env python
"""从 prototype/*.html 抽取内联 SVG 精灵，生成 Taro 可用的资源模块。

为什么用 base64 data URI 而不是 PNG：
- 10 个精灵合计仅约 16 KB，转 PNG 反而更大且丢失矢量清晰度；
- 小程序 `<view>` 的 `background-image` 支持 data URI，全平台一致；
- 仓库里不出现二进制文件，git diff 可读。

用法（在仓库根目录）：
    python frontend/scripts/extract_sprites.py

产物：
    frontend/src/assets/sprites/index.ts   —— 精灵名 -> data URI
    frontend/src/assets/sprites/svg/*.svg  —— 原始 SVG，便于人工核对
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_DIR = REPO_ROOT / "prototype"
OUT_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "sprites"
SVG_OUT_DIR = OUT_DIR / "svg"

# 原型中的 aria-label -> 语义化英文标识（TS 里用的 key）
LABEL_TO_KEY: dict[str, str] = {
    "小精灵拾拾": "shishi",
    "猫头鹰书灵墨墨": "momo",
    "宝箱怪铜宝": "tongbao",
    "折纸信使鸢鸢": "yuanyuan",
    "学者头像": "scholar",
    "学徒头像": "apprentice",
    "骑士头像": "knight",
    "法师头像": "mage",
    "游侠头像": "ranger",
    "工匠头像": "artisan",
}

# 中文说明，写进 TS 注释方便查阅
KEY_TO_NOTE: dict[str, str] = {
    "shishi": "小精灵拾拾 · 引导 IP，出现 32 次",
    "momo": "猫头鹰书灵墨墨 · 讲解卡",
    "tongbao": "宝箱怪铜宝 · 结算金币",
    "yuanyuan": "折纸信使鸢鸢 · 本期不使用（drift 动效）",
    "scholar": "学者头像 · 身份位",
    "apprentice": "学徒头像 · 公会社交",
    "knight": "骑士头像 · 公会社交",
    "mage": "法师头像 · 公会社交",
    "ranger": "游侠头像 · 公会社交",
    "artisan": "工匠头像 · 冒险者档案",
}

SPRITE_PATTERN = re.compile(
    r'<svg\b[^>]*aria-label="(?P<label>[^"]+)"[^>]*>(?P<body>.*?)</svg>', re.S
)


def normalize_svg(svg: str) -> str:
    """规整 SVG：去掉演示用的固定 width/height 与动画 class，只留 viewBox。

    这样在 Taro 里可以任意缩放，不受原型里的展示尺寸限制。
    """
    svg = re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)
    svg = re.sub(r'\sclass="[^"]*"', "", svg)
    svg = re.sub(r"\s+", " ", svg).strip()
    # 确保有 xmlns，否则 data URI 在小程序里可能不渲染
    if "xmlns=" not in svg:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


def to_data_uri(svg: str) -> str:
    """转成 base64 data URI（base64 比 URL 编码更稳，避免 # 与引号转义问题）。"""
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def collect() -> dict[str, str]:
    """扫描全部原型 HTML，按 aria-label 取出现过的**最长**版本（信息最完整）。"""
    best: dict[str, str] = {}
    for html_file in sorted(PROTOTYPE_DIR.glob("*.html")):
        text = html_file.read_text(encoding="utf-8")
        for m in SPRITE_PATTERN.finditer(text):
            label = m.group("label")
            svg = m.group(0)
            if label not in best or len(svg) > len(best[label]):
                best[label] = svg
    return best


def main() -> int:
    if not PROTOTYPE_DIR.is_dir():
        print(f"[x] 找不到原型目录: {PROTOTYPE_DIR}", file=sys.stderr)
        return 1

    found = collect()
    if not found:
        print("[x] 未在原型中匹配到任何带 aria-label 的 <svg>", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SVG_OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "// ⚠️ 本文件由 frontend/scripts/extract_sprites.py 自动生成，请勿手工修改。",
        "// 重新生成：python frontend/scripts/extract_sprites.py",
        "//",
        "// 精灵源自 prototype/*.html 的内联 SVG，转为 base64 data URI，",
        "// 这样小程序 <view> 的 background-image 可直接使用，且保持矢量清晰。",
        "",
        "/** 精灵标识 */",
        "export type SpriteName =",
    ]

    keys: list[tuple[str, str]] = []  # (key, data_uri)
    unknown: list[str] = []

    for label, raw_svg in sorted(found.items(), key=lambda x: x[0]):
        key = LABEL_TO_KEY.get(label)
        if key is None:
            unknown.append(label)
            continue
        svg = normalize_svg(raw_svg)
        (SVG_OUT_DIR / f"{key}.svg").write_text(svg, encoding="utf-8")
        keys.append((key, to_data_uri(svg)))

    for key, _ in keys:
        lines.append(f"  | '{key}'")
    lines[-1] = lines[-1] + ";"
    lines.append("")
    lines.append("/** 精灵名 -> data URI */")
    lines.append("export const SPRITES: Record<SpriteName, string> = {")
    for key, uri in keys:
        note = KEY_TO_NOTE.get(key, "")
        lines.append(f"  // {note}")
        lines.append(f"  {key}:")
        lines.append(f"    '{uri}',")
    lines.append("};")
    lines.append("")
    lines.append("/** 精灵名 -> 中文说明（无障碍用） */")
    lines.append("export const SPRITE_LABELS: Record<SpriteName, string> = {")
    for key, _ in keys:
        label = next((k for k, v in LABEL_TO_KEY.items() if v == key), key)
        lines.append(f"  {key}: '{label}',")
    lines.append("};")
    lines.append("")
    lines.append("/** 默认导出 */")
    lines.append("export default SPRITES;")
    lines.append("")

    (OUT_DIR / "index.ts").write_text("\n".join(lines), encoding="utf-8")

    total = sum(len(u) for _, u in keys)
    print(f"[ok] 导出 {len(keys)} 个精灵 -> {OUT_DIR.relative_to(REPO_ROOT)}/index.ts")
    for key, uri in keys:
        print(f"     {key:<12} {len(uri):>6} 字节")
    print(f"     合计 {total / 1024:.1f} KB（base64）")
    print(f"[ok] 原始 SVG 副本 -> {SVG_OUT_DIR.relative_to(REPO_ROOT)}/")
    if unknown:
        print(f"[!] 以下 aria-label 未在 LABEL_TO_KEY 中登记，已跳过：{unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
