"""一次性把 SVG 卡通形象接入所有页面。每处替换都要求唯一命中，否则报错。"""
import io
import sys

PA = []


def a(old, new):
    PA.append((old, new))


# ---------------- 00 设计规范：新增形象章节 ----------------
a("""    body = (sec("色彩系统", "整套配色分两层：羊皮纸层承担阅读，魔法色层承担情绪与操作。\"""",
  """    sprites = ('<div class="ds-row">'
               + "".join('<div style="text-align:center">'
                         '<div style="background:#FDF8EF;border:1px solid #E3D5BC;border-radius:16px;'
                         'padding:10px;display:flex;justify-content:center;width:96px">'
                         + shishi(st, 74, "") + "</div>"
                         '<div class="tiny" style="margin-top:6px">' + nm + "</div></div>"
                         for st, nm in [("normal", "默认"), ("happy", "开心"), ("excited", "兴奋"),
                                        ("win", "通关"), ("think", "思考"), ("sad", "失落"),
                                        ("sleep", "空态"), ("dizzy", "异常")])
               + '<div style="display:flex;flex-direction:column;align-items:center;gap:10px;'
                 'background:#FDF8EF;border:1px solid #E3D5BC;border-radius:16px;padding:14px">'
               + stage(150, "happy") + '<div class="tiny">法阵舞台 · 生成态</div></div>'
               + spec("形象使用规范", [
                   "精灵全站只用一个角色，通过表情而非换角色来表达状态",
                   "默认态带 3.4s 上下浮动动画，生成态加快到 2.2s",
                   "尺寸只用三档：卡片内 46-56px、空态 72-96px、舞台 100px 以上",
                   "全部为 SVG 路径，无位图依赖，任意尺寸不失真",
                   "开启系统减少动效偏好时，所有浮动与闪烁动画自动关闭",
               ])
               + "</div>")
            + sec("引导精灵「拾拾」", "产品的引导 IP，也是唯一贯穿全部页面的角色。"
                                     "水蓝色小精灵造型，表情随场景切换：生成中兴奋、答对开心、"
                                     "空态入睡、异常时眩晕。道具（金币、宝箱、勋章、卷轴）同属一套线性语言。",
                sprites)
            + sec("色彩系统", "整套配色分两层：羊皮纸层承担阅读，魔法色层承担情绪与操作。\"""")

# ---------------- 01 核心闭环 ----------------
a("""               + magic(124) +
               '<div style="text-align:center"><div style="font-size:20px;font-weight:700">知拾冒险社</div>'""",
  """               + stage(176, "happy") +
               '<div style="text-align:center"><div style="font-size:20px;font-weight:700">知拾冒险社</div>'""")

a("""               card('<div class="row"><div class="avatar"></div>'
                    '<div><div class="h sm">冒险者，欢迎回到社团大厅</div>'
                    '<div class="sub" style="margin-top:3px">今天想拾取哪一块知识？</div></div></div>')
               + '<div class="field" style="flex:1;display:flex;flex-direction:column;justify-content:space-between">'
                 '<div class="ph">说出你想学的任何知识…<br>一句话 / 一段文字 / 一个网址 / 一份文档</div>'
                 '<div class="tiny" style="text-align:right">0 / 200</div></div>'""",
  """               card(corners() + '<div class="row"><div style="flex:none">'
                    + shishi("happy", 46, "floaty fast") + "</div>"
                    '<div><div class="h sm">冒险者，欢迎回到社团大厅</div>'
                    '<div class="sub" style="margin-top:3px">今天想拾取哪一块知识？</div></div></div>', "rel")
               + scrollbox('<div class="ph">说出你想学的任何知识…<br>一句话 / 一段文字 / 一个网址 / 一份文档</div>'
                           '<div class="tiny" style="text-align:right">0 / 200</div>', grow=True)""")

