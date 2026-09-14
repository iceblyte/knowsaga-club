# -*- coding: utf-8 -*-
"""第二轮形态对比：折纸信使（纸鸢）+ 宝箱怪（铜宝）。"""
import os
import kit as K

OUT = os.path.dirname(os.path.abspath(__file__))
F, S, L = K.PAPER_F, K.PAPER_S, K.PAPER_L
G, GL, SEAL, CREAM, INK = K.GOLD, K.GOLD_LINE, K.SEAL, K.CREAM, K.INK
W, WD, WL, WDK = K.WOOD, K.WOOD_D, K.WOOD_LINE, K.WOOD_DARK


def wrap(inner, size=190):
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 100 100">'
            + inner + "</svg>")


def seal_mark(cx, cy, r=5.2):
    """朱砂印：实心圆 + 内圈，不用 X（X 会读成「禁止」）。"""
    return ('<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="' + str(r) + '" fill="' + SEAL + '"/>'
            '<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="' + str(r * 0.48)
            + '" fill="none" stroke="' + CREAM + '" stroke-width="1.3"/>')


# ---- 折纸信使 E：经典折纸飞机 + 脸 ----
E = (
    '<path d="M92 20 40 62 52 88Z" fill="' + S + '" stroke="' + L + '" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M92 20 8 52 40 62Z" fill="' + F + '" stroke="' + L + '" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M92 20 40 62" stroke="' + L + '" stroke-width="1.4" opacity=".55" fill="none"/>'
    '<path d="M8 52 56 44" stroke="' + L + '" stroke-width="1.1" opacity=".4" fill="none"/>'
    + seal_mark(44, 50, 5)
    + '<circle cx="70" cy="37" r="3.4" fill="' + INK + '"/>'
    '<circle cx="80" cy="30" r="3.4" fill="' + INK + '"/>'
    '<circle cx="68.8" cy="35.8" r="1.2" fill="#FFF"/>'
    '<circle cx="78.8" cy="28.8" r="1.2" fill="#FFF"/>'
    '<path d="M74 42q4 3 8-1" fill="none" stroke="' + INK + '" stroke-width="1.8" stroke-linecap="round"/>')

# ---- 折纸信使 F：双翼平展（更像鸟） ----
FF = (
    '<path d="M88 26 10 34 44 58Z" fill="' + S + '" stroke="' + L + '" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M88 26 12 74 44 58Z" fill="' + F + '" stroke="' + L + '" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M88 26 44 58" stroke="' + L + '" stroke-width="1.4" opacity=".55" fill="none"/>'
    '<path d="M12 74 40 76" stroke="' + L + '" stroke-width="1.2" opacity=".45" fill="none"/>'
    + seal_mark(56, 42, 5)
    + '<circle cx="74" cy="32" r="3.4" fill="' + INK + '"/>'
    '<circle cx="66" cy="42" r="3.4" fill="' + INK + '"/>'
    '<circle cx="72.8" cy="30.8" r="1.2" fill="#FFF"/>'
    '<circle cx="64.8" cy="40.8" r="1.2" fill="#FFF"/>')

# ---- 折纸信使 G：竖向折角（更方正） ----
GG = (
    '<path d="M50 6 92 62 50 88Z" fill="' + S + '" stroke="' + L + '" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M50 6 8 62 50 88Z" fill="' + F + '" stroke="' + L + '" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M50 6 50 88" stroke="' + L + '" stroke-width="1.4" opacity=".5" fill="none"/>'
    '<path d="M50 6 8 62M50 6 92 62" stroke="' + L + '" stroke-width="1.1" opacity=".35" fill="none"/>'
    + seal_mark(50, 60, 5)
    + '<circle cx="40" cy="26" r="3.4" fill="' + INK + '"/>'
    '<circle cx="60" cy="26" r="3.4" fill="' + INK + '"/>'
    '<circle cx="38.8" cy="24.8" r="1.2" fill="#FFF"/>'
    '<circle cx="58.8" cy="24.8" r="1.2" fill="#FFF"/>'
    '<path d="M46 34q4 3.5 8 0" fill="none" stroke="' + INK + '" stroke-width="1.8" stroke-linecap="round"/>')


