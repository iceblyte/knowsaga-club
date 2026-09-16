#!/usr/bin/env python
"""抽取原型里的「装饰图形」（无 aria-label 的 SVG）。

与精灵的区别：精灵是角色形象（有 aria-label），装饰是法阵、纸纹这类
纯几何图形（无 aria-label），按 viewBox 与动画类名识别。

产物：
    frontend/src/assets/decorations/index.ts
    frontend/src/assets/decorations/svg/*.svg

注意：进度环（正确率圆环）**不在**这里 —— 它需要按实际数值绘制并做
生长动画，静态 SVG 表达不了，改用 Canvas 2D（见 src/components/RingProgress/）。

用法（在仓库根目录）：
    python frontend/scripts/extract_decorations.py
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_DIR = REPO_ROOT / "prototype"
OUT_DIR = REPO_ROOT / "frontend" / "src" / "assets" / "decorations"
SVG_OUT_DIR = OUT_DIR / "svg"

# 装饰标识 -> (识别条件, 说明)
#   识别条件用 (viewBox, 必须包含的类名, 必须包含的属性片段) 描述
DECORATIONS: dict[str, dict[str, object]] = {
    "magicCircle": {
        "viewBox": "0 0 120 120",
        "class": "spin",
        "note": "法阵 · 启动页与生成中页的旋转背景（原型 3 处引用）",
    },
}

SVG_PATTERN = re.compile(r"<svg\b[^>]*viewBox=\"(?P<vb>[^\"]+)\"[^>]*>.*?</svg>", re.S)


def normalize(svg: str) -> str:
    """去掉演示用的固定 width/height 与动画 class，只保留 viewBox 与几何。"""
    svg = re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)
    svg = re.sub(r'\sclass="[^"]*"', "", svg)
    svg = re.sub(r"\sstyle=\"[^\"]*\"", "", svg)
    svg = re.sub(r"\s+", " ", svg).strip()
    if "xmlns=" not in svg:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


def to_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def main() -> int:
    if not PROTOTYPE_DIR.is_dir():
        print(f"[x] 找不到原型目录: {PROTOTYPE_DIR}", file=sys.stderr)
        return 1

    # 收集所有原型里的 SVG 候选（保留最长版本）
    candidates: list[str] = []
    for html in sorted(PROTOTYPE_DIR.glob("*.html")):
        candidates.extend(SVG_PATTERN.findall(html.read_text(encoding="utf-8")))
        candidates.extend(
            m.group(0) for m in SVG_PATTERN.finditer(html.read_text(encoding="utf-8"))
        )

    # 去重
    seen: set[str] = set()
    unique: list[str] = []
    for s in candidates:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SVG_OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "// ⚠️ 本文件由 frontend/scripts/extract_decorations.py 自动生成，请勿手工修改。",
        "// 重新生成：python frontend/scripts/extract_decorations.py",
        "//",
        "// 装饰图形（法阵等）源自 prototype/*.html 的无 aria-label 内联 SVG，",
        "// 转成 base64 data URI 供小程序 <image> 使用。",
        "",
        "/** 装饰标识 */",
        "export type DecorationName =",
    ]

    found: list[tuple[str, str]] = []
    for name, rule in DECORATIONS.items():
        vb = rule["viewBox"]
        cls = rule["class"]
        match = None
        for svg in unique:
            if f'viewBox="{vb}"' not in svg:
                continue
            if cls and f'class="{cls}"' not in svg:
                continue
            if match is None or len(svg) > len(match):
                match = svg
        if match is None:
            print(f"[!] 未匹配到装饰图形 {name}（viewBox={vb}, class={cls}）", file=sys.stderr)
            continue
        normalized = normalize(match)
        (SVG_OUT_DIR / f"{name}.svg").write_text(normalized, encoding="utf-8")
        found.append((name, to_data_uri(normalized)))

    if not found:
        print("[x] 没有抽取到任何装饰图形", file=sys.stderr)
        return 1

    for name, _ in found:
        lines.append(f"  | '{name}'")
    lines[-1] += ";"
    lines.append("")
    lines.append("/** 装饰名 -> data URI */")
    lines.append("export const DECORATIONS: Record<DecorationName, string> = {")
    for name, uri in found:
        lines.append(f"  // {DECORATIONS[name]['note']}")
        lines.append(f"  {name}:")
        lines.append(f"    '{uri}',")
    lines.append("};")
    lines.append("")
    lines.append("export default DECORATIONS;")
    lines.append("")

    (OUT_DIR / "index.ts").write_text("\n".join(lines), encoding="utf-8")

    print(f"[ok] 导出 {len(found)} 个装饰图形 -> {OUT_DIR.name}/index.ts")
    for name, uri in found:
        print(f"     {name:<14} {len(uri):>6} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