a("""               card('<div class="row"><div class="avatar"></div>'
                    '<div><div class="h sm">冒险者，欢迎回到社团大厅</div>'
                    '<div class="sub" style="margin-top:3px">今天想拾取哪一块知识？</div></div></div>')
               + '<div class="field solid" style="flex:1;display:flex;flex-direction:column;justify-content:space-between;background:#FFFFFF">'
                 '<div style="font-size:12.5px;line-height:1.75;color:#3A2E22">'
                 '我想学习什么是 RAG，以及它和传统搜索有什么区别</div>'
                 '<div class="between"><span class="pill blue">AI 将联网补充</span>'
                 '<span class="tiny">28 / 200</span></div></div>'""",
  """               card(corners() + '<div class="row"><div style="flex:none">'
                    + shishi("think", 46, "floaty fast") + "</div>"
                    '<div><div class="h sm">冒险者，欢迎回到社团大厅</div>'
                    '<div class="sub" style="margin-top:3px">今天想拾取哪一块知识？</div></div></div>', "rel")
               + scrollbox('<div style="font-size:12.5px;line-height:1.75;color:#3A2E22">'
                           '我想学习什么是 RAG，以及它和传统搜索有什么区别</div>'
                           '<div class="between"><span class="pill blue">AI 将联网补充</span>'
                           '<span class="tiny">28 / 200</span></div>', grow=True)""")

a("""                    + magic(124) +
                    '<div style="text-align:center"><div class="h">正在生成知识副本</div>'""",
  """                    + stage(176, "excited") +
                    '<div style="text-align:center"><div class="h">正在生成知识副本</div>'""")

a("""               body=card('<div class="between"><span class="pill blue">知识副本</span>'
                         '<span class="tiny">约 4 分钟</span></div>'
                         '<div class="h" style="margin-top:8px">RAG 入门闯关</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '围绕 RAG 的基础定义、检索原理与应用场景生成的题库。</div>')""",
  """               body=card('<div class="row" style="align-items:flex-start;gap:10px">'
                         + shishi("happy", 56, "floaty") +
                         '<div style="flex:1;min-width:0">'
                         '<div class="between"><span class="pill blue">知识副本</span>'
                         '<span class="tiny">约 4 分钟</span></div>'
                         '<div class="h" style="margin-top:6px">RAG 入门闯关</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '围绕 RAG 的基础定义、检索原理与应用场景生成的题库。</div></div></div>')""")

a("""                    + magic(96) +
                    '<div style="text-align:center"><div style="font-size:22px;font-weight:700">副本通关</div>'""",
  """                    + stage(150, "win") +
                    '<div style="text-align:center"><div style="font-size:22px;font-weight:700">副本通关</div>'""")

# ---------------- 02 挑战副本 ----------------
a("""                    + card('<div class="between"><span style="font-size:12.5px;font-weight:600;color:#1E5C3A">'
                           '答对了 · +40 XP</span><span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:8px">'
                           'RAG 会先把文档切成小块并转成向量，检索时按语义相似度召回，'
                           '所以它能理解「意思」而不只是匹配关键词。</div>', "ok grow"))""",
  """                    + card('<div class="row" style="align-items:flex-start;gap:10px">'
                           + shishi("happy", 50, "floaty fast") +
                           '<div style="flex:1;min-width:0">'
                           '<div class="between"><span style="font-size:12.5px;font-weight:600;color:#1E5C3A">'
                           '答对了 · +40 XP</span><span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           'RAG 会先把文档切成小块并转成向量，检索时按语义相似度召回，'
                           '所以它能理解「意思」而不只是匹配关键词。</div></div></div>', "ok grow"))""")