# ---- 铜宝 H：箱体 + 内侧暗层 + 探头眼睛 + 后掀的盖 ----
def chest(rot, eyes_y, arm):
    a = ""
    if arm:
        a = ('<path d="M16 62c-6 2-10 7-9 11 1 3 5 4 8 2 4-2 6-7 5-11-1-2-2-2-4-2z" fill="'
             + W + '" stroke="' + WL + '" stroke-width="1.8" stroke-linejoin="round"/>'
             '<path d="M84 62c6 2 10 7 9 11-1 3-5 4-8 2-4-2-6-7-5-11 1-2 2-2 4-2z" fill="'
             + W + '" stroke="' + WL + '" stroke-width="1.8" stroke-linejoin="round"/>')
    return (
        a
        + '<rect x="18" y="38" width="64" height="18" rx="3" fill="' + WDK + '"/>'
        + '<ellipse cx="40" cy="' + str(eyes_y) + '" rx="6.6" ry="7" fill="' + INK + '"/>'
        '<ellipse cx="60" cy="' + str(eyes_y) + '" rx="6.6" ry="7" fill="' + INK + '"/>'
        '<circle cx="37.6" cy="' + str(eyes_y - 2.8) + '" r="2.3" fill="#FFF"/>'
        '<circle cx="57.6" cy="' + str(eyes_y - 2.8) + '" r="2.3" fill="#FFF"/>'
        # 箱体
        '<path d="M12 52h76v30a6 6 0 0 1-6 6H18a6 6 0 0 1-6-6z" fill="' + WD
        + '" stroke="' + WL + '" stroke-width="2.2" stroke-linejoin="round"/>'
        '<rect x="22" y="52" width="5" height="36" fill="' + WL + '" opacity=".38"/>'
        '<rect x="73" y="52" width="5" height="36" fill="' + WL + '" opacity=".38"/>'
        '<rect x="42" y="60" width="16" height="15" rx="2.5" fill="' + G + '" stroke="'
        + WL + '" stroke-width="1.8"/>'
        '<circle cx="50" cy="66" r="2.1" fill="' + WL + '"/>'
        '<path d="M50 67.8v3.6" stroke="' + WL + '" stroke-width="1.7" stroke-linecap="round"/>'
        # 盖（绕左铰链后掀）
        '<g transform="rotate(' + str(rot) + ' 12 52)">'
        '<path d="M12 52c0-13 17-22 38-22s38 9 38 22z" fill="' + W + '" stroke="' + WL
        + '" stroke-width="2.2" stroke-linejoin="round"/>'
        '<rect x="23" y="34" width="5" height="18" fill="' + WL + '" opacity=".45"/>'
        '<rect x="72" y="34" width="5" height="18" fill="' + WL + '" opacity=".45"/>'
        '<rect x="41" y="44" width="18" height="9" rx="2" fill="' + G + '" stroke="'
        + WL + '" stroke-width="1.8"/></g>')


H1 = chest(-16, 46, True)
H2 = chest(-30, 48, False)
H3 = chest(-16, 48, False)

cells = "".join(
    '<div style="background:#FEFCF6;border:1px solid #D9C6A4;border-radius:8px;padding:10px;'
    'display:flex;flex-direction:column;align-items:center;gap:6px">' + wrap(v)
    + '<div style="font-size:12px;color:#6B5A45">' + n + '</div></div>'
    for n, v in [("E 飞机+脸", E), ("F 双翼", FF), ("G 竖折", GG),
                 ("H1 掀盖+手", H1), ("H2 大掀+无手", H2), ("H3 小掀+无手", H3)])

small = ""
for v in [E, FF, GG, H1, H2, H3]:
    small += ('<div style="background:#F1E8D0;padding:8px;border-radius:6px">'
              '<svg width="52" height="52" viewBox="0 0 100 100">' + v + "</svg></div>")

html = ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'></head><body "
        "style='background:#F1E8D0;padding:18px;font-family:sans-serif'>"
        "<div style='display:flex;gap:12px'>" + cells + "</div>"
        "<div style='margin-top:14px;display:flex;gap:12px;align-items:center'>" + small
        + "</div></body></html>")

with open(os.path.join(OUT, "_crane_var.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("ok")
