# -*- coding: utf-8 -*-
"""角色检视页（分屏）：每次只渲染一小批，放到足够大以便肉眼校对形状。"""
import os
import sys
import kit as K

OUT = os.path.dirname(os.path.abspath(__file__))
which = sys.argv[1] if len(sys.argv) > 1 else "cast"


def cell(label, svg, bg="#F1E8D0", pad=16):
    return ('<div style="background:' + bg + ';border:1px solid #D9C6A4;border-radius:8px;'
            'padding:' + str(pad) + 'px;display:flex;flex-direction:column;align-items:center;'
            'gap:10px">' + svg + '<div style="font-size:12px;color:#6B5A45">' + label
            + "</div></div>")


def row(items, gap=16):
    return ('<div style="display:flex;gap:' + str(gap) + 'px;flex-wrap:wrap;'
            'align-items:flex-end">' + "".join(items) + "</div>")


SIZE = 200
blocks = []
if which == "cast":
    blocks.append(row([
        cell("拾拾 · normal", K.shishi("normal", SIZE)),
        cell("墨墨 · normal", K.momo("normal", SIZE)),
        cell("纸鸢", K.yuanyuan(SIZE)),
        cell("铜宝 · open", K.tongbao(SIZE)),
    ]))
elif which == "owl":
    blocks.append(row([cell("墨墨 " + s, K.momo(s, SIZE)) for s in
                       ["normal", "happy", "think", "sad"]]))
elif which == "av":
    blocks.append(row([cell(K.AV_NAME[k], K.adv_avatar(k, SIZE), "#FEFCF6")
                       for k in K.AV_ORDER[:3]]))
    blocks.append(row([cell(K.AV_NAME[k], K.adv_avatar(k, SIZE), "#FEFCF6")
                       for k in K.AV_ORDER[3:]]))
elif which == "small":
    blocks.append("<div style='font-size:12px;color:#6B5A45'>真实使用尺寸 · 上排 56px，下排 30px</div>")
    blocks.append(row([cell(n, f(56), pad=10) for n, f in [
        ("拾拾", K.shishi), ("墨墨", K.momo), ("鸢鸢", K.yuanyuan), ("铜宝", K.tongbao)]]))
    blocks.append(row([cell(n, f(30), pad=8) for n, f in [
        ("拾拾", K.shishi), ("墨墨", K.momo), ("鸢鸢", K.yuanyuan), ("铜宝", K.tongbao)]]))
elif which == "avsmall":
    blocks.append(row([cell(K.AV_NAME[k], K.adv_avatar(k, 44), "#FEFCF6", 8)
                       for k in K.AV_ORDER]))
    blocks.append(row([cell(K.AV_NAME[k], K.adv_avatar(k, 28), "#FEFCF6", 6)
                       for k in K.AV_ORDER]))

html = ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'><style>" + K.CSS +
        "body{padding:20px}</style></head><body>" + "".join(blocks) + "</body></html>")
with open(os.path.join(OUT, "_chars_" + which + ".html"), "w", encoding="utf-8") as f:
    f.write(html)
print("ok _chars_" + which + ".html")
