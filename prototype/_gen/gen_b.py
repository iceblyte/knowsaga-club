"""生成 04-冒险者档案 / 05-卷轴工坊 / 06-公会社交 / 07-会员与设置"""
import os
import kit as K
from kit import (card, slip, stamp, rule, btn, opt, bar, ring, li, phone, grid, doc,
                 nav, tabbar, magic, shishi, stage, coin, chest, medal, sparkle,
                 scroll_icon, scrollbox, momo, yuanyuan, tongbao, adv_avatar,
                 avatar_blank, AV_ORDER, AV_NAME)

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 身份映射：好友与排行榜的六位冒险者，头像与各自的学习阶段对应。
# 名单复用公会社交的同一批人，保证跨页面「同一个人长得一样」。
ME = ("scholar", "冒险者 · 拾光")
PEERS = [
    ("apprentice", "阿库娅不想学习", "Lv.5"),
    ("mage", "惠惠只想放爆裂魔法", "Lv.4"),
    ("knight", "达克妮丝", "Lv.2"),
    ("ranger", "和真", "Lv.3"),
]
AV_OF = dict(zip([n for _, n, _ in PEERS] + [ME[1]], [k for k, _, _ in PEERS] + [ME[0]]))


def av_of(name):
    """按名字取头像款式。允许列表里给名字加「（我）」等后缀做标注，
    查找时先剥掉后缀，避免同一个人在不同页面换了张脸。"""
    key = name.split("（")[0].strip()
    return AV_OF.get(key, "apprentice")


def who(name, desc="", lv="", size=38):
    """身份位：头像 + 姓名 + 副信息。取代原先的纯色圆占位。"""
    k = av_of(name)
    d = desc or lv
    return ('<div class="who">' + adv_avatar(k, size) + '<div class="tx">'
            + '<div class="n">' + name + '</div>'
            + ('<div class="d">' + d + '</div>' if d else "") + "</div></div>")


def w(name, html):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(html)
    print("  ok  " + name)


def hero(xp=1280, lv=3, streak=4):
    return card('<div class="between"><div class="row" style="gap:9px">'
                + adv_avatar(ME[0], 32)
                + '<div><div style="font-size:12px;font-weight:600">Lv.' + str(lv) + ' 见习冒险者</div>'
                '<div class="tiny">' + str(xp) + ' / 2000 XP</div></div></div>'
                '<span class="pill gold">连续 ' + str(streak) + ' 天</span></div>'
                '<div style="height:8px"></div>' + bar(int(xp * 100 / 2000), "blue"))


# =====================================================================
# 04 冒险者档案
# =====================================================================
def tree_svg():
    """知识树：三层、等距。宽度按最宽一行（4 个叶子节点）反推，
    保证任何一层都不越界——首版的根节点 x=-24 被容器裁掉了。"""
    W, GAP = 78, 14          # 节点宽 / 节点间距
    PAD = 6                  # 左右留白
    step = W + GAP           # 相邻节点中心距 = 92
    c = [PAD + W / 2 + i * step for i in range(4)]      # 第三层 4 个中心：45 137 229 321
    mid = lambda a, b: (a + b) / 2
    nodes = [
        (mid(mid(c[0], c[1]), mid(c[2], c[3])), 24, "AI 基础", "#2F6BD8"),
        (mid(c[0], c[1]), 96, "RAG", "#2F7D4F"),
        (mid(c[2], c[3]), 96, "Prompt", "#C8912A"),
        (c[0], 168, "向量检索", "#2F7D4F"),
        (c[1], 168, "知识库", "#D9C6A4"),
        (c[2], 168, "提示词", "#C8912A"),
        (c[3], 168, "评测", "#D9C6A4"),
    ]
    lines = [(nodes[0][0], 54, nodes[1][0], 96), (nodes[0][0], 54, nodes[2][0], 96),
             (nodes[1][0], 126, nodes[3][0], 168), (nodes[1][0], 126, nodes[4][0], 168),
             (nodes[2][0], 126, nodes[5][0], 168), (nodes[2][0], 126, nodes[6][0], 168)]
    out = []
    for x1, y1, x2, y2 in lines:
        out.append('<line x1="' + str(x1) + '" y1="' + str(y1) + '" x2="' + str(x2) + '" y2="'
                   + str(y2) + '" stroke="#D9C6A4" stroke-width="1.5"/>')
    for x, y, t, col in nodes:
        out.append('<rect x="' + str(x - W / 2) + '" y="' + str(y) + '" width="' + str(W)
                   + '" height="30" rx="10" fill="' + col + '" opacity="'
                   + ("0.16" if col != "#D9C6A4" else "0.5") + '"/>')
        out.append('<rect x="' + str(x - W / 2) + '" y="' + str(y) + '" width="' + str(W)
                   + '" height="30" rx="10" fill="none" stroke="' + col + '" stroke-width="1"/>')
        out.append('<text x="' + str(x) + '" y="' + str(y + 15) + '" text-anchor="middle" '
                   'dominant-baseline="central" font-size="11.5" font-weight="600" fill="#2A2018">'
                   + t + "</text>")
    return ('<svg width="100%" viewBox="0 0 ' + str(PAD * 2 + W * 4 + GAP * 3) + ' 210" '
            'style="display:block">' + "".join(out) + "</svg>")


def dmark(ch, bg, line, fg):
    """知识领域标记：方块 + 首字，与 .li 的图标同一语言（并列项不用编号）。"""
    return ('<span style="width:28px;height:28px;border-radius:6px;background:' + bg
            + ';box-shadow:inset 0 0 0 1px ' + line + ';color:' + fg + ';flex:none;'
            'display:flex;align-items:center;justify-content:center;font-size:12.5px;'
            'font-weight:700;font-family:var(--f-disp)">' + ch + "</span>")