a("""                    + card('<div class="between"><span style="font-size:12.5px;font-weight:600" class="c-bad">'
                           '正确答案是 C</span><span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:8px">'
                           'B 错在把 RAG 当成语言限制。RAG 的核心是「先检索再生成」，'
                           '靠向量相似度找到相关片段，与语种无关。</div>', "bad grow"))""",
  """                    + card('<div class="row" style="align-items:flex-start;gap:10px">'
                           + shishi("think", 50, "floaty fast") +
                           '<div style="flex:1;min-width:0">'
                           '<div class="between"><span style="font-size:12.5px;font-weight:600" class="c-bad">'
                           '正确答案是 C</span><span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           'B 错在把 RAG 当成语言限制。RAG 的核心是「先检索再生成」，'
                           '靠向量相似度找到相关片段，与语种无关。</div></div></div>', "bad grow"))""")

a("""                    + card('<div class="between"><span style="font-size:12.5px;font-weight:600" class="c-gold">'
                           '部分正确 · +30 XP</span><span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:8px">'
                           '正确答案是 A、C、D。多选按比例计分，选对 3 项中的 2 项，'
                           '拿到一半经验值。B 错在速度并非 RAG 的优势。</div>', "gold grow"))""",
  """                    + card('<div class="row" style="align-items:flex-start;gap:10px">'
                           + shishi("think", 50, "floaty fast") +
                           '<div style="flex:1;min-width:0">'
                           '<div class="between"><span style="font-size:12.5px;font-weight:600" class="c-gold">'
                           '部分正确 · +30 XP</span><span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           '正确答案是 A、C、D。多选按比例计分，选对 3 项中的 2 项，'
                           '拿到一半经验值。B 错在速度并非 RAG 的优势。</div></div></div>', "gold grow"))""")

a("""               foot='<div class="mask"><div class="card plain" style="width:100%;padding:18px">'
                    '<div class="h">要离开这个副本吗？</div>'""",
  """               foot='<div class="mask"><div class="card plain" style="width:100%;padding:18px;text-align:center">'
                    + shishi("think", 76, "floaty") +
                    '<div class="h" style="margin-top:10px">要离开这个副本吗？</div>'""")

a("""                    + magic(110) +
                    '<div style="text-align:center"><div class="h">正在撰写冒险日志</div>'""",
  """                    + stage(160, "excited") +
                    '<div style="text-align:center"><div class="h">正在撰写冒险日志</div>'""")

# ---------------- 03 冒险日志 ----------------
a("""                    + card('<div class="between"><span style="font-size:12.5px;font-weight:600">'
                           '本局超过社团里 72% 的冒险者</span><span class="pill ok">中上</span></div>'
                           '<div style="height:10px"></div>' + bar(72, "ok"), "plain")""",
  """                    + card('<div class="row" style="gap:10px">' + shishi("happy", 52, "floaty")
                           + '<div style="flex:1;min-width:0">'
                           '<div class="between"><span style="font-size:12.5px;font-weight:600">'
                           '本局超过社团里 72% 的冒险者</span><span class="pill ok">中上</span></div>'
                           '<div style="height:10px"></div>' + bar(72, "ok") + "</div></div>", "plain")""")

a("""               body=card('<div class="tiny" style="margin-bottom:10px">三句话知识总结</div>'
                         '<div class="stack">'""",
  """               body=card('<div class="row" style="justify-content:space-between;align-items:flex-start">'
                         '<span class="tiny">三句话知识总结</span>'
                         + shishi("happy", 46, "floaty fast") + "</div>"
                         '<div class="stack" style="margin-top:6px">'""")

a("""                         '<div class="tiny">知拾冒险社 · 冒险日志</div>'
                         '<div style="font-size:19px;font-weight:700;line-height:1.55;margin-top:16px">'""",
  """                         '<div class="tiny">知拾冒险社 · 冒险日志</div>'
                         '<div style="display:flex;justify-content:center;margin-top:6px">'
                         + shishi("win", 86, "floaty") + "</div>"
                         '<div style="font-size:19px;font-weight:700;line-height:1.55;margin-top:8px">'""")

a("""                    + magic(100) +
                    '<div class="h">正在绘制分享海报</div>'""",
  """                    + stage(150, "excited") +
                    '<div class="h">正在绘制分享海报</div>'""")

