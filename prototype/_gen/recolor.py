# -*- coding: utf-8 -*-
"""把生成器里硬编码的旧色值统一替换为新设计系统的色值。

注意顺序：bg="#FDF8EF" 是「手机屏底」，在新系统里应映射到纸色 paper；
而其它位置的 #FDF8EF 是「页面底」，应映射到板色 board。所以先处理带 bg= 的。
"""
import io

# 顺序敏感：先处理特殊上下文
PRE = [
    ('bg="#FDF8EF"', 'bg="#FEFCF6"'),   # 手机屏底 → 纸色
]

MAP = [
    # 底色与面
    ("#FDF8EF", "#F1E8D0"),   # 页面底 → 板色
    ("#FFFBF3", "#FEFCF6"),   # 卡片面 → 纸色
    ("#F3EADA", "#F5EDD8"),   # 次级面 → 压痕面
    ("#EFE3D0", "#EADFC4"),   # 分隔线 → 深压痕
    ("#FFFFFF", "#FEFCF6"),   # 纯白 → 纸色（避免刺眼的白与纸色打架）
    ("#FFFDF8", "#F5EDD8"),
    # 线
    ("#E3D5BC", "#D9C6A4"),
    ("#C9B79A", "#C4B08C"),
    ("#E8DCC8", "#E0D2B4"),
    ("#D9C9AC", "#CDBB9A"),
    # 墨
    ("#3A2E22", "#2A2018"),
    ("#5A4B3A", "#6B5A45"),
    ("#8A7A66", "#6B5A45"),
    ("#A08B6E", "#9A8870"),
    ("#B0A08A", "#9A8870"),
    # 魔法蓝
    ("#3D8BFD", "#2F6BD8"),
    ("#2A6FD6", "#1F4694"),
    ("#E8F1FE", "#DCE9FB"),
    ("#85B7EB", "#7FA9D8"),
    ("#C4DCFB", "#B9D5F2"),
    # 金 / 铜
    ("#F5B301", "#C8912A"),
    ("#D99A00", "#9C6E15"),
    ("#FDF3D9", "#F8EFD6"),
    ("#E8C86A", "#D4A94A"),
    ("#F0DCA8", "#E8D2A0"),
    ("#D9C08A", "#C4A874"),
    # 语义
    ("#3FAE6B", "#2F7D4F"),
    ("#2C7F4D", "#1F5A38"),
    ("#1E5C3A", "#2F7D4F"),
    ("#E6F6EC", "#DFF0E4"),
    ("#E5484D", "#A63A2E"),
    ("#8A2B2E", "#A63A2E"),
    ("#A32D2D", "#7A2820"),
    ("#FDECEC", "#F7E3DF"),
    ("#8B5CF6", "#6D4BC4"),
    ("#6D3FD4", "#6D4BC4"),
    ("#F0EBFE", "#EDE8FA"),
    ("#C4B0F7", "#B9A2EE"),
]

report = []
for path in ["gen_a.py", "gen_b.py"]:
    src = io.open(path, encoding="utf-8").read()
    n = 0
    for old, new in PRE:
        n += src.count(old)
        src = src.replace(old, new)
    for old, new in MAP:
        n += src.count(old)
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8").write(src)
    report.append((path, n))

for p, n in report:
    print("%-10s 替换 %d 处" % (p, n))

# 残留检查
import re
for path in ["gen_a.py", "gen_b.py"]:
    src = io.open(path, encoding="utf-8").read()
    left = sorted(set(re.findall(r"#[0-9A-Fa-f]{6}", src)))
    known = {"#2A2018", "#F1E8D0", "#FEFCF6", "#F5EDD8", "#EADFC4", "#D9C6A4",
             "#C4B08C", "#E0D2B4", "#CDBB9A", "#6B5A45", "#9A8870", "#2F6BD8",
             "#1F4694", "#DCE9FB", "#7FA9D8", "#B9D5F2", "#C8912A", "#9C6E15",
             "#F8EFD6", "#D4A94A", "#E8D2A0", "#C4A874", "#2F7D4F", "#1F5A38",
             "#DFF0E4", "#A63A2E", "#7A2820", "#F7E3DF", "#6D4BC4", "#EDE8FA",
             "#B9A2EE", "#FFF9EA", "#3D2A05", "#D3C29F", "#F7EBCB", "#E4F0FB",
             "#C2DFF7", "#E8A0AE", "#8F6210", "#AE7A1C", "#C68B22", "#6B4408",
             "#FFF3D0", "#4A3608"}
    odd = [c for c in left if c not in known]
    if odd:
        print("  %s 未映射色值: %s" % (path, " ".join(odd)))