def build_04():
    s1 = phone("个人中心",
               head=nav("我的档案", back=False, right="设置"),
               foot=tabbar(4),
               desc="个人中心首屏，先给身份认同，再给数据。",
               title="冒险者卡片用金色描边强调「这是你的身份」，与普通卡片区分。",
               body=card('<div class="row" style="gap:12px">'
                         + adv_avatar("scholar", 58) +
                         '<div style="flex:1"><div style="font-size:15px;font-weight:600">冒险者 · 拾光</div>'
                         '<div class="row" style="margin-top:6px;gap:6px">'
                         '<span class="pill gold">Lv.3</span><span class="pill blue">见习冒险者</span></div></div></div>'
                         '<div style="height:12px"></div>'
                         '<div class="between"><span class="tiny">距离 Lv.4 还差 720 XP</span>'
                         '<span class="tiny c-blue">1280 / 2000</span></div>'
                         '<div style="height:6px"></div>' + bar(64, "blue"), "gold")
                    + '<div class="grid3">'
                    + card('<div class="stat sm c-blue">12</div><div class="statlab">闯关副本</div>', "plain")
                    + card('<div class="stat sm c-gold">1840</div><div class="statlab">累计 XP</div>', "plain")
                    + card('<div class="stat sm c-ok">83%</div><div class="statlab">平均正确率</div>', "plain")
                    + "</div>"
                    + li("树", "知识树", "已点亮 5 个知识领域", "查看")
                    + li("账", "历史卷轴", "共 12 份冒险日志", "12")
                    + li("印", "勋章墙", "已解锁 6 / 18 枚", "6"))

    s2 = phone("冒险者卡片",
               head=nav("冒险者卡片"),
               bg="#FEFCF6",
               desc="把成长数据包装成一张公会卡，是留存的关键情绪锚点。",
               title="卡片可长按保存，用于在社群里展示自己的学习进度。",
               body=card('<div style="text-align:center;padding:6px">'
                         '<div class="tiny">知拾冒险社 · 冒险者公会卡</div>'
                         '<div style="height:16px"></div>'
                         '<div style="display:flex;justify-content:center">' + adv_avatar("scholar", 84) + "</div>"
                         '<div style="font-size:17px;font-weight:700;margin-top:6px">冒险者 · 拾光</div>'
                         '<div class="row" style="justify-content:center;margin-top:8px;gap:6px">'
                         '<span class="pill gold">Lv.3</span><span class="pill blue">见习冒险者</span></div>'
                         '<div style="height:18px"></div>'
                         '<div class="grid3">'
                         '<div><div class="stat sm">12</div><div class="statlab">副本</div></div>'
                         '<div><div class="stat sm">83%</div><div class="statlab">正确率</div></div>'
                         '<div><div class="stat sm">4</div><div class="statlab">连续天数</div></div>'
                         "</div>"
                         '<div style="height:16px"></div>'
                         '<div style="height:1px;background:#EADFC4"></div>'
                         '<div class="row" style="justify-content:space-between;margin-top:12px">'
                         '<span class="tiny">职业倾向 · 检索者</span>'
                         '<span class="tiny">加入第 38 天</span></div>'
                         "</div>", "parch")
                    + '<div class="spacer"></div>'
                    + btn("保存公会卡")
                    + btn("分享给好友", "ghost"))

    s3 = phone("学习数据看板",
               head=nav("数据看板", right="近 30 天"),
               desc="用图表回答「我这段时间到底学得怎么样」。",
               title="柱状图只展示最近 7 天，避免移动端柱子过密不可读；趋势用文字补充。",
               body=card('<div class="between"><span class="tiny">近 7 天答题量</span>'
                         '<span class="tiny c-ok">较上周 +18%</span></div>'
                         '<div style="height:12px"></div>'
                         '<div class="row" style="align-items:flex-end;gap:8px;height:88px">'
                         + "".join('<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:5px">'
                                   '<div style="width:100%;height:' + str(h) + 'px;border-radius:6px 6px 0 0;'
                                   'background:' + ("#2F6BD8" if h == mh else "#B9D5F2") + '"></div>'
                                   '<span class="tiny" style="font-size:10px">' + d + "</span></div>"
                                   for d, h, mh in [("一", 34, 34), ("二", 52, 34), ("三", 22, 34),
                                                    ("四", 60, 34), ("五", 44, 34), ("六", 28, 34),
                                                    ("日", 48, 34)])
                         + "</div>")
                    + '<div class="grid2">'
                    + card('<div class="tiny">正确率趋势</div>'
                           '<div class="stat sm c-ok" style="margin-top:6px">83%</div>'
                           '<div class="tiny" style="margin-top:4px">连续 3 周上升</div>', "plain")
                    + card('<div class="tiny">平均单局用时</div>'
                           '<div class="stat sm c-blue" style="margin-top:6px">3m24s</div>'
                           '<div class="tiny" style="margin-top:4px">较上周快 21 秒</div>', "plain")
                    + "</div>"
                    + card('<div class="tiny" style="margin-bottom:8px">各知识领域掌握度</div>'
                           '<div class="stack tight">'
                           '<div><div class="between"><span class="tiny">AI 基础</span>'
                           '<span class="tiny c-ok">92%</span></div>' + bar(92, "ok") + "</div>"
                           '<div><div class="between"><span class="tiny">RAG</span>'
                           '<span class="tiny c-gold">80%</span></div>' + bar(80) + "</div>"
                           '<div><div class="between"><span class="tiny">Prompt 工程</span>'
                           '<span class="tiny c-bad">58%</span></div>'
                           + '<div class="bar"><i style="width:58%;background:#A63A2E"></i></div></div>'
                           "</div>", "plain"))

    s4 = phone("知识树",
               head=nav("知识树"),
               desc="把零散的闯关记录聚合成一棵树，让成长有形状。",
               title="已点亮的节点用彩色描边，未点亮保持暖棕描边；点击节点查看该领域日志。",
               body=card(tree_svg(), "plain")
                    + card('<div class="row" style="gap:10px">'
                           + dmark("基", "#E6F2E9", "rgba(47,125,79,.34)", "#2F7D4F")
                           + '<div style="flex:1"><div class="tiny">AI 基础</div>'
                           '<div style="height:6px"></div>' + bar(92, "ok") + "</div>"
                           '<span class="pill ok">已点亮</span></div>'
                           '<div style="height:10px"></div>'
                           + '<div class="row" style="gap:10px">'
                           + dmark("R", "#F8EFD6", "rgba(200,145,42,.36)", "#9C6E15")
                           + '<div style="flex:1"><div class="tiny">RAG</div>'
                           '<div style="height:6px"></div>' + bar(80) + "</div>"
                           '<span class="pill gold">进行中</span></div>'
                           '<div style="height:10px"></div>'
                           + '<div class="row" style="gap:10px">'
                           + dmark("评", "#F5EDD8", "rgba(150,120,72,.34)", "#9A8870")
                           + '<div style="flex:1"><div class="tiny">评测</div>'
                           '<div style="height:6px"></div>' + bar(0) + "</div>"
                           '<span class="pill">未开始</span></div>')
                    + '<div class="spacer"></div>'
                    + card('<div class="row" style="gap:10px;align-items:center">'
                           + momo("think", 54)
                           + '<div class="body sm">RAG 已经点亮了 80%，'
                           '再闯一次「向量检索」就能整片亮起来。</div></div>', "parch")
                    + btn("点亮新领域", "gold"))

    s5 = phone("历史卷轴",
               head=nav("历史卷轴"),
               desc="所有领取过的卷轴，按时间倒序。",
               title="支持按知识领域筛选，长按可删除，删除仅移除记录不影响统计。",
               body='<div class="row" style="gap:6px;flex-wrap:wrap">'
                    '<span class="chip" style="background:#2F6BD8;color:#fff;border-color:#2F6BD8">全部</span>'
                    '<span class="chip">AI 基础</span><span class="chip">RAG</span>'
                    '<span class="chip">Prompt</span></div>'
                    + li("卷", "RAG 入门闯关", "今天 14:20 · 正确率 80%", "5 题")
                    + li("卷", "近代史纲要 · 第三章", "昨天 21:05 · 正确率 100%", "5 题")
                    + li("卷", "Prompt 工程入门", "9 月 11 日 · 正确率 60%", "5 题")
                    + li("卷", "向量数据库选型", "9 月 9 日 · 正确率 80%", "5 题")
                    + '<div class="spacer"></div>'
                    + '<div class="tiny" style="text-align:center">已经到底了 · 共 12 份卷轴</div>')

    s6 = phone("卷轴详情",
               head=nav("卷轴详情", right="重做"),
               desc="单份卷轴的回看页，包含逐题作答记录。",
               title="可展开任意一题重看讲解，是「复盘」这个需求最直接的落点。",
               body=card('<div class="between"><div><div class="h sm">RAG 入门闯关</div>'
                         '<div class="tiny" style="margin-top:4px">今天 14:20 · 用时 3 分 12 秒</div></div>'
                         + ring(80, size=58, stroke=7, label="80%", lab_size=14) + "</div>")
                    + card('<div class="between"><span class="tiny">第 1 题 · 单选</span>'
                           '<span class="pill ok">答对</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           'RAG 与传统关键词检索最核心的差别是什么？</div>'
                           '<div class="tiny" style="margin-top:8px">我的答案：C · 正确</div>')
                    + card('<div class="between"><span class="tiny">第 2 题 · 单选</span>'
                           '<span class="pill ok">答对</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           '向量检索相比关键词检索主要解决什么问题？</div>'
                           '<div class="tiny" style="margin-top:8px">我的答案：A · 正确</div>')
                    + card('<div class="between"><span class="tiny">第 3 题 · 多选</span>'
                           '<span class="pill gold">部分正确</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           '以下哪些属于 RAG 相比传统搜索的优势？</div>'
                           '<div class="tiny" style="margin-top:8px">我的答案：A、C · 正确答案 A、C、D</div>', "gold")
                    + '<div class="spacer"></div>'
                    + btn("重新挑战这一卷", "ghost"))

    s7 = phone("旧识重温 · 错题本",
               head=nav("旧识重温"),
               foot=tabbar(4),
               desc="答错的题按遗忘曲线排队，在合适的时间重新出现。",
               title="每道错题标注「第几次复习」与下次出现时间，让用户理解这个机制不是随机推送。",
               body=card('<div class="row" style="gap:10px;align-items:flex-start">'
                         + momo("think", 54) +
                         '<div style="flex:1;min-width:0">'
                         '<div class="between"><span class="tiny">待复习错题</span>'
                         '<span class="pill bad">3 题到期</span></div>'
                         '<div class="body sm" style="margin-top:8px">'
                         '按艾宾浩斯遗忘曲线，这 3 道题今天最适合重做，'
                         '此时回忆的成本最低、效果最好。</div></div></div>', "parch")
                    + li("题", "RAG 与搜索引擎的边界", "答错 1 次 · 今天到期", "重做")
                    + li("题", "Prompt 中的角色设定", "答错 2 次 · 今天到期", "重做")
                    + li("题", "向量维度与召回率", "答错 1 次 · 明天到期", "待复习")
                    + li("题", "分块策略对效果的影响", "答错 1 次 · 3 天后", "待复习")
                    + '<div class="spacer"></div>'
                    + btn("开始旧识重温关卡"))

    s8 = phone("复习提醒",
               head=nav("复习提醒"),
               bg="#FEFCF6",
               desc="从微信服务通知唤回用户的落地页。",
               title="提醒文案强调「只需 2 分钟」，把重新开始的成本说到最低。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:14px">'
                    + yuanyuan(126, "drift") +
                    '<div style="text-align:center"><div class="h">你有 3 道旧识在等你</div>'
                    '<div class="body sm" style="margin-top:8px">'
                    '三天前你在「RAG 与搜索引擎的边界」上失手，现在重做记得最牢。</div></div>'
                    + card('<div class="row" style="justify-content:center;gap:16px">'
                           '<div style="text-align:center"><div class="stat sm c-gold">2m</div>'
                           '<div class="statlab">预计用时</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-blue">3</div>'
                           '<div class="statlab">待复习题</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-rare">+60</div>'
                           '<div class="statlab">可得 XP</div></div></div>', "plain")
                    + "</div>"
                    '<div class="spacer"></div>'
                    + btn("开始重温")
                    + btn("今天先不复习", "ghost"))

    s9 = phone("勋章墙",
               head=nav("勋章墙", right="6 / 18"),
               desc="成就系统，给非每日活跃用户也留一条正反馈路径。",
               title="未解锁勋章保留轮廓与名称，让用户知道还有什么可以追求。",
               body=card('<div class="between"><span class="tiny">已解锁</span>'
                         '<span class="tiny c-gold">6 / 18 枚</span></div>'
                         '<div style="height:10px"></div>' + bar(33, "rare"))
                    + card('<div class="grid4" style="gap:12px">'
                           + "".join('<div style="text-align:center">'
                                     '<div style="display:flex;justify-content:center;'
                                     + ("" if on else "opacity:.3;filter:grayscale(1)") + '">'
                                     + medal(48, kd) + "</div>"
                                     '<div class="tiny" style="margin-top:6px">' + nm + "</div></div>"
                                     for kd, on, nm in [
                                         ("gold", True, "初次启程"), ("gold", True, "五连答对"),
                                         ("rare", True, "百题达成"), ("gold", True, "满分通关"),
                                         ("gold", False, "七日不辍"), ("gold", False, "深夜求知"),
                                         ("gold", False, "卷轴百卷"), ("rare", False, "神秘成就")])
                           + "</div>", "plain")
                    + '<div class="spacer"></div>'
                    + btn("查看全部成就", "ghost"))

    html = doc("04", "冒险者档案",
               "个人中心与后台复盘分析，共 9 屏。这一组回答的是「我坚持了这么久，"
               "到底积累了什么」——用等级、知识树、数据看板把抽象的进步变成可见的形状。"
               "同时落地需求文档里的 P1 能力：结合遗忘曲线的错题复习与后台图表分析。",
               ["冒险者公会卡", "学习数据看板", "知识树可视化",
                "历史卷轴回看", "旧识重温（错题本）", "勋章墙 · 9 屏"],
               grid([s1, s2, s3, s4, s5, s6, s7, s8, s9]))
    w("04-冒险者档案.html", html)