a("""                    '<div class="badge" style="background:#FDECEC;border-color:#E5484D;color:#E5484D;'
                    'width:56px;height:56px;font-size:22px">!</div>'
                    '<div style="text-align:center"><div class="h">报告生成失败</div>'""",
  """                    + shishi("dizzy", 96, "floaty") +
                    '<div style="text-align:center"><div class="h">报告生成失败</div>'""")

a("""                    '<div class="avatar" style="width:64px;height:64px;background:#F3EADA;border-color:#E3D5BC"></div>'
                    '<div style="text-align:center"><div class="h">网络好像断开了</div>'""",
  """                    + shishi("sad", 96, "floaty") +
                    '<div style="text-align:center"><div class="h">网络好像断开了</div>'""")

a("""                    + '<div class="spacer"></div>'
                    + '<div class="tiny" style="text-align:center">已经到底了 · 共 12 份日志</div>')""",
  """                    + '<div class="spacer"></div>'
                    + '<div style="display:flex;flex-direction:column;align-items:center;gap:6px">'
                    + shishi("sleep", 64, "floaty slow")
                    + '<div class="tiny">已经到底了 · 共 12 份日志</div></div>')""")

PB = []


def b(old, new):
    PB.append((old, new))


# ---------------- 04 冒险者档案 ----------------
b("""               body=card('<div class="row" style="gap:12px"><div class="avatar gold" style="width:52px;height:52px"></div>'
                         '<div style="flex:1"><div style="font-size:15px;font-weight:600">冒险者 · 拾光</div>'""",
  """               body=card('<div class="row" style="gap:12px">'
                         + shishi("happy", 58, "floaty fast") +
                         '<div style="flex:1"><div style="font-size:15px;font-weight:600">冒险者 · 拾光</div>'""")

b("""                         '<div class="avatar gold" style="width:64px;height:64px;margin:0 auto"></div>'
                         '<div style="font-size:17px;font-weight:700;margin-top:12px">冒险者 · 拾光</div>'""",
  """                         '<div style="display:flex;justify-content:center">' + shishi("win", 88, "floaty") + "</div>"
                         '<div style="font-size:17px;font-weight:700;margin-top:6px">冒险者 · 拾光</div>'""")

b("""                    + btn("点亮新领域", "gold"))""",
  """                    + '<div class="row" style="justify-content:center">' + shishi("think", 60, "floaty") + "</div>"
                    + btn("点亮新领域", "gold"))""")

b("""               body=card('<div class="between"><span class="tiny">待复习错题</span>'
                         '<span class="pill bad">3 题到期</span></div>'
                         '<div class="body sm" style="margin-top:8px">'
                         '按艾宾浩斯遗忘曲线，这 3 道题今天最适合重做，'
                         '此时回忆的成本最低、效果最好。</div>', "parch")""",
  """               body=card('<div class="row" style="gap:10px;align-items:flex-start">'
                         + shishi("think", 54, "floaty fast") +
                         '<div style="flex:1;min-width:0">'
                         '<div class="between"><span class="tiny">待复习错题</span>'
                         '<span class="pill bad">3 题到期</span></div>'
                         '<div class="body sm" style="margin-top:8px">'
                         '按艾宾浩斯遗忘曲线，这 3 道题今天最适合重做，'
                         '此时回忆的成本最低、效果最好。</div></div></div>', "parch")""")

b("""                    + magic(96) +
                    '<div style="text-align:center"><div class="h">你有 3 道旧识在等你</div>'""",
  """                    + stage(150, "happy") +
                    '<div style="text-align:center"><div class="h">你有 3 道旧识在等你</div>'""")

