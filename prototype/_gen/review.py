# -*- coding: utf-8 -*-
"""单屏复核：把指定 HTML 里第 N 个手机屏隔离出来放大截图，便于逐屏肉眼检查。
用法： python review.py 02 3 4        # 02 号文件的第 3、4 屏
       python review.py 00 1 2        # 00 设计规范页的区块（按 .ds-sec 序号）
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

num = sys.argv[1]
idxs = [int(x) for x in sys.argv[2:]] or [1]
files = {"00": "00-设计规范", "01": "01-核心闭环", "02": "02-挑战副本",
         "03": "03-冒险日志", "04": "04-冒险者档案", "05": "05-卷轴工坊",
         "06": "06-公会社交", "07": "07-会员与设置"}
src = os.path.join(ROOT, files[num] + ".html")
html = open(src, encoding="utf-8").read()

if num == "00":
    sel = ".ds-sec"
    colcss = ".ds-sec{padding:20px;max-width:1160px}"
    w = 1240
    # 隔离时用 block 而不是 flex：flex 会让章节的 h2 / p / 内容块都变成
    # 并排的 flex item，只有「单子元素」的章节看着正常，多子元素的章节会被
    # 挤成竖条。block 才和页面里的真实排版一致。
    show = "display:block!important"
else:
    sel = ".grid>.slot"
    colcss = (".wrap{max-width:520px;padding:20px}.grid{grid-template-columns:minmax(0,1fr)}"
              ".slot{margin-bottom:26px}")
    w = 500
    show = "display:flex!important"

for i in idxs:
    css = ("<style>" + colcss
           + sel + "{display:none!important}"
           + sel + ":nth-child(" + str(i) + "){" + show + "}</style>")
    tmp = html.replace("</head>", css + "\n</head>")
    tp = os.path.join(ROOT, "_gen", "_review.html")
    open(tp, "w", encoding="utf-8").write(tmp)
    out = os.path.join(SHOTS, "rv-%s-%d.png" % (num, i))
    # 手机屏往往比 1000px 高，底部标签栏会被裁掉；用 REVIEW_H 调高窗口即可看到全屏
    h = int(os.environ.get("REVIEW_H", "1000"))
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", "--window-size=%d,%d" % (w, h),
                    "--screenshot=" + out, "file:///" + tp.replace("\\", "/")],
                   capture_output=True)
    print("  ok  rv-%s-%d.png" % (num, i))
