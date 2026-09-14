# -*- coding: utf-8 -*-
"""全量截图：用系统 Chrome 的 headless 模式逐页整页截图，用于视觉自检。
不依赖 agent-browser，无需下载 Chromium。"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W, SCALE = 1360, 1
BG_PER_PHONE = 1180          # 每行手机的大致高度
TAIL = 420                   # 页头 + 说明 + 页脚留白

FILES = ["00-设计规范", "01-核心闭环", "02-挑战副本", "03-冒险日志",
         "04-冒险者档案", "05-卷轴工坊", "06-公会社交", "07-会员与设置"]

only = sys.argv[1:] or [f[:2] for f in FILES]
os.makedirs(SHOTS, exist_ok=True)

for f in FILES:
    if f[:2] not in only:
        continue
    # 设计规范页不是手机网格，单独给高一点
    if f.startswith("00"):
        h = 7200
    else:
        import re
        html = open(os.path.join(ROOT, f + ".html"), encoding="utf-8").read()
        n = html.count('class="slot"')
        rows = (n + 2) // 3
        h = rows * BG_PER_PHONE + TAIL
    out = os.path.join(SHOTS, f[:2] + ".png")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=" + str(SCALE),
           "--window-size=%d,%d" % (W, h),
           "--screenshot=" + out,
           "file:///" + os.path.join(ROOT, f + ".html").replace("\\", "/")]
    subprocess.run(cmd, capture_output=True)
    print("  ok  %s  (%dx%d)" % (f[:2] + ".png", W, h))
print("done ->", SHOTS)