b("""                    + card('<div class="grid4" style="gap:12px">'
                           '<div style="text-align:center"><div class="badge" style="margin:0 auto">1</div>'
                           '<div class="tiny" style="margin-top:6px">初次启程</div></div>'
                           '<div style="text-align:center"><div class="badge" style="margin:0 auto">5</div>'
                           '<div class="tiny" style="margin-top:6px">五连答对</div></div>'
                           '<div style="text-align:center"><div class="badge rare" style="margin:0 auto">百</div>'
                           '<div class="tiny" style="margin-top:6px">百题达成</div></div>'
                           '<div style="text-align:center"><div class="badge" style="margin:0 auto">满</div>'
                           '<div class="tiny" style="margin-top:6px">满分通关</div></div>'
                           '<div style="text-align:center"><div class="badge off" style="margin:0 auto">7</div>'
                           '<div class="tiny" style="margin-top:6px">七日不辍</div></div>'
                           '<div style="text-align:center"><div class="badge off" style="margin:0 auto">夜</div>'
                           '<div class="tiny" style="margin-top:6px">深夜求知</div></div>'
                           '<div style="text-align:center"><div class="badge off" style="margin:0 auto">师</div>'
                           '<div class="tiny" style="margin-top:6px">卷轴百卷</div></div>'
                           '<div style="text-align:center"><div class="badge off" style="margin:0 auto">?</div>'
                           '<div class="tiny" style="margin-top:6px">神秘成就</div></div>'
                           "</div>", "plain")""",
  """                    + card('<div class="grid4" style="gap:12px">'
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
                           + "</div>", "plain")""")

# ---------------- 05 卷轴工坊 ----------------
b("""               body=card('<div class="h sm">想从哪儿开始？</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '一句话、一份文档、一个网页或一段视频，都能变成知识副本。</div>', "parch")""",
  """               body=card('<div class="row" style="gap:10px;align-items:center">'
                         + shishi("happy", 58, "floaty fast") +
                         '<div style="flex:1;min-width:0">'
                         '<div class="h sm">想从哪儿开始？</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '一句话、一份文档、一个网页或一段视频，都能变成知识副本。</div></div></div>', "parch")""")

b("""                    '<div class="badge" style="width:52px;height:52px;font-size:18px">+</div>'
                    '<div style="font-size:13px;font-weight:600">点击选择或拖入文件</div>'""",
  """                    + scroll_icon(54) +
                    '<div style="font-size:13px;font-weight:600">点击选择或拖入文件</div>'""")

b("""                    + magic(112) +
                    '<div style="text-align:center"><div class="h">正在解析文档</div>'""",
  """                    + stage(160, "excited") +
                    '<div style="text-align:center"><div class="h">正在解析文档</div>'""")

b("""               body=card('<div class="between"><span class="tiny">共 3 个知识库</span>'
                         '<span class="tiny">已用 12.6 MB</span></div>'
                         '<div style="height:10px"></div>' + bar(42, "blue"))""",
  """               body=card('<div class="row" style="gap:10px;align-items:center">'
                         + shishi("happy", 50, "floaty fast") +
                         '<div style="flex:1;min-width:0">'
                         '<div class="between"><span class="tiny">共 3 个知识库</span>'
                         '<span class="tiny">已用 12.6 MB</span></div>'
                         '<div style="height:10px"></div>' + bar(42, "blue") + "</div></div>")""")

# ---------------- 06 公会社交 ----------------
b("""               body=card('<div class="h sm">发起一场知识对决</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '选择一份已有的卷轴，邀请好友同场作答，比正确率也比速度。</div>', "parch")""",
  """               body=card('<div class="row" style="gap:10px;align-items:center">'
                         + shishi("excited", 58, "floaty fast") +
                         '<div style="flex:1;min-width:0">'
                         '<div class="h sm">发起一场知识对决</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '选择一份已有的卷轴，邀请好友同场作答，比正确率也比速度。</div></div></div>', "parch")""")

b("""                    + magic(104) +
                    '<div style="text-align:center"><div class="h">邀请已发出</div>'""",
  """                    + stage(155, "happy") +
                    '<div style="text-align:center"><div class="h">邀请已发出</div>'""")

