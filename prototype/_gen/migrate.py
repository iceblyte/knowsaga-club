# -*- coding: utf-8 -*-
"""一次性迁移脚本：把 gen_a.py / gen_b.py 迁到新的设计系统。

改动三处：
  1) doc() 签名由 (title, kicker, desc, tags, body) 改为 (num, name, desc, tags, body)
     —— 去掉全大写的英文眉标，改为「卷宗编号」。
  2) 去掉静态精灵上无差别的漂浮动效（27 处），动效只保留在 stage() 与答题反馈。
  3) 删除装饰性角标 corners()（Chanel：出门前摘掉一件配饰）。
"""
import io
import re

DOCS = [
    ("00 · 设计规范", "Design System", "00", "设计规范"),
    ("01 · 核心业务闭环", "Core Flow", "01", "核心业务闭环"),
    ("02 · 挑战副本", "Quiz Screens", "02", "挑战副本"),
    ("03 · 冒险探险日志", "Report & Share", "03", "冒险探险日志"),
    ("04 · 冒险者档案", "Profile & Analytics", "04", "冒险者档案"),
    ("05 · 卷轴工坊", "Input Workshop", "05", "卷轴工坊"),
    ("06 · 公会社交", "Social & PK", "06", "公会社交"),
    ("07 · 会员与设置", "Commerce & Settings", "07", "会员与设置"),
]

report = []


def run(path):
    src = io.open(path, encoding="utf-8").read()
    n = {}

    # ---- 1. doc() 签名 ----
    c = 0
    for title, kicker, num, name in DOCS:
        old = 'doc("' + title + '", "' + kicker + '",'
        new = 'doc("' + num + '", "' + name + '",'
        if old in src:
            src = src.replace(old, new)
            c += 1
    n["doc"] = c

    # ---- 2. 去掉静态精灵的漂浮动效 ----
    f = 0
    for suffix in [' fast', ' slow', '']:
        old = ', "floaty' + suffix + '")'
        f += src.count(old)
        src = src.replace(old, ")")
    n["floaty"] = f

    # ---- 3. 删除装饰角标 ----
    k = src.count("corners() + ")
    src = src.replace("corners() + ", "")
    n["corners"] = k

    # 清理 import
    src = re.sub(r"(scroll_icon, scrollbox), corners\)", r"\1)", src)

    io.open(path, "w", encoding="utf-8").write(src)
    report.append((path, n))


for p in ["gen_a.py", "gen_b.py"]:
    run(p)

for path, n in report:
    print("%-10s  doc %d/8   floaty 清除 %d   corners 清除 %d" % (path, n["doc"], n["floaty"], n["corners"]))