# =====================================================================
# 05 卷轴工坊
# =====================================================================
def build_05():
    s1 = phone("选择输入方式",
               head=nav("卷轴工坊", back=False, right="我的"),
               foot=tabbar(1),
               desc="把「一句话」以外的所有输入源收在一处，主流程不受干扰。",
               title="四种输入方式平铺，不折叠成菜单，降低发现成本。",
               body=card('<div class="row" style="gap:10px;align-items:center">'
                         + shishi("happy", 58) +
                         '<div style="flex:1;min-width:0">'
                         '<div class="h sm">想从哪儿开始？</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '一句话、一份文档、一个网页或一段视频，都能变成知识副本。</div></div></div>', "parch")
                    + card('<div class="row"><span class="badge" style="width:36px;height:36px;font-size:14px">文</span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">一句话 / 一段文本</div>'
                           '<div class="tiny" style="margin-top:3px">最快，AI 会联网补充背景</div></div>'
                           '<span class="tiny">›</span></div>', "plain")
                    + card('<div class="row"><span class="badge" style="width:36px;height:36px;font-size:14px">档</span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">上传文档</div>'
                           '<div class="tiny" style="margin-top:3px">PDF / Word / Markdown / 纯文本</div></div>'
                           '<span class="tiny">›</span></div>', "plain")
                    + card('<div class="row"><span class="badge" style="width:36px;height:36px;font-size:14px">链</span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">网页链接</div>'
                           '<div class="tiny" style="margin-top:3px">自动抓取正文并解析</div></div>'
                           '<span class="tiny">›</span></div>', "plain")
                    + card('<div class="row"><span class="badge" style="width:36px;height:36px;font-size:14px">影</span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">视频链接</div>'
                           '<div class="tiny" style="margin-top:3px">提取字幕生成题目</div></div>'
                           '<span class="tiny">›</span></div>', "plain")
                    + '<div class="spacer"></div>'
                    + '<div class="tiny" style="text-align:center">多源解析为 P1 能力，MVP 首版仅支持文本</div>')

    s2 = phone("上传文档",
               head=nav("上传文档"),
               desc="上传区做足容错提示，格式与大小上限提前说明。",
               title="上传前校验格式与体积，不合规的文件在本地就拦下，不浪费一次网络请求。",
               body='<div class="field" style="flex:1;display:flex;flex-direction:column;align-items:center;'
                    'justify-content:center;gap:12px;border-style:solid;border-width:1.5px">'
                    + scroll_icon(54) +
                    '<div style="font-size:13px;font-weight:600">点击选择或拖入文件</div>'
                    '<div class="tiny" style="text-align:center">支持 PDF / Word / Markdown / TXT<br>单个文件不超过 20MB</div>'
                    "</div>"
                    + card('<div class="tiny" style="margin-bottom:8px">最近上传</div>'
                           + li("PDF", "机器学习导论.pdf", "8.4 MB · 已解析", "使用")
                           + '<div style="height:8px"></div>'
                           + li("DOC", "产品需求文档.docx", "1.2 MB · 已解析", "使用"), "plain")
                    + btn("选择文件"))

    s3 = phone("文档解析中",
               head=nav("解析中", right="取消"),
               bg="#FEFCF6",
               desc="文档解析是耗时操作，必须分阶段可见。",
               title="解析走异步任务，前端按 8 秒间隔轮询，规避小程序 60 秒请求上限。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:18px">'
                    + stage(160, "excited") +
                    '<div style="text-align:center"><div class="h">正在解析文档</div>'
                    '<div class="sub" style="margin-top:6px">机器学习导论.pdf · 8.4 MB</div></div>'
                    + bar(58, "blue", "width:180px") + "</div>"
                    '<div class="spacer"></div>'
                    + card(li("1", "提取正文", "已完成 · 42 页", "完成")
                           + '<div style="height:8px"></div>'
                           + li("2", "切分与向量化", "处理中 · 第 68 / 120 块")
                           + '<div style="height:8px"></div>'
                           + li("3", "存入知识库", "等待中"), "plain"))

    s4 = phone("网页 / 视频链接",
               head=nav("添加链接"),
               desc="链接输入复用卷轴输入框，自动识别类型。",
               title="识别到视频域名时切换为字幕提取模式，并提示预估耗时。",
               body=card('<div class="tiny" style="margin-bottom:8px">粘贴链接</div>'
                         '<div class="field solid" style="background:#FEFCF6">'
                         '<div style="font-size:12.5px;color:#2A2018;line-height:1.6">'
                         'https://example.com/blog/what-is-rag</div></div>'
                         '<div class="row" style="margin-top:10px;gap:6px">'
                         '<span class="pill blue">已识别为网页</span>'
                         '<span class="pill">预计 15 秒</span></div>')
                    + card('<div class="tiny" style="margin-bottom:8px">解析内容预览</div>'
                           '<div class="h sm">什么是 RAG：检索增强生成入门</div>'
                           '<div class="body sm" style="margin-top:6px">'
                           '本文介绍检索增强生成的基本原理，对比它与传统关键词搜索的差异…</div>'
                           '<div class="row" style="margin-top:10px;gap:6px">'
                           '<span class="chip">约 3200 字</span><span class="chip">预计出 5 题</span></div>', "plain")
                    + '<div class="spacer"></div>'
                    + btn("生成知识副本")
                    + '<div class="tiny" style="text-align:center">仅支持公开可访问的页面</div>')

    s5 = phone("知识库列表",
               head=nav("我的知识库", right="新建"),
               desc="RAG 私有知识库，用于企业考核与真题模拟。",
               title="按用户与文档双重隔离，列表展示解析状态，未就绪的库不允许出题。",
               body=card('<div class="row" style="gap:10px;align-items:center">'
                         + momo("happy", 50) +
                         '<div style="flex:1;min-width:0">'
                         '<div class="between"><span class="tiny">共 3 个知识库</span>'
                         '<span class="tiny">已用 12.6 MB</span></div>'
                         '<div style="height:10px"></div>' + bar(42, "blue") + "</div></div>")
                    + li("库", "机器学习导论", "3 份文档 · 已就绪", "出题")
                    + li("库", "产品需求文档", "1 份文档 · 已就绪", "出题")
                    + li("库", "内部考核题库", "2 份文档 · 解析中", "等待")
                    + '<div class="spacer"></div>'
                    + btn("新建知识库", "ghost"))

    s6 = phone("新建知识库",
               head=nav("新建知识库"),
               desc="把一组相关文档收进同一个文件夹，用于批量出题。",
               title="命名与描述都会参与检索，提示用户写清楚主题能提升出题质量。",
               body=card('<div class="tiny" style="margin-bottom:8px">知识库名称</div>'
                         '<div class="field solid" style="background:#FEFCF6">'
                         '<div style="font-size:12.5px;color:#2A2018">机器学习导论</div></div>'
                         '<div class="tiny" style="margin-top:12px;margin-bottom:8px">用途描述（可选）</div>'
                         '<div class="field solid" style="background:#FEFCF6;min-height:64px">'
                         '<div class="ph">例如：用于期末复习，重点关注监督学习部分</div></div>', "plain")
                    + card('<div class="row" style="gap:10px;align-items:flex-start">'
                           + momo("think", 48)
                           + '<div><div class="tiny">写清楚主题和用途</div>'
                           '<div class="body sm" style="margin-top:4px">'
                           'AI 检索时会优先命中相关章节，出题会更贴合你的目标。</div></div></div>', "blue")
                    + '<div class="spacer"></div>'
                    + btn("创建并上传文档")
                    + btn("取消", "ghost"))

    s7 = phone("知识库详情",
               head=nav("机器学习导论", right="设置"),
               desc="单库详情，管理文档与出题范围。",
               title="可指定章节范围出题，这是企业考核场景的核心需求。",
               body=card('<div class="between"><span class="pill ok">已就绪</span>'
                         '<span class="tiny">3 份文档 · 120 个知识块</span></div>'
                         '<div class="h sm" style="margin-top:8px">用于期末复习，重点关注监督学习</div>')
                    + card('<div class="tiny" style="margin-bottom:8px">出题范围</div>'
                           '<div class="row" style="flex-wrap:wrap;gap:6px">'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">全部文档</span>'
                           '<span class="chip">仅第 1-4 章</span><span class="chip">自定义</span></div>', "plain")
                    + li("PDF", "机器学习导论.pdf", "42 页 · 68 块", "已就绪")
                    + li("PDF", "监督学习笔记.pdf", "18 页 · 32 块", "已就绪")
                    + li("DOC", "习题集.docx", "9 页 · 20 块", "已就绪")
                    + '<div class="spacer"></div>'
                    + btn("从本知识库出题", "gold"))

    s8 = phone("从知识库出题",
               head=nav("生成设置"),
               desc="基于私有文档出题，需要比通用出题更多的参数控制。",
               title="题量与难度可选，避免用户拿到一份不合预期的卷轴浪费等待时间。",
               body=card('<div class="tiny" style="margin-bottom:8px">出题来源</div>'
                         '<div class="row" style="gap:9px">' + scroll_icon(26)
                         + '<div><div style="font-size:12.5px;font-weight:600">机器学习导论</div>'
                         '<div class="tiny">3 份文档 · 120 个知识块</div></div></div>', "parch")
                    + card('<div class="tiny" style="margin-bottom:8px">题目数量</div>'
                           '<div class="row" style="gap:6px">'
                           '<span class="chip">3 题</span>'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">5 题</span>'
                           '<span class="chip">10 题</span><span class="chip">自定义</span></div>', "plain")
                    + card('<div class="tiny" style="margin-bottom:8px">难度分布</div>'
                           '<div class="row" style="gap:6px">'
                           '<span class="chip">偏易</span>'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">均衡</span>'
                           '<span class="chip">偏难</span></div>', "plain")
                    + card('<div class="tiny" style="margin-bottom:8px">题型</div>'
                           '<div class="row" style="gap:6px">'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">单选 3</span>'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">多选 1</span>'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">判断 1</span></div>', "plain")
                    + '<div class="spacer"></div>'
                    + btn("生成知识副本"))

    html = doc("05", "卷轴工坊",
               "多源输入与 RAG 私有知识库，共 8 屏。MVP 阶段只有「一句话输入」，"
               "这一组是需求文档 P1 的完整设计——把文档、网页、视频统一抽象成"
               "「卷轴来源」，并为企业考核场景提供私有知识库与出题参数控制。",
               ["文档 / 网页 / 视频解析", "异步解析状态可见", "RAG 私有知识库",
                "出题范围与参数控制", "按用户与文档双重隔离", "8 屏"],
               grid([s1, s2, s3, s4, s5, s6, s7, s8]))
    w("05-卷轴工坊.html", html)


# =====================================================================
# 06 公会社交
# =====================================================================
def peer_row(name, lv, acc, action="邀请"):
    """好友行：身份位用真实头像，右侧是动作。"""
    return ('<div class="li" style="gap:11px">'
            + who(name, lv + " · 正确率 " + acc, size=40)
            + '<span class="pill gold">' + action + "</span></div>")


def rank_row(rank, name, lv, acc, score, me=False):
    col = "#9C6E15" if rank == "1" else "#9A8870"
    return ('<div class="li" style="gap:10px">'
            '<span class="num" style="width:16px;flex:none;font-size:14px;color:' + col
            + '">' + rank + "</span>"
            + who(name, lv + " · 正确率 " + acc, size=38)
            + '<span class="num" style="font-size:14px;color:'
            + ("#9C6E15" if me else "#6B5A45") + '">' + score + "</span></div>")


def build_06():
    s1 = phone("好友 PK 邀请",
               head=nav("公会社交", back=False, right="我的"),
               foot=tabbar(3),
               desc="P2 扩展能力。以同一份题库为基础，邀请好友同场作答。",
               title="PK 复用已有卷轴，不重新出题，保证双方题目完全一致才公平。",
               body=card('<div class="row" style="gap:10px;align-items:center">'
                         + shishi("excited", 58) +
                         '<div style="flex:1;min-width:0">'
                         '<div class="h sm">发起一场知识对决</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '选择一份已有的卷轴，邀请好友同场作答，比正确率也比速度。</div></div></div>', "parch")
                    + card('<div class="between"><span class="tiny">选择对战卷轴</span>'
                           '<span class="tiny c-blue">更换</span></div>'
                           '<div class="row" style="margin-top:10px;gap:9px">' + scroll_icon(26)
                           + '<div><div style="font-size:12.5px;font-weight:600">RAG 入门闯关</div>'
                           '<div class="tiny">5 题 · 约 4 分钟</div></div></div>', "plain")
                    + '<div class="tiny" style="margin-top:2px">邀请好友</div>'
                    + peer_row("阿库娅不想学习", "Lv.5", "78%")
                    + peer_row("惠惠只想放爆裂魔法", "Lv.4", "91%")
                    + peer_row("达克妮丝", "Lv.2", "65%")
                    + '<div class="spacer"></div>'
                    + btn("生成邀请卡片"))

    s2 = phone("等待好友接受",
               head=nav("等待中", right="取消"),
               bg="#FEFCF6",
               desc="邀请发出后的等待态，明确告知超时时间。",
               title="等待期间给出超时兜底：5 分钟未接受自动转为单人练习，不让用户空等。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:16px">'
                    + yuanyuan(130, "drift") +
                    '<div style="text-align:center"><div class="h">邀请已发出</div>'
                    '<div class="body sm" style="margin-top:8px">'
                    '等待「阿库娅不想学习」接受挑战，最长等待 5 分钟。</div></div>'
                    + card('<div class="row" style="justify-content:center;gap:16px">'
                           '<div style="text-align:center"><div class="stat sm c-blue">5</div>'
                           '<div class="statlab">题目数</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-gold">2m</div>'
                           '<div class="statlab">超时后</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-ok">+120</div>'
                           '<div class="statlab">胜者 XP</div></div></div>', "plain")
                    + "</div>"
                    '<div class="spacer"></div>'
                    + btn("再等等")
                    + btn("先自己练一局", "ghost"))

    s3 = phone("对战答题",
               head=nav("知识对决", right="3 / 5"),
               desc="对战模式下额外展示双方进度，其余交互与单人一致。",
               title="只在顶部增加一条对比进度条，不引入倒计时压力，避免破坏学习体验。",
               body='<div class="card plain" style="padding:10px 12px">'
                    '<div class="between" style="margin-bottom:8px">'
                    '<span class="row" style="gap:6px">' + adv_avatar(ME[0], 24)
                    + '<span style="font-size:11.5px;font-weight:600">我 · 3 / 5</span></span>'
                    '<span class="row" style="gap:6px">'
                    '<span style="font-size:11.5px;font-weight:600">阿库娅 · 2 / 5</span>'
                    + adv_avatar(AV_OF["阿库娅不想学习"], 24) + '</span></div>'
                    '<div class="bar blue"><i style="width:60%"></i></div>'
                    '<div style="height:5px"></div>'
                    '<div class="bar"><i style="width:40%;background:#A63A2E"></i></div></div>'
                    + card('<span class="pill">单选题</span>'
                           '<div style="font-size:13.5px;line-height:1.7;margin-top:8px;font-weight:600">'
                           'RAG 与传统关键词检索最核心的差别是什么？</div>', "parch")
                    + opt("A", "先把文档切分成小块再检索")
                    + opt("B", "只在中文语料范围内检索", "sel")
                    + opt("C", "按语义相似度召回相关片段")
                    + opt("D", "完全不依赖大模型生成答案")
                    + '<div class="spacer"></div>'
                    + btn("确认作答"))

    s4 = phone("对战结算",
               head=nav("对决结果"),
               bg="#FEFCF6",
               desc="胜负之外，强调双方都学到了什么。",
               title="输的一方同样给出进步反馈与 XP，避免 PK 变成劝退机制。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:12px">'
                    + shishi("win", 108) +
                    '<div style="font-size:20px;font-weight:700;margin-top:4px">你赢了这场对决</div>'
                    '<div class="sub">5 : 4 · 用时 3 分 12 秒</div></div>'
                    + card('<div class="between">' + who(ME[1], size=34) +
                           '<span style="font-size:12.5px;font-weight:600;color:#2F7D4F">答对 5 题</span></div>'
                           '<div style="height:8px"></div>' + bar(100, "ok")
                           + '<div style="height:14px"></div>'
                           '<div class="between">' + who("阿库娅不想学习", size=34) +
                           '<span style="font-size:12.5px;font-weight:600;color:#9A8870">答对 4 题</span></div>'
                           '<div style="height:8px"></div>'
                           + '<div class="bar"><i style="width:80%;background:#A63A2E"></i></div>', "plain")
                    + card('<div class="row" style="justify-content:center;gap:18px">'
                           '<div style="text-align:center"><div class="stat sm c-gold">+120</div>'
                           '<div class="statlab">胜场 XP</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-blue">+1</div>'
                           '<div class="statlab">连胜</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-ok">2</div>'
                           '<div class="statlab">本局提升</div></div></div>', "gold")
                    + '<div class="spacer"></div>'
                    + btn("再来一局")
                    + btn("查看复盘报告", "ghost"))

    s5 = phone("排行榜",
               head=nav("知识排行榜", right="全部"),
               desc="按知识领域划分的全服榜单，只在 P2 阶段上线。",
               title="排行榜按领域分榜，避免单一总榜被高频用户长期占据而失去激励意义。",
               body='<div class="row" style="gap:6px;flex-wrap:wrap">'
                    '<span class="chip" style="background:#2F6BD8;color:#fff;border-color:#2F6BD8">本周</span>'
                    '<span class="chip">本月</span><span class="chip">AI 基础</span>'
                    '<span class="chip">RAG</span></div>'
                    + card('<div class="row" style="gap:11px">'
                           '<span class="badge" style="width:34px;height:34px;font-size:15px">1</span>'
                           + who("惠惠只想放爆裂魔法", "Lv.4 · 正确率 91%", size=38)
                           + '<span class="num c-gold" style="font-size:15px">2480</span></div>', "gold")
                    + rank_row("2", "达克妮丝", "Lv.2", "65%", "2110")
                    + rank_row("3", "阿库娅不想学习", "Lv.5", "78%", "1980")
                    + rank_row("4", "冒险者 · 拾光（我）", "Lv.3", "83%", "1840", me=True)
                    + rank_row("5", "和真", "Lv.3", "70%", "1620")
                    + '<div class="spacer"></div>'
                    + '<div class="tiny" style="text-align:center">本周还剩 3 天 · 继续加油</div>')

    s6 = phone("分享邀请卡片",
               head=nav("分享", right="保存"),
               bg="#FEFCF6",
               desc="社交裂变的最小单元，一张可转发的挑战卡。",
               title="卡片不展示被邀请人的数据，降低隐私顾虑，提升转发意愿。",
               body=card('<div style="text-align:center;padding:12px 8px">'
                         '<div class="tiny">知拾冒险社 · 知识对决</div>'
                         '<div style="display:flex;justify-content:center;margin-top:6px">'
                         + yuanyuan(88) + "</div>"
                         '<div style="font-size:18px;font-weight:700;margin-top:8px;line-height:1.5">'
                         '我在「RAG 入门」拿了 5 分，<br>你敢来比一场吗？</div>'
                         '<div style="height:18px"></div>'
                         '<div class="row" style="justify-content:center;gap:10px">'
                         + adv_avatar(ME[0], 46)
                         + '<span style="font-size:14px;font-weight:700;color:#9A8870">VS</span>'
                         + avatar_blank(46) + "</div>"
                         '<div class="tiny" style="margin-top:12px">5 题 · 约 4 分钟 · 即时出结果</div>'
                         '<div style="height:16px"></div>'
                         '<div style="height:1px;background:#EADFC4"></div>'
                         '<div class="row" style="justify-content:center;margin-top:14px;gap:10px">'
                         '<div style="width:52px;height:52px;border-radius:10px;background:#F5EDD8;'
                         'border:1px solid #D9C6A4"></div>'
                         '<div style="text-align:left"><div style="font-size:11.5px;font-weight:600">'
                         '长按识别应战</div>'
                         '<div class="tiny" style="margin-top:3px">拾万千知识，闯无尽关卡</div></div>'
                         "</div></div>", "plain")
                    + '<div class="spacer"></div>'
                    + btn("分享给微信好友")
                    + btn("保存到相册", "ghost"))

    html = doc("06", "公会社交",
               "社交对战与排行榜，共 6 屏，属于需求文档的 P2 扩展能力。"
               "这一组在当前「中度游戏化」的设定下不进 MVP，"
               "但先把设计做出来，等核心闭环验证稳定后可以直接接上。"
               "设计上刻意压低竞争感：PK 复用同一份题库保证公平，输的一方同样拿到成长反馈。",
               ["好友 PK 邀请", "同题库保证公平", "对战进度对比",
                "胜负双方均有反馈", "按领域分榜", "P2 扩展预留 · 6 屏"],
               grid([s1, s2, s3, s4, s5, s6]))
    w("06-公会社交.html", html)


# =====================================================================
# 07 会员与设置
# =====================================================================
def build_07():
    s1 = phone("会员权益",
               head=nav("冒险者通行证"),
               bg="#FEFCF6",
               desc="商业化入口。权益描述必须具体，避免空泛的「尊享」话术。",
               title="权益按使用频次排序，把用户最可能用到的放在最前面。",
               body=card('<div class="row" style="gap:12px">'
                         + tongbao(66) +
                         '<div><div style="font-size:15px;font-weight:700">冒险者通行证</div>'
                         '<div class="tiny" style="margin-top:4px">解锁完整 AI 能力，学习不再受限</div></div></div>', "gold")
                    + card('<div class="row"><span class="dotmark gold"></span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">无限次召唤副本</div>'
                           '<div class="tiny" style="margin-top:3px">免费版每天 3 次，会员不限次数</div></div></div>')
                    + card('<div class="row"><span class="dotmark gold"></span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">私有知识库扩容至 1 GB</div>'
                           '<div class="tiny" style="margin-top:3px">免费版 50 MB，适合企业考核与真题模拟</div></div></div>')
                    + card('<div class="row"><span class="dotmark gold"></span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">深度复盘报告</div>'
                           '<div class="tiny" style="margin-top:3px">包含知识点归因与个性化复习计划</div></div></div>')
                    + card('<div class="row"><span class="dotmark gold"></span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">题目配图与语音讲解</div>'
                           '<div class="tiny" style="margin-top:3px">多模态能力，学得更直观</div></div></div>')
                    + '<div class="spacer"></div>'
                    + btn("查看套餐", "gold"))

    s2 = phone("套餐对比",
               head=nav("选择套餐"),
               desc="三档套餐并排，推荐档位用描边强调而不是放大。",
               title="默认选中性价比最高的一档，同时保留月付入口降低决策门槛。",
               body='<div class="grid3" style="gap:8px">'
                    + card('<div style="text-align:center"><div class="tiny">月付</div>'
                           '<div class="stat sm" style="margin-top:6px">18</div>'
                           '<div class="tiny">元 / 月</div></div>', "plain")
                    + card('<div style="text-align:center"><div class="tiny c-gold">年付 · 推荐</div>'
                           '<div class="stat sm c-gold" style="margin-top:6px">128</div>'
                           '<div class="tiny">元 / 年</div></div>', "gold")
                    + card('<div style="text-align:center"><div class="tiny">永久</div>'
                           '<div class="stat sm" style="margin-top:6px">398</div>'
                           '<div class="tiny">元 一次性</div></div>', "plain")
                    + "</div>"
                    + card('<div class="between"><span class="tiny">年付相当于</span>'
                           '<span class="pill gold">每月 10.7 元 · 省 41%</span></div>')
                    + card('<div class="tiny" style="margin-bottom:8px">套餐包含</div>'
                           '<div class="stack tight">'
                           '<div class="row"><span class="pill ok">✓</span><span class="body sm">无限次召唤副本</span></div>'
                           '<div class="row"><span class="pill ok">✓</span><span class="body sm">私有知识库 1 GB</span></div>'
                           '<div class="row"><span class="pill ok">✓</span><span class="body sm">深度复盘报告</span></div>'
                           '<div class="row"><span class="pill ok">✓</span><span class="body sm">多模态配图与语音</span></div>'
                           "</div>", "plain")
                    + '<div class="spacer"></div>'
                    + btn("立即开通 · 128 元", "gold")
                    + '<div class="tiny" style="text-align:center">开通后 7 天内可申请退款</div>')

    s3 = phone("支付确认",
               head=nav("确认订单"),
               desc="支付前把商品、金额、有效期一次说清。",
               title="金额用等宽字体加粗，与微信支付收银台的视觉习惯保持一致。",
               body=card('<div class="between"><span class="tiny">商品</span>'
                         '<span style="font-size:12.5px;font-weight:600">冒险者通行证 · 年付</span></div>'
                         '<div style="height:12px"></div>'
                         '<div class="between"><span class="tiny">有效期</span>'
                         '<span style="font-size:12.5px">2026-09-14 至 2027-09-14</span></div>'
                         '<div style="height:12px"></div>'
                         '<div class="between"><span class="tiny">支付方式</span>'
                         '<span style="font-size:12.5px">微信支付</span></div>', "plain")
                    + card('<div class="between"><span class="tiny">应付金额</span>'
                           '<span class="stat sm c-gold">128.00 元</span></div>', "gold")
                    + '<div class="spacer"></div>'
                    + btn("微信支付 128.00 元", "gold")
                    + '<div class="tiny" style="text-align:center">'
                    '点击即表示同意《会员服务协议》与《自动续费规则》</div>')

    s4 = phone("支付成功",
               head=nav("支付结果"),
               bg="#FEFCF6",
               desc="支付成功后的即时反馈与下一步引导。",
               title="成功页不设自动跳转，停留 3 秒后由用户决定去留，避免打断阅读。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:14px">'
                    + tongbao(118) +
                    '<div style="text-align:center"><div class="h">开通成功</div>'
                    '<div class="body sm" style="margin-top:8px">'
                    '冒险者通行证已生效，有效期至 2027-09-14。</div></div>'
                    + card('<div class="between"><span class="tiny">订单号</span>'
                           '<span class="tiny">202609142038110002</span></div>', "plain")
                    + "</div>"
                    '<div class="spacer"></div>'
                    + btn("立即召唤一个副本")
                    + btn("返回个人中心", "ghost"))

    s5 = phone("设置",
               head=nav("设置"),
               foot=tabbar(4),
               desc="设置项按使用频率排序，把账号相关放在最下方。",
               title="所有开关状态用颜色加位置双重表达，不只依赖颜色。",
               body=li("铃", "学习提醒", "每天 20:00 提醒我复习", "已开")
                    + li("音", "音效与振动", "答对答错的即时反馈", "已开")
                    + li("存", "流量下自动加载配图", "关闭可节省流量", "已关")
                    + li("护", "护眼模式", "降低羊皮纸底亮度", "已关")
                    + li("清", "清理缓存", "当前占用 12.6 MB", "清理")
                    + li("账", "账号与安全", "微信已绑定", "")
                    + li("问", "帮助与反馈", "常见问题与意见反馈", "")
                    + li("版", "关于知拾冒险社", "版本 1.0.0", ""))

    s6 = phone("学习提醒设置",
               head=nav("学习提醒"),
               desc="留存的关键设置项，默认开启但必须可关闭。",
               title="提醒时间默认 20:00，覆盖下班后的学习高峰；支持按星期自定义。",
               body=card('<div class="between"><span style="font-size:12.5px;font-weight:600">每日学习提醒</span>'
                         '<span class="pill ok">已开启</span></div>'
                         '<div class="row" style="gap:10px;align-items:flex-start;margin-top:8px">'
                         + yuanyuan(58)
                         + '<div class="body sm">'
                         '每天在你设定的时间提醒你来社团大厅，避免连续记录中断。</div></div>', "parch")
                    + card('<div class="tiny" style="margin-bottom:10px">提醒时间</div>'
                           '<div class="row" style="gap:6px;flex-wrap:wrap">'
                           '<span class="chip">08:00</span><span class="chip">12:30</span>'
                           '<span class="chip" style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8">20:00</span>'
                           '<span class="chip">22:00</span></div>', "plain")
                    + card('<div class="tiny" style="margin-bottom:10px">提醒日</div>'
                           '<div class="row" style="gap:6px">'
                           + "".join('<span class="chip"' + (' style="background:#DCE9FB;color:#1F4694;border-color:#7FA9D8"' if d in "一二三四五" else "") + '>' + d + "</span>"
                                     for d in "一二三四五六日")
                           + "</div>", "plain")
                    + card('<div class="tiny" style="margin-bottom:10px">额外提醒</div>'
                           + '<div class="between"><span class="body sm">连续记录即将中断时提醒</span>'
                           '<span class="pill ok">开</span></div>'
                           '<div style="height:10px"></div>'
                           + '<div class="between"><span class="body sm">旧识重温到期时提醒</span>'
                           '<span class="pill ok">开</span></div>', "plain")
                    + '<div class="spacer"></div>'
                    + btn("保存设置"))

    s7 = phone("空态合集",
               head=nav("空态与异常"),
               desc="同一屏并列展示三种空态，用于设计评审对照。",
               title="三种空态都遵循同一结构：状态图标 + 一句解释 + 一个明确动作。",
               body=card('<div style="text-align:center;padding:8px 0">'
                         + '<div style="display:flex;justify-content:center">' + shishi("happy", 74) + "</div>"
                         '<div class="h sm" style="margin-top:8px">还没有冒险卷轴</div>'
                         '<div class="tiny" style="margin-top:6px">去社团大厅领取你的第一张卷轴吧</div>'
                         '<div style="height:12px"></div>' + btn("去社团大厅", "sm") + "</div>", "plain")
                    + card('<div style="text-align:center;padding:8px 0">'
                           + '<div style="display:flex;justify-content:center">' + shishi("think", 74) + "</div>"
                           '<div class="h sm" style="margin-top:8px">还没有上传文档</div>'
                           '<div class="tiny" style="margin-top:6px">上传一份资料，AI 会把它变成题库</div>'
                           '<div style="height:12px"></div>' + btn("上传文档", "sm ghost") + "</div>", "plain")
                    + card('<div style="text-align:center;padding:8px 0">'
                           + '<div style="display:flex;justify-content:center">' + shishi("sad", 74) + "</div>"
                           '<div class="h sm" style="margin-top:8px">网络好像断开了</div>'
                           '<div class="tiny" style="margin-top:6px">已下载的日志仍可查看</div>'
                           '<div style="height:12px"></div>' + btn("重新连接", "sm ghost") + "</div>", "plain"))

    s8 = phone("帮助与反馈",
               head=nav("帮助与反馈"),
               desc="兜底页面。AI 产品必须让用户能找到人。",
               title="把「题目有问题」单独列一条，这是 AI 出题类产品最高频的反馈类型。",
               body=card('<div class="h sm">常见问题</div>')
                    + li("问", "为什么生成的题目不太准？", "补充背景资料可以显著提升质量", "查看")
                    + li("问", "免费版每天能生成几次？", "每天 3 次，会员不限次数", "查看")
                    + li("问", "上传的文档安全吗？", "按用户隔离，不会用于训练", "查看")
                    + card('<div class="row"><span class="badge" style="width:32px;height:32px;font-size:13px">!</span>'
                           '<div style="flex:1"><div style="font-size:12.5px;font-weight:600">举报题目问题</div>'
                           '<div class="tiny" style="margin-top:3px">题干有误、答案错误或内容不适</div></div>'
                           '<span class="tiny">›</span></div>', "bad")
                    + li("邮", "联系开发者", "工作日 24 小时内回复", "发信")
                    + '<div class="spacer"></div>'
                    + '<div class="tiny" style="text-align:center">知拾冒险社 v1.0.0 · 拾万千知识，闯无尽关卡</div>')

    html = doc("07", "会员与设置",
               "商业化闭环与系统设置，共 8 屏。这一组对应需求文档的 P3 阶段，"
               "同时补齐了产品必须有的兜底页面。商业化设计的原则是："
               "权益写得具体、价格讲得清楚、退路留得明白——AI 产品的付费转化，"
               "建立在用户已经认可出题质量之后，而不是靠话术。",
               ["会员权益与套餐", "支付与结果页", "设置与提醒",
                "空态合集", "帮助与反馈", "P3 扩展 · 8 屏"],
               grid([s1, s2, s3, s4, s5, s6, s7, s8]))
    w("07-会员与设置.html", html)


if __name__ == "__main__":
    print("generating 04-07 ...")
    build_04()
    build_05()
    build_06()
    build_07()
    print("done.")