b("""                    '<div class="badge" style="width:72px;height:72px;font-size:24px">胜</div>'
                    '<div style="font-size:20px;font-weight:700">你赢了这场对决</div>'""",
  """                    + shishi("win", 108, "floaty") +
                    '<div style="font-size:20px;font-weight:700;margin-top:4px">你赢了这场对决</div>'""")

b("""                         '<div class="tiny">知拾冒险社 · 知识对决</div>'
                         '<div style="font-size:18px;font-weight:700;margin-top:16px;line-height:1.5">'""",
  """                         '<div class="tiny">知拾冒险社 · 知识对决</div>'
                         '<div style="display:flex;justify-content:center;margin-top:6px">'
                         + shishi("win", 78, "floaty") + "</div>"
                         '<div style="font-size:18px;font-weight:700;margin-top:8px;line-height:1.5">'""")

# ---------------- 07 会员与设置 ----------------
b("""               body=card('<div class="row" style="gap:12px">'
                         '<div class="badge" style="width:52px;height:52px;font-size:18px">V</div>'
                         '<div><div style="font-size:15px;font-weight:700">冒险者通行证</div>'""",
  """               body=card('<div class="row" style="gap:12px">'
                         + shishi("excited", 62, "floaty fast") +
                         '<div><div style="font-size:15px;font-weight:700">冒险者通行证</div>'""")

b("""                    '<div class="badge" style="width:64px;height:64px;font-size:24px">✓</div>'
                    '<div style="text-align:center"><div class="h">开通成功</div>'""",
  """                    + shishi("win", 104, "floaty") +
                    '<div style="text-align:center"><div class="h">开通成功</div>'""")

b("""               body=card('<div style="text-align:center;padding:8px 0">'
                         '<div class="avatar" style="width:48px;height:48px;margin:0 auto"></div>'
                         '<div class="h sm" style="margin-top:12px">还没有冒险卷轴</div>'""",
  """               body=card('<div style="text-align:center;padding:8px 0">'
                         + '<div style="display:flex;justify-content:center">' + shishi("happy", 74, "floaty") + "</div>"
                         '<div class="h sm" style="margin-top:8px">还没有冒险卷轴</div>'""")

b("""                    + card('<div style="text-align:center;padding:8px 0">'
                           '<div class="avatar" style="width:48px;height:48px;margin:0 auto;background:#F3EADA;border-color:#E3D5BC"></div>'
                           '<div class="h sm" style="margin-top:12px">还没有上传文档</div>'""",
  """                    + card('<div style="text-align:center;padding:8px 0">'
                           + '<div style="display:flex;justify-content:center">' + shishi("think", 74, "floaty") + "</div>"
                           '<div class="h sm" style="margin-top:8px">还没有上传文档</div>'""")

b("""                    + card('<div style="text-align:center;padding:8px 0">'
                           '<div class="badge" style="background:#FDECEC;border-color:#E5484D;color:#E5484D;'
                           'width:48px;height:48px;font-size:20px;margin:0 auto">!</div>'
                           '<div class="h sm" style="margin-top:12px">网络好像断开了</div>'""",
  """                    + card('<div style="text-align:center;padding:8px 0">'
                           + '<div style="display:flex;justify-content:center">' + shishi("sad", 74, "floaty") + "</div>"
                           '<div class="h sm" style="margin-top:8px">网络好像断开了</div>'""")


def apply(path, patches):
    src = open(path, encoding="utf-8").read()
    ok = fail = 0
    for i, (old, new) in enumerate(patches):
        n = src.count(old)
        if n != 1:
            print("  [FAIL] #%d 命中 %d 次: %r" % (i, n, old[:70]))
            fail += 1
            continue
        src = src.replace(old, new)
        ok += 1
    open(path, "w", encoding="utf-8").write(src)
    print("%s -> 成功 %d / 失败 %d" % (path, ok, fail))
    return fail


if __name__ == "__main__":
    f = apply("gen_a.py", PA)
    f += apply("gen_b.py", PB)
    sys.exit(1 if f else 0)
