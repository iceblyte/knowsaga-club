"""生成 00-设计规范 / 01-核心闭环 / 02-挑战副本 / 03-冒险日志"""
import os
import kit as K
from kit import (card, slip, stamp, rule, btn, opt, bar, ring, li, phone, grid, doc,
                 nav, tabbar, magic, shishi, stage, coin, chest, medal, sparkle,
                 scroll_icon, scrollbox, momo, yuanyuan, tongbao, adv_avatar,
                 AV_ORDER, AV_NAME)

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def w(name, html):
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    print("  ok  " + name)


# =====================================================================
# 00 设计规范
# =====================================================================
def sw(h, n):
    return ('<div class="sw"><div class="box" style="background:' + h + '"></div>'
            '<div class="hx">' + h + '</div><div class="nm">' + n + "</div></div>")


def spec(title, items):
    lis = "".join("<li>" + i + "</li>" for i in items)
    return '<div class="spec"><h3>' + title + "</h3><ul>" + lis + "</ul></div>"


def sec(title, desc, inner):
    return ('<section class="ds-sec"><h2>' + title + "</h2><p>" + desc + "</p>" + inner + "</section>")


def plaque(svg, name, role, where, w=126, bg="#FEFCF6"):
    return ('<div style="background:' + bg + ';border:1px solid #D9C6A4;border-radius:8px;'
            'padding:12px 8px 11px;display:flex;flex-direction:column;align-items:center;'
            'gap:7px;width:' + str(w) + 'px">' + svg
            + '<div style="font-size:14px;font-weight:700;font-family:var(--f-disp)">' + name + '</div>'
            '<div style="font-size:11px;color:#9C6E15;font-weight:600">' + role + '</div>'
            '<div style="font-size:10.5px;color:#9A8870;line-height:1.55;text-align:center">'
            + where + "</div></div>")


def build_ds():
    c1 = "".join(sw(*x) for x in [
        ("#F1E8D0", "板色 · 页面底"),
        ("#FEFCF6", "纸面 · 阅读层"),
        ("#F5EDD8", "压痕面 · 控件层"),
        ("#EADFC4", "深压痕 · 分隔与槽"),
        ("#D9C6A4", "纸上的线"),
        ("#2A2018", "墨 · 正文"),
        ("#9A8870", "淡墨 · 次级文字"),
    ])
    c2 = "".join(sw(*x) for x in [
        ("#2F6BD8", "魔法蓝 · 主操作"),
        ("#1F4694", "按钮底边 / 按压"),
        ("#DCE9FB", "蓝浅底 · 选中"),
        ("#C8912A", "黄铜 · XP"),
        ("#9C6E15", "黄铜深 · 数字"),
        ("#2F7D4F", "正确 / 通过"),
        ("#A63A2E", "朱砂 · 错误与印章"),
        ("#6D4BC4", "稀有 / 连击"),
    ])
    s1 = ("<div class=\"ds-row\">"
          + spec("色彩使用配比", [
              "羊皮纸层约占 70% 视觉面积，承担全部长文本阅读",
              "魔法色约占 30%，只出现在按钮、状态、奖励上",
              "同一屏内高饱和色不超过 3 处，避免视觉噪音",
              "正确 / 错误色需搭配图标或文字，不单独依赖颜色传达",
          ])
          + spec("文字对比度", [
              "正文 #2A2018 on #F1E8D0：对比度 11.8:1",
              "次级文字 #9A8870 on #F1E8D0：对比度 3.6:1，仅用于辅助信息",
              "禁用态不得低于 2.5:1，且必须配合文案说明",
          ])
          + "</div>")

    t1 = ('<div style="background:#FEFCF6;border:1px solid #D9C6A4;border-radius:16px;padding:20px;">'
          '<div style="font-size:24px;font-weight:700;letter-spacing:-.02em;">拾万千知识，闯无尽关卡</div>'
          '<div class="tiny" style="margin-top:6px;">24px / 700 · 仅用于启动页与结算页的标语</div>'
          '<div style="height:1px;background:#EADFC4;margin:16px 0;"></div>'
          '<div style="font-size:17px;font-weight:600;">RAG 与传统关键词检索的差别</div>'
          '<div class="tiny" style="margin-top:6px;">17px / 600 · 题干与页面主标题</div>'
          '<div style="height:1px;background:#EADFC4;margin:16px 0;"></div>'
          '<div style="font-size:15px;font-weight:600;">召唤副本</div>'
          '<div class="tiny" style="margin-top:6px;">15px / 600 · 按钮与卡片标题</div>'
          '<div style="height:1px;background:#EADFC4;margin:16px 0;"></div>'
          '<div class="body">RAG 会先把文档切成小块并转成向量，再按语义相似度召回。</div>'
          '<div class="tiny" style="margin-top:6px;">13px / 400 / 行高 1.75 · 知识讲解正文</div>'
          '<div style="height:1px;background:#EADFC4;margin:16px 0;"></div>'
          '<div class="tiny">最后修改 3 天前 · 共 5 题</div>'
          '<div class="tiny" style="margin-top:6px;">11px / 400 · 辅助说明与时间戳</div>'
          "</div>")

    b1 = ('<div class="ds-row">'
          '<div style="width:200px;">' + btn("召唤副本") + '<div style="height:12px"></div>'
          + btn("开始挑战", "gold") + "</div>"
          '<div style="width:200px;">' + btn("分享给好友", "ghost") + '<div style="height:12px"></div>'
          + btn("题目生成中", "dis") + "</div>"
          + spec("按钮规范", [
              "底部 4px 深色实边，制造可按压的立体感",
              "按下时底边归零 + 整体下移 4px，模拟物理按键",
              "主操作全屏宽，一屏内只出现一个主按钮",
              "禁用态同时降低饱和与对比，并替换为进行中文案",
              "最小热区 44 × 44px，实测约 8mm，满足微信规范",
          ])
          + "</div>")

    cards = ('<div class="ds-row">'
             + '<div style="width:210px;display:flex;flex-direction:column;gap:12px;">'
             + card('<div class="h sm">冒险者档案</div><div class="sub" style="margin-top:4px">Lv.3 · 1280 XP</div>')
             + card('<div class="h sm">本题答对</div><div class="body sm" style="margin-top:4px">向量检索理解语义</div>', "ok")
             + card('<div class="h sm">本题答错</div><div class="body sm" style="margin-top:4px">正确答案是 C</div>', "bad")
             + "</div>"
             + '<div style="width:210px;display:flex;flex-direction:column;gap:12px;">'
             + card('<div class="h sm">金币奖励</div><div class="sub" style="margin-top:4px">+32 金币</div>', "gold")
             + card('<div class="h sm">连击加成</div><div class="sub" style="margin-top:4px">连续答对 3 题</div>', "rare")
             + card('<div class="h sm">知识副本</div><div class="sub" style="margin-top:4px">RAG 入门 · 5 题</div>', "blue")
             + "</div>"
             + spec("卡片规范", [
                 "圆角 16px，1px 暖棕描边，不使用重阴影",
                 "默认卡片面 #FEFCF6，需要强调阅读时切换为羊皮纸底",
                 "状态色卡片仅在答题反馈与结算场景使用",
                 "卡片内边距 13px，卡片间距 10px",
             ])
             + "</div>")

    inp = ('<div class="ds-row">'
           '<div style="width:250px;display:flex;flex-direction:column;gap:12px;">'
           + '<div class="field"><div class="ph">说出你想学的任何知识…<br>一句话 / 一段文字 / 一个网址</div>'
             '<div class="tiny" style="text-align:right;margin-top:8px">0 / 200</div></div>'
           + '<div class="field solid"><div style="font-size:12.5px;line-height:1.7;color:#2A2018">'
             '我想学习什么是 RAG，以及它和传统搜索有什么区别</div>'
             '<div class="tiny" style="text-align:right;margin-top:8px">28 / 200</div></div>'
           + "</div>"
           + '<div style="width:210px;display:flex;flex-direction:column;gap:12px;">'
           + '<div class="field solid" style="background:#FEFCF6">'
             '<div class="tiny" style="margin-bottom:6px">或粘贴一个链接</div>'
             '<div style="font-size:12.5px;color:#2A2018">https://example.com/rag-guide</div></div>'
           + '<div class="row" style="flex-wrap:wrap;gap:6px">'
             '<span class="chip">AI 入门</span><span class="chip">RAG 是什么</span>'
             '<span class="chip">近代史纲要</span></div>'
           + "</div>"
           + spec("输入与快捷项", [
               "输入框用虚线描边表达「可书写的卷轴」，聚焦后转为实线",
               "单行主题与多行文本共用同一容器，按内容自动增高",
               "优先提供历史与推荐 chip，减少键盘输入（微信规范 3.1）",
               "粘贴长链接或文档时自动识别类型并切换解析方式",
           ])
           + "</div>")

    prog = ('<div class="ds-row">'
            + '<div style="width:230px;display:flex;flex-direction:column;gap:14px;">'
            + '<div><div class="between" style="margin-bottom:6px"><span class="tiny">答题进度 3 / 5</span>'
              '<span class="tiny c-gold">+40 XP</span></div>' + bar(60) + "</div>"
            + '<div><div class="tiny" style="margin-bottom:6px">等级进度 1280 / 2000</div>' + bar(64, "blue") + "</div>"
            + '<div><div class="tiny" style="margin-bottom:6px">掌握度 80%</div>' + bar(80, "ok") + "</div>"
            + '<div><div class="tiny" style="margin-bottom:6px">连击 4 题</div>' + bar(80, "rare") + "</div>"
            + "</div>"
            + '<div style="width:230px;display:flex;align-items:center;gap:18px;background:#FEFCF6;'
              'border:1px solid #D9C6A4;border-radius:16px;padding:16px;">'
            + ring(80, label="80%") + ring(60, color="#C8912A", label="60%")
            + "</div>"
            + spec("进度与经验值", [
                "答题进度条固定在顶部，答错也让进度前进，避免卡住的挫败感",
                "XP 用金币金，等级用魔法蓝，掌握度用正确绿，三者语义不混用",
                "环形图只用于结算与报告页，答题中不使用，减少干扰",
                "经验值数字保留等宽字体，避免跳动时宽度抖动",
            ])
            + "</div>")

    opts = ('<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;max-width:760px;">'
            + card(opt("A", "先切分文档再检索"), "plain")
            + card(opt("B", "我的选择", "bad"), "plain")
            + card(opt("C", "按语义相似度召回 · 正确答案", "ok"), "plain")
            + card(opt("D", "待提交的选中项", "sel"), "plain")
            + "</div>"
            + spec("答题选项四态", [
                "默认态：羊皮纸底 + 暖棕描边，选项键为圆形浅底",
                "选中态（多选待提交）：魔法蓝描边 + 浅蓝底",
                "正确态：正确绿描边 + 浅绿底 + 键位填充绿色",
                "错误态：惠惠红描边 + 浅红底，且正确答案必须同屏可见",
                "四种状态均保持左侧键位圆点，颜色之外还有形状一致性",
            ]))

    badges = ('<div class="ds-row">'
              + '<div style="background:#FEFCF6;border:1px solid #D9C6A4;border-radius:16px;padding:18px;'
                'display:flex;gap:16px;align-items:center;">'
              + '<div class="badge">1</div><div class="badge rare">3</div>'
              + '<div class="badge off">7</div><div class="medal">' + medal(46) + '</div>'
              + '<div class="row" style="gap:10px">'
              + adv_avatar("scholar", 40) + adv_avatar("mage", 40)
              + adv_avatar("knight", 40) + "</div>"
              + "</div>"
              + spec("勋章与头像", [
                  "勋章用圆形金底 + 描边，未解锁降饱和并保留轮廓",
                  "等级 1 到 3 用金，稀有与连击成就用紫",
                  "头像统一 6 款职业形象，最小 28px，最大 84px（公会卡与海报）",
                  "勋章墙按 4 列排布，一行不超过 4 个",
              ])
              + "</div>")

    states = ('<div class="ds-row">'
              + '<div style="width:190px;background:#FEFCF6;border:1px solid #D9C6A4;border-radius:16px;'
                'padding:22px;display:flex;flex-direction:column;align-items:center;gap:12px;">'
              + stage(96, "excited") + '<div class="h sm">正在召唤副本</div>'
              + '<div class="tiny" style="text-align:center">正在联网检索知识…</div>'
              + bar(55, "blue", "width:120px") + "</div>"
              + '<div style="width:190px;background:#FEFCF6;border:1px solid #D9C6A4;border-radius:16px;'
                'padding:22px;display:flex;flex-direction:column;align-items:center;gap:12px;">'
              + shishi("happy", 62)
              + '<div class="h sm">还没有冒险卷轴</div>'
              + '<div class="tiny" style="text-align:center">去社团大厅领取你的第一张卷轴吧</div>'
              + btn("去社团大厅", "sm") + "</div>"
              + '<div style="width:190px;background:#FEFCF6;border:1px solid #D9C6A4;border-radius:16px;'
                'padding:22px;display:flex;flex-direction:column;align-items:center;gap:12px;">'
              + shishi("dizzy", 62)
              + '<div class="h sm">副本召唤失败</div>'
              + '<div class="tiny" style="text-align:center">网络不稳定，题目没有生成成功</div>'
              + btn("重新召唤", "sm") + "</div>"
              + spec("加载 / 空态 / 异常", [
                  "加载态必须有动画，静止画面会被误认为卡死（微信规范 2.2）",
                  "加载超过 3 秒需给出阶段性文案，超过 8 秒提供取消入口",
                  "空态用拾拾的默认表情，不做「难过」——空态不是失败",
                  "异常态保留用户已输入内容，重试不需要重新输入",
              ])
              + "</div>")

    cast = ('<div class="ds-row" style="gap:12px">'
            + plaque(shishi("happy", 78), "拾拾", "引导精灵", "生成中 · 空态<br>结算 · 异常")
            + plaque(momo("happy", 78), "墨墨", "猫头鹰书灵", "答题讲解 · 复盘报告<br>错题本 · 知识库")
            + plaque(yuanyuan(78), "鸢鸢", "折纸信使", "邀请 · 等待<br>分享 · 复习提醒")
            + plaque(tongbao(78), "铜宝", "宝箱怪", "通关结算 · 通行证<br>支付成功")
            + spec("为什么要四个角色，而不是一个", [
                "分工不重叠：一个角色只负责一个语义域，避免「到处贴吉祥物」",
                "拾拾负责流程与情绪，墨墨负责知识，鸢鸢负责社交，铜宝负责收获",
                "同一屏最多出现两个角色，其余靠印章与图标承担",
                "剪影互相区分：拾拾圆润、墨墨圆润带耳羽、鸢鸢全直边、铜宝方正",
                "全部为 SVG 路径，无位图依赖，任意尺寸不失真，不增加主包体积",
            ])
            + "</div>")

    sprites = ('<div class="ds-row" style="gap:10px;align-items:flex-start">'
               + '<div style="background:#F1E8D0;border:1px solid #D9C6A4;border-radius:8px;'
                 'padding:12px 14px">'
               + '<div class="tiny" style="margin-bottom:8px">拾拾 · 表情状态机（8 态）</div>'
               + '<div class="cast">'
               + "".join('<div>' + shishi(st, 56) + '<span class="tiny">' + nm + "</span></div>"
                         for st, nm in [("normal", "默认"), ("happy", "开心"), ("excited", "兴奋"),
                                        ("win", "通关"), ("think", "思考"), ("sad", "失落"),
                                        ("sleep", "空态"), ("dizzy", "异常")])
               + "</div></div>"
               + '<div style="background:#F1E8D0;border:1px solid #D9C6A4;border-radius:8px;'
                 'padding:12px 14px">'
               + '<div class="tiny" style="margin-bottom:8px">墨墨 · 讲解与复盘的四种语气</div>'
               + '<div class="cast">'
               + "".join('<div>' + momo(st, 56) + '<span class="tiny">' + nm + "</span></div>"
                         for st, nm in [("normal", "陈述"), ("happy", "答对"), ("think", "答错"),
                                        ("sad", "需巩固")])
               + "</div></div>"
               + '<div style="background:#F1E8D0;border:1px solid #D9C6A4;border-radius:8px;'
                 'padding:12px 14px;display:flex;flex-direction:column;align-items:center;gap:10px">'
               + stage(150, "happy") + '<div class="tiny">法阵舞台 · 仅用于生成态</div></div>'
               + "</div>"
               + '<div style="height:14px"></div>'
               + '<div class="ds-row">'
               + spec("形象使用规范", [
                   "静态场景一律不动；只有生成态（法阵舞台）与答题反馈才有动效",
                   "鸢鸢的飘行只出现在「等待对方回应」，幅度控制在 5px 以内",
                   "尺寸只用三档：卡片内 46–58px、空态与海报 72–96px、舞台 100px 以上",
                   "角色永远不替换数据：数字、进度条、正确率始终是可读的文本",
                   "开启系统「减少动效」偏好时，全部浮动、闪烁、飘行自动关闭",
               ])
               + spec("角色出现的密度", [
                   "单屏最多两个角色，超过两个就把其中一个降级成图标",
                   "讲解卡用墨墨、分享卡用鸢鸢、结算用铜宝，同一场景不混用",
                   "空态与异常态固定用拾拾——它是用户最先认识的角色",
                   "新角色一律复用同一套墨线（2.2–2.6px）与平涂，不引入渐变",
               ])
               + "</div>")

    avatars = ('<div class="ds-row" style="gap:12px">'
               + "".join(plaque(adv_avatar(k, 74), AV_NAME[k], "冒险者头像",
                                where, w=104)
                         for k, where in [
                             ("apprentice", "新注册用户<br>Lv.1–2"),
                             ("ranger", "探索型学习者"),
                             ("mage", "重度用户<br>Lv.4 以上"),
                             ("knight", "PK 与对战场景"),
                             ("scholar", "默认身份<br>「检索者」"),
                             ("artisan", "知识库创建者")])
               + spec("头像为什么必须有形象", [
                   "旧方案用纯色圆占位，导致公会成员、排行榜、好友列表读起来是同一个人",
                   "头像承担社交识别：名单里必须一眼看出「这是谁」，而不是第几个色块",
                   "六款职业与「冒险者」世界观同源，同时映射用户的学习阶段",
                   "同一张脸 + 不同头饰，小到 28px 仍可靠剪影与色相区分",
                   "头像不出现在正文里，只出现在身份位；正文用印章与图标",
               ])
               + "</div>")

    mat = ('<div class="ds-row">'
           + '<div style="flex:1;min-width:290px">'
             '<div class="tiny" style="margin-bottom:8px">L1 · 纸面（.card）— 阅读区域</div>'
           + card('<div class="h sm">题干或说明文字</div>'
                  '<div class="body sm" style="margin-top:4px">明亮纸色 + 可见细边，无外投影。'
                  '读作「纸上的一个区域」。</div>')
           + '<div class="tiny" style="margin:18px 0 8px">L2 · 纸片（.slip）— 离散物件</div>'
           + slip('<div class="h sm">通关结算单</div>'
                  '<div class="body sm" style="margin-top:4px">硬投影 + 细描边，'
                  '读作「一张单独的纸」。</div>')
           + '<div class="tiny" style="margin:18px 0 8px">L3 · 印章（.stamp）— 全站唯一的响亮元素</div>'
           + '<div class="row" style="gap:10px;flex-wrap:wrap">'
           + stamp("答对", "ok") + stamp("正确答案 C") + stamp("部分正确", "gold")
           + "</div>"
           + "</div>"
           + spec("为什么不用统一圆角卡片", [
               "内容默认不装盒：先靠纸面明暗与虚实线分组，需要离散物件时才给边界",
               "层级用材质区分，不用投影——全站没有一处通用的柔和卡影",
               "圆角随材质变：纸面 6px、纸片 3px、印章 2px，不共用一个圆角值",
               "控件用压痕面，阅读用纸面，两者必须能在纸底上一眼分辨",
           ])
           + spec("动效纪律", [
               "静态场景一律不动：档案页、列表、空态里的精灵不漂浮",
               "生成态的法阵旋转是功能性的——它在说明「正在发生什么」",
               "答题反馈的抖动与变色是响应人的动作，不是装饰",
               "全站只有这两处动效，且都受「减少动效」偏好控制",
           ])
           + "</div>")

    body = (sec("材质层级与印章",
                "整套界面只有三种材质：纸面、纸片、印章。内容默认不装进盒子，"
                "层级靠材质而不是阴影来区分，全站没有一处通用的柔和卡影。",
                mat)
            + sec("角色谱系", "四个角色，各有分工，互不抢戏：拾拾负责流程与情绪，"
                             "墨墨负责知识，鸢鸢负责社交，铜宝负责收获。"
                             "它们共用同一套墨线与平涂，但剪影刻意互相区分——"
                             "小到 46px 也能一眼认出是谁。角色的任务是替界面说话，"
                             "而不是给界面贴装饰。", cast)
            + sec("表情与语气", "角色不换人，只换表情。拾拾八态覆盖全部流程状态；"
                               "墨墨四态对应讲解卡的四种语气：陈述、答对、答错、需巩固。",
                sprites)
            + sec("冒险者头像", "六款职业形象，替换原先的纯色圆占位。"
                               "这是本轮改动里对可用性影响最大的一处——"
                               "公会成员、排行榜、好友列表原本读起来是「一堆色块」，"
                               "现在每一个身份位都有可辨认的脸。", avatars)
            + sec("色彩系统", "整套配色分两层：羊皮纸层承担阅读，魔法色层承担情绪与操作。"
                "色值全部通过对比度校验，正文达到 11.8:1。",
                '<div class="ds-row">' + c1 + "</div>"
                '<div style="height:14px"></div>'
                '<div class="ds-row">' + c2 + "</div>"
                '<div style="height:16px"></div>' + s1)
            + sec("字体阶梯", "中文对齐微信小程序官方规范 22 / 17 / 15 / 14 / 12，"
                             "全站只用 400 与 600 两档字重。拉丁与数字单独用 Baloo 2 —— "
                             "游戏化产品里数字承担了大量情绪（XP / 等级 / 分数 / 进度），"
                             "值得一个有个性的 face。中文因小程序主包 2MB 上限不引网络字体，"
                             "个性改由字重、字距、行高承担。", t1)
            + sec("按钮体系", "按钮用底部实边制造立体按压感，是整个产品游戏化气质最直接的来源。", b1)
            + sec("卡片与容器", "卡片是承载知识的最小单位。统一为纸面 + 可见细边，"
                               "不叠加通用投影，避免与纸底糊成一片。", cards)
            + sec("输入与快捷项", "社团大厅只保留一个输入框，降低启动门槛是这个页面的唯一目标。", inp)
            + sec("进度与经验值", "进度必须可见且持续。即使答错，也有某个维度在向前推进。", prog)
            + sec("答题选项四态", "答题反馈是整个产品最高频的交互，四种状态必须一眼可辨且不产生焦虑。", opts)
            + sec("勋章与头像", "成长感的可视化载体。", badges)
            + sec("加载 / 空态 / 异常", "异常状态是用户最沮丧的时刻，必须给明确原因和可执行的下一步。", states))

    html = doc("00", "设计规范",
               "《知拾冒险社》全部 UI 原型的公共基础。视觉语言为「纸与印」："
               "界面里只有三种材质——纸面、纸片、印章；内容默认不装进盒子，"
               "层级靠材质而非阴影区分；全站唯一的响亮元素是朱砂印章。"
               "以下规范是 01 到 07 全部页面的唯一视觉来源。",
               ["纸面 / 纸片 / 印章", "数字用 Baloo 2", "无统一卡影",
                "微信字号规范", "热区 ≥ 44px", "状态色不单依赖颜色"],
               body)
    w("00-设计规范.html", html)


# =====================================================================
# 01 核心闭环
# =====================================================================
def hero_card():
    return card('<div class="between"><div class="row" style="gap:9px">' + adv_avatar("scholar", 32)
                + '<div><div style="font-size:12px;font-weight:600">Lv.3 见习冒险者</div>'
                '<div class="tiny">1280 / 2000 XP</div></div></div>'
                '<span class="pill gold">连续 4 天</span></div>'
                '<div style="height:8px"></div>' + bar(64, "blue"))


def build_01():
    s1 = phone("启动页 · 卷轴展开",
               '<div class="spacer"></div>'
               '<div style="display:flex;flex-direction:column;align-items:center;gap:20px">'
               + stage(176, "happy") +
               '<div style="text-align:center"><div style="font-size:20px;font-weight:700">知拾冒险社</div>'
               '<div class="sub" style="margin-top:8px">拾万千知识，闯无尽关卡</div></div>'
               + bar(45, "blue", "width:150px") +
               '<div class="tiny">正在展开冒险卷轴…</div></div>'
               '<div class="spacer"></div>',
               head='<div style="height:48px"></div>',
               bg="#FEFCF6",
               desc="冷启动到首屏的过渡，用展开的魔法阵替代默认白屏。",
               title="法阵 1.8s 匀速旋转，下方文案按阶段切换，避免用户误判卡死。")

    s2 = phone("社团大厅 · 空态",
               card('<div class="row"><div style="flex:none">'
                    + shishi("happy", 46) + "</div>"
                    '<div><div class="h sm">冒险者，欢迎回到社团大厅</div>'
                    '<div class="sub" style="margin-top:3px">今天想拾取哪一块知识？</div></div></div>', "rel")
               + scrollbox('<div class="ph">说出你想学的任何知识…<br>一句话 / 一段文字 / 一个网址 / 一份文档</div>'
                           '<div class="tiny" style="text-align:right">0 / 200</div>', grow=True)
               + '<div class="row" style="flex-wrap:wrap;gap:6px">'
                 '<span class="chip">AI 入门</span><span class="chip">RAG 是什么</span>'
                 '<span class="chip">近代史纲要</span></div>'
               + btn("召唤副本") + hero_card(),
               head=nav("社团大厅", back=False, right="我的"),
               foot=tabbar(0),
               desc="全屏只有一个目标：让用户把想学的东西写下来。",
               title="历史与推荐 chip 减少键盘输入，能显著提升首题生成率。")

    s3 = phone("社团大厅 · 已输入",
               head=nav("社团大厅", back=False, right="我的"),
               foot=tabbar(0),
               desc="输入后主按钮激活，同时提示 AI 会联网补充知识。",
               title="超过 8 个字才激活按钮，防止用户提交无意义内容浪费 AI 额度。",
               body=card('<div class="row"><div style="flex:none">'
                         + shishi("think", 46) + "</div>"
                         '<div><div class="h sm">冒险者，欢迎回到社团大厅</div>'
                         '<div class="sub" style="margin-top:3px">今天想拾取哪一块知识？</div></div></div>', "rel")
                    + scrollbox('<div style="font-size:12.5px;line-height:1.75;color:#2A2018">'
                                '我想学习什么是 RAG，以及它和传统搜索有什么区别</div>'
                                '<div class="between"><span class="pill blue">AI 将联网补充</span>'
                                '<span class="tiny">28 / 200</span></div>', grow=True)
                    + '<div class="row" style="flex-wrap:wrap;gap:6px">'
                      '<span class="chip">追加背景资料</span><span class="chip">上传文档</span>'
                      '<span class="chip">粘贴网址</span></div>'
                    + btn("召唤副本")
                    + card('<div class="between"><div class="row" style="gap:9px">'
                           + adv_avatar("scholar", 32)
                           + '<div><div style="font-size:12px;font-weight:600">Lv.3 见习冒险者</div>'
                           '<div class="tiny">1280 / 2000 XP</div></div></div>'
                           '<span class="pill gold">连续 4 天</span></div>'
                           '<div style="height:8px"></div>' + bar(64, "blue")))

    s4 = phone("副本召唤中",
               head=nav("召唤中", right="取消"),
               bg="#FEFCF6",
               desc="AI 出题的等待过程，把黑盒等待变成可见的三步仪式。",
               title="微信小程序单次请求上限 60s，超过 8s 显示取消入口，走异步轮询。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:18px">'
                    + stage(176, "excited") +
                    '<div style="text-align:center"><div class="h">正在生成知识副本</div>'
                    '<div class="sub" style="margin-top:6px">RAG 入门 · 预计 12 秒</div></div>'
                    + bar(62, "blue", "width:180px") + "</div>"
                    '<div class="spacer"></div>'
                    + card(li("1", "联网检索知识", "已完成 · 命中 6 条资料", "完成")
                           + '<div style="height:8px"></div>'
                           + li("2", "生成闯关题目", "正在生成第 4 / 5 题")
                           + '<div style="height:8px"></div>'
                           + li("3", "校验题目结构", "等待中"), "plain"))

    s5 = phone("副本确认页",
               head=nav("知识副本", right="重生成"),
               desc="出题完成后先给一次确认机会，避免直接进入不想要的题目。",
               title="题目构成与知识点标签前置展示，让用户对难度有预期，降低中途退出率。",
               body=card('<div class="row" style="align-items:flex-start;gap:10px">'
                         + shishi("happy", 56) +
                         '<div style="flex:1;min-width:0">'
                         '<div class="between"><span class="pill blue">知识副本</span>'
                         '<span class="tiny">约 4 分钟</span></div>'
                         '<div class="h" style="margin-top:6px">RAG 入门闯关</div>'
                         '<div class="body sm" style="margin-top:6px">'
                         '围绕 RAG 的基础定义、检索原理与应用场景生成的题库。</div></div></div>')
                    + '<div class="grid3">'
                    + card('<div class="stat sm c-blue">3</div><div class="statlab">单选题</div>', "plain")
                    + card('<div class="stat sm c-blue">1</div><div class="statlab">多选题</div>', "plain")
                    + card('<div class="stat sm c-blue">1</div><div class="statlab">判断题</div>', "plain")
                    + "</div>"
                    + card('<div class="tiny" style="margin-bottom:8px">本次覆盖的知识点</div>'
                           '<div class="row" style="flex-wrap:wrap;gap:6px">'
                           '<span class="chip">RAG 基本定义</span><span class="chip">向量检索</span>'
                           '<span class="chip">与搜索引擎的边界</span><span class="chip">应用场景</span></div>')
                    + '<div class="spacer"></div>'
                    + btn("开始挑战副本")
                    + '<div class="tiny" style="text-align:center">答错也会给出完整讲解，不会扣分</div>')

    s6 = phone("通关结算",
               head='<div style="height:48px"></div>',
               bg="#FEFCF6",
               desc="通关瞬间的奖励释放，是整个循环里情绪最高的节点。",
               title="XP 与金币数字做 0.8s 递增动画，正确率环延后 0.3s 绘制，制造层次感。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:14px">'
                    + stage(150, "win") +
                    '<div style="text-align:center"><div style="font-size:22px;font-weight:700">副本通关</div>'
                    '<div class="sub" style="margin-top:6px">RAG 入门 · 5 题全部完成</div>'
                    '<div style="margin-top:10px">' + stamp("已通关", "gold") + '</div></div>'
                    + '</div>'
                    + '<div class="grid2" style="margin-top:6px">'
                    + card('<div class="stat c-gold">+180</div><div class="statlab">经验值 XP</div>', "gold")
                    + card('<div class="row" style="gap:8px">' + tongbao(42)
                           + '<div><div class="stat sm c-gold">+32</div>'
                           '<div class="statlab">冒险金币</div></div></div>', "gold")
                    + "</div>"
                    + card('<div class="row">' + ring(80, size=64, stroke=8, label="80%", lab_size=15)
                           + '<div><div style="font-size:13px;font-weight:600">正确率 4 / 5</div>'
                           '<div class="tiny" style="margin-top:4px">超过社团里 72% 的冒险者</div></div></div>')
                    + '<div class="spacer"></div>'
                    + btn("查看冒险探险日志")
                    + btn("再来一局", "ghost"))

    html = doc("01", "核心业务闭环",
               "从打开小程序到通关结算的完整主链路，共 6 屏。这一组是产品的骨架，"
               "其余所有页面都挂在它上面。设计上刻意压低了信息密度——"
               "每一步只让用户做一个决定，把「开始学习」这件事的门槛降到最低。",
               ["冷启动 → 大厅 → 生成 → 挑战 → 结算", "异步轮询规避 60s 超时",
                "生成过程三步可见", "结算页奖励动画", "6 屏 · MVP P0"],
               grid([s1, s2, s3, s4, s5, s6]))
    w("01-核心闭环.html", html)


# =====================================================================
# 02 挑战副本
# =====================================================================
def qhead(cur, total, xp):
    return ('<div><div class="between" style="margin-bottom:6px">'
            '<span style="font-size:12px;font-weight:600">第 ' + str(cur) + " / " + str(total) + " 题</span>"
            '<span class="tiny c-gold">' + xp + "</span></div>" + bar(int(cur * 100 / total)) + "</div>")


def stem(kind, text):
    return card('<span class="pill">' + kind + '</span>'
                '<div style="font-size:13.5px;line-height:1.7;margin-top:8px;font-weight:600">'
                + text + "</div>", "parch")


def build_02():
    s1 = phone("单选题 · 未作答",
               head=nav("挑战副本", right="1 / 5"),
               desc="默认态。四个选项等权重，不暗示答案。",
               title="题干字号 13.5px、行高 1.7，保证 3 行以内不折行过多；选项热区 44px。",
               body=qhead(1, 5, "+40 XP")
                    + stem("单选题", "RAG 与传统关键词检索最核心的差别是什么？")
                    + opt("A", "先把文档切分成小块再检索")
                    + opt("B", "只在中文语料范围内检索")
                    + opt("C", "按语义相似度召回相关片段")
                    + opt("D", "完全不依赖大模型生成答案")
                    + '<div class="spacer"></div>'
                    + btn("确认作答", "dis"))

    s2 = phone("单选题 · 答对",
               head=nav("挑战副本", right="1 / 5"),
               desc="答对后正确项立刻变绿，讲解卡同步展开，并发放 XP。",
               title="反馈卡固定在选项下方，不做全屏弹窗，避免打断答题节奏。",
               body=qhead(1, 5, "+40 XP")
                    + stem("单选题", "RAG 与传统关键词检索最核心的差别是什么？")
                    + opt("A", "先把文档切分成小块再检索")
                    + opt("B", "只在中文语料范围内检索")
                    + opt("C", "按语义相似度召回相关片段", "ok")
                    + opt("D", "完全不依赖大模型生成答案")
                    + card('<div class="row" style="align-items:flex-start;gap:10px">'
                           + momo("happy", 50) +
                           '<div style="flex:1;min-width:0">'
                           '<div class="between"><span class="stamp ok">答对</span>'
                           '<span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           'RAG 会先把文档切成小块并转成向量，检索时按语义相似度召回，'
                           '所以它能理解「意思」而不只是匹配关键词。</div></div></div>', "ok grow",
                           "display:flex;flex-direction:column;justify-content:center"))

    s3 = phone("单选题 · 答错",
               head=nav("挑战副本", right="1 / 5"),
               desc="答错时用户选择标红、正确答案标绿，两者同屏，讲解不省略。",
               title="错误色降低饱和度避免惩罚感；文案用「正确答案是 C」而非「你答错了」。",
               body=qhead(1, 5, "+0 XP")
                    + stem("单选题", "RAG 与传统关键词检索最核心的差别是什么？")
                    + opt("A", "先把文档切分成小块再检索")
                    + opt("B", "只在中文语料范围内检索", "bad")
                    + opt("C", "按语义相似度召回相关片段", "ok")
                    + opt("D", "完全不依赖大模型生成答案")
                    + card('<div class="row" style="align-items:flex-start;gap:10px">'
                           + momo("think", 50) +
                           '<div style="flex:1;min-width:0">'
                           '<div class="between"><span class="stamp">正确答案 C</span>'
                           '<span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           'B 错在把 RAG 当成语言限制。RAG 的核心是「先检索再生成」，'
                           '靠向量相似度找到相关片段，与语种无关。</div></div></div>', "bad grow",
                           "display:flex;flex-direction:column;justify-content:center"))

    s4 = phone("多选题 · 待提交",
               head=nav("挑战副本", right="3 / 5"),
               desc="多选允许勾选多个，选中项变蓝，底部按钮提示已选数量。",
               title="未达到最少选项数时按钮禁用并提示原因，避免用户反复点击无效。",
               body=qhead(3, 5, "+60 XP")
                    + stem("多选题", "以下哪些属于 RAG 相比传统搜索的优势？")
                    + opt("A", "能理解同义表达", "sel")
                    + opt("B", "检索速度一定更快")
                    + opt("C", "可结合私有文档作答", "sel")
                    + opt("D", "答案可附带出处片段")
                    + '<div class="spacer"></div>'
                    + btn("已选 2 项 · 确认作答"))

    s5 = phone("多选题 · 部分正确",
               head=nav("挑战副本", right="3 / 5"),
               desc="多选按比例给分，选对部分标绿、错选标红，并说明得分规则。",
               title="多选不给全或无，答对一半拿一半 XP，符合多邻国「让失败安全」的原则。",
               body=qhead(3, 5, "+30 XP")
                    + stem("多选题", "以下哪些属于 RAG 相比传统搜索的优势？")
                    + opt("A", "能理解同义表达", "ok")
                    + opt("B", "检索速度一定更快", "bad")
                    + opt("C", "可结合私有文档作答", "ok")
                    + opt("D", "答案可附带出处片段")
                    + card('<div class="row" style="align-items:flex-start;gap:10px">'
                           + momo("think", 50) +
                           '<div style="flex:1;min-width:0">'
                           '<div class="between"><span class="stamp gold">部分正确</span>'
                           '<span class="tiny">收起</span></div>'
                           '<div class="body sm" style="margin-top:6px">'
                           '正确答案是 A、C、D。多选按比例计分，选对 3 项中的 2 项，'
                           '拿到一半经验值。B 错在速度并非 RAG 的优势。</div></div></div>', "gold grow",
                           "display:flex;flex-direction:column;justify-content:center"))

    s6 = phone("判断题 · 未作答",
               head=nav("挑战副本", right="5 / 5"),
               desc="判断题只有两个选项，做成大尺寸对错卡而非小按钮。",
               title="判断题的选项键改用符号而非字母，减少一次语义转换。",
               body=qhead(5, 5, "+20 XP")
                    + stem("判断题", "RAG 可以完全不依赖大模型，只靠向量检索完成问答。")
                    + '<div style="height:6px"></div>'
                    + '<div class="grid2" style="gap:10px">'
                    + card('<div style="text-align:center;padding:8px 0">'
                           '<div style="font-size:20px;font-weight:700;color:#2F7D4F">&#10003;</div>'
                           '<div style="font-size:13px;font-weight:600;margin-top:6px">正确</div></div>', "plain")
                    + card('<div style="text-align:center;padding:8px 0">'
                           '<div style="font-size:20px;font-weight:700;color:#A63A2E">&#10007;</div>'
                           '<div style="font-size:13px;font-weight:600;margin-top:6px">错误</div></div>', "plain")
                    + "</div>"
                    + '<div class="spacer"></div>'
                    + '<div class="tiny" style="text-align:center">这是本局最后一题，作答后生成探险日志</div>')

    s7 = phone("讲解折叠态",
               head=nav("挑战副本", right="2 / 5"),
               desc="讲解默认展开，用户可折叠以免页面过长。",
               title="折叠后仅保留一行摘要，点击整行展开，折叠状态在题目间不共享。",
               body=qhead(2, 5, "+40 XP")
                    + stem("单选题", "向量检索相比关键词检索，主要解决什么问题？")
                    + opt("A", "同义词与近义表达无法匹配", "ok")
                    + opt("B", "文档数量过少")
                    + opt("C", "模型推理速度过慢")
                    + opt("D", "多语言支持不足")
                    + card('<div class="between"><span class="stamp ok">答对</span>'
                           '<span class="tiny">展开</span></div>'
                           '<div class="tiny" style="margin-top:8px">点击查看本题知识讲解</div>', "ok")
                    + card('<div class="tiny" style="margin-bottom:6px">相关知识点</div>'
                           '<div class="row" style="flex-wrap:wrap;gap:6px">'
                           '<span class="chip">向量检索</span><span class="chip">语义相似度</span></div>', "plain")
                    + '<div class="spacer"></div>'
                    + btn("下一题"))

    s8 = phone("退出确认",
               head=nav("挑战副本", right="3 / 5"),
               desc="中途返回时弹层确认，明确告知进度会被保留。",
               title="退出不是失败——文案强调「进度已保存」，降低用户的心理负担。",
               body=qhead(3, 5, "+40 XP")
                    + stem("多选题", "以下哪些属于 RAG 相比传统搜索的优势？")
                    + opt("A", "能理解同义表达", "sel")
                    + opt("B", "检索速度一定更快")
                    + opt("C", "可结合私有文档作答", "sel")
                    + opt("D", "答案可附带出处片段")
                    + '<div class="spacer"></div>'
                    + btn("已选 2 项 · 确认作答"),
               foot='<div class="mask"><div class="card plain" style="width:100%;padding:18px;text-align:center">'
                    + shishi("think", 76) +
                    '<div class="h" style="margin-top:10px">要离开这个副本吗？</div>'
                    '<div class="body sm" style="margin-top:8px">'
                    '当前进度会保存，下次可以从第 3 题继续挑战。</div>'
                    '<div style="height:16px"></div>' + btn("继续挑战")
                    + '<div style="height:8px"></div>' + btn("保存并退出", "ghost") + "</div></div>")

    s9 = phone("最后一题 · 提交中",
               head=nav("提交中"),
               bg="#FEFCF6",
               desc="全部作答完成后提交，进入报告生成。",
               title="提交与报告生成合并为一次请求，前端先本地判题、再一次性上报。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:18px">'
                    + stage(160, "excited") +
                    '<div style="text-align:center"><div class="h">正在撰写冒险探险日志</div>'
                    '<div class="sub" style="margin-top:6px">统计答题情况并生成复盘报告</div></div>'
                    + bar(76, "blue", "width:180px") + "</div>"
                    '<div class="spacer"></div>'
                    + card('<div class="grid3">'
                           '<div style="text-align:center"><div class="stat sm c-gold">4/5</div>'
                           '<div class="statlab">答对题数</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-blue">80%</div>'
                           '<div class="statlab">正确率</div></div>'
                           '<div style="text-align:center"><div class="stat sm c-ok">180</div>'
                           '<div class="statlab">获得 XP</div></div></div>', "plain"))

    html = doc("02", "挑战副本",
               "答题闯关的全部题型与状态，共 9 屏。这一组是整个产品交互密度最高的部分，"
               "设计目标只有一个：让用户答完立刻知道自己对不对、为什么，"
               "并且无论答对答错都不产生挫败感。所有反馈都在当前屏内完成，不跳页、不弹窗。",
               ["单选 / 多选 / 判断", "答对 · 答错 · 部分正确", "讲解可折叠",
                "退出保留进度", "多选按比例给分", "9 屏"],
               grid([s1, s2, s3, s4, s5, s6, s7, s8, s9]))
    w("02-挑战副本.html", html)


# =====================================================================
# 03 冒险日志
# =====================================================================
def build_03():
    s1 = phone("探险日志 · 主视图",
               head=nav("冒险探险日志", right="分享"),
               desc="报告首屏。正确率是唯一的大数字，其余信息逐层展开。",
               title="正确率用环形图而非数字，环的缺口让「还没满」这件事被看见。",
               body=card('<div class="row" style="gap:16px">' + ring(80, size=88)
                         + '<div><div class="h">RAG 入门闯关</div>'
                         '<div class="tiny" style="margin-top:6px">2026-09-14 · 用时 3 分 12 秒</div>'
                         '<div class="row" style="margin-top:10px;gap:6px">'
                         '<span class="pill gold">+180 XP</span><span class="pill">+32 金币</span></div>'
                         "</div></div>")
                    + '<div class="grid3">'
                    + card('<div class="stat sm c-ok">4/5</div><div class="statlab">答对</div>', "plain")
                    + card('<div class="stat sm c-bad">1</div><div class="statlab">答错</div>', "plain")
                    + card('<div class="stat sm c-blue">8.4s</div><div class="statlab">平均用时</div>', "plain")
                    + "</div>"
                    + card('<div class="row" style="gap:10px">' + momo("happy", 52)
                           + '<div style="flex:1;min-width:0">'
                           '<div class="between"><span style="font-size:12.5px;font-weight:600">'
                           '本局超过社团里 72% 的冒险者</span><span class="pill ok">中上</span></div>'
                           '<div style="height:10px"></div>' + bar(72, "ok") + "</div></div>", "plain")
                    + '<div class="spacer"></div>'
                    + btn("生成分享海报")
                    + btn("返回社团大厅", "ghost"))

    s2 = phone("三句话总结",
               head=nav("知识总结"),
               desc="AI 生成的复盘报告主体，控制在三句话以内。",
               title="每句话都带知识点锚点，点击可跳到对应题目的讲解，形成复习闭环。",
               body=card('<div class="row" style="justify-content:space-between;align-items:flex-start">'
                         '<span class="tiny">三句话知识总结</span>'
                         + momo("happy", 46) + "</div>"
                         '<div class="stack" style="margin-top:6px">'
                         '<div class="row" style="align-items:flex-start"><span class="dotmark"'
                         ' style="margin-top:8px"></span>'
                         '<span class="body sm">RAG 等于「检索 + 生成」，先找到资料再让模型作答。</span></div>'
                         '<div class="row" style="align-items:flex-start"><span class="dotmark"'
                         ' style="margin-top:8px"></span>'
                         '<span class="body sm">向量检索靠语义相似度，所以能匹配同义表达。</span></div>'
                         '<div class="row" style="align-items:flex-start"><span class="dotmark"'
                         ' style="margin-top:8px"></span>'
                         '<span class="body sm">它的最大价值在私有文档场景，而不是替代通用搜索。</span></div>'
                         "</div>", "parch")
                    + card('<div class="tiny" style="margin-bottom:8px">掌握较好的知识点</div>'
                           '<div class="row" style="flex-wrap:wrap;gap:6px">'
                           '<span class="pill ok">RAG 基本定义</span>'
                           '<span class="pill ok">向量检索</span></div>', "ok")
                    + card('<div class="tiny" style="margin-bottom:8px">需要再巩固的知识点</div>'
                           '<div class="row" style="flex-wrap:wrap;gap:6px">'
                           '<span class="pill bad">RAG 与搜索引擎的边界</span></div>', "bad")
                    + '<div class="spacer"></div>'
                    + btn("复习薄弱知识点", "gold"))

    s3 = phone("复习建议",
               head=nav("下一步建议"),
               desc="给出可执行的动作，而不是空泛的鼓励。",
               title="每条建议都绑定一个具体按钮，让「建议」可以直接被执行。",
               body=card('<div class="row" style="align-items:flex-start">'
                         '<span class="badge" style="width:30px;height:30px;font-size:13px">1</span>'
                         '<div><div class="h sm">重做第 3 题</div>'
                         '<div class="body sm" style="margin-top:5px">'
                         '你在「RAG 与搜索引擎的边界」上答错了，这是本次唯一的失分点。</div>'
                         '<div style="height:10px"></div>' + btn("立即重做", "sm ghost") + "</div></div>")
                    + card('<div class="row" style="align-items:flex-start">'
                           '<span class="badge" style="width:30px;height:30px;font-size:13px">2</span>'
                           '<div><div class="h sm">3 天后自动提醒复习</div>'
                           '<div class="body sm" style="margin-top:5px">'
                           '已按遗忘曲线为你排入「旧识重温」关卡，到时会在微信里提醒。</div>'
                           '<div style="height:10px"></div>'
                           '<span class="pill gold">已加入复习计划</span></div></div>')
                    + card('<div class="row" style="align-items:flex-start">'
                           '<span class="badge" style="width:30px;height:30px;font-size:13px">3</span>'
                           '<div><div class="h sm">继续下一张卷轴</div>'
                           '<div class="body sm" style="margin-top:5px">'
                           '建议接着学「RAG 的落地实践」，把这次的概念用到真实场景里。</div>'
                           '<div style="height:10px"></div>' + btn("召唤新副本", "sm") + "</div></div>")
                    + '<div class="spacer"></div>'
                    + btn("回到探险日志", "ghost"))

    s4 = phone("分享海报",
               head=nav("分享海报", right="保存"),
               bg="#FEFCF6",
               desc="Canvas 生成的金句海报，不含排名，避免社交压力。",
               title="海报固定 750 × 1334，含学习金句、正确率与小程序码，可直接保存转发。",
               body=card('<div style="text-align:center;padding:10px 6px">'
                         '<div class="tiny">知拾冒险社 · 冒险探险日志</div>'
                         '<div style="display:flex;justify-content:center;margin-top:6px">'
                         + yuanyuan(86) + "</div>"
                         '<div style="font-size:19px;font-weight:700;line-height:1.55;margin-top:8px">'
                         '把知识做成关卡，<br>记忆会更深。</div>'
                         '<div style="height:18px"></div>'
                         + ring(80, size=76, label="80%") +
                         '<div class="tiny" style="margin-top:10px">RAG 入门 · 5 题 · 正确率</div>'
                         '<div style="height:16px"></div>'
                         '<div class="row" style="justify-content:center;gap:6px">'
                         '<span class="pill gold">+180 XP</span><span class="pill blue">Lv.3</span></div>'
                         '<div style="height:18px"></div>'
                         '<div style="height:1px;background:#EADFC4"></div>'
                         '<div class="row" style="justify-content:center;margin-top:14px;gap:10px">'
                         '<div style="width:56px;height:56px;border-radius:10px;background:#F5EDD8;'
                         'border:1px solid #D9C6A4"></div>'
                         '<div style="text-align:left"><div style="font-size:11.5px;font-weight:600">'
                         '长按识别小程序码</div>'
                         '<div class="tiny" style="margin-top:3px">拾万千知识，闯无尽关卡</div></div>'
                         "</div></div>", "plain")
                    + '<div class="spacer"></div>'
                    + btn("保存到相册")
                    + btn("分享给微信好友", "ghost"))

    s5 = phone("海报生成中",
               head=nav("生成中"),
               bg="#FEFCF6",
               desc="Canvas 绘制是同步操作，仍需给出即时反馈。",
               title="海报绘制超过 1.5 秒时展示进度，绘制完成后再替换为预览。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:16px">'
                    + stage(150, "excited") +
                    '<div class="h">正在绘制分享海报</div>'
                    + bar(68, "blue", "width:170px") +
                    '<div class="tiny">正在拼接金句与小程序码…</div></div>'
                    '<div class="spacer"></div>')

    s6 = phone("生成失败",
               head=nav("探险日志"),
               desc="报告或海报生成失败时，保留全部答题数据。",
               title="失败文案给出具体原因与重试动作，不用「操作失败」这类无信息量的提示。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:14px">'
                    + shishi("dizzy", 96) +
                    '<div style="text-align:center"><div class="h">报告生成失败</div>'
                    '<div class="body sm" style="margin-top:8px">'
                    'AI 服务暂时繁忙，你的答题记录已经保存，不会丢失。</div></div></div>'
                    '<div class="spacer"></div>'
                    + btn("重新生成报告")
                    + btn("先看看答题详情", "ghost"))

    s7 = phone("网络异常",
               head=nav("社团大厅"),
               desc="全局断网态，任何页面都要能优雅降级。",
               title="断网时不阻塞浏览历史报告，只禁用需要联网的生成类操作。",
               body='<div class="spacer"></div>'
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:14px">'
                    + shishi("sad", 96) +
                    '<div style="text-align:center"><div class="h">网络好像断开了</div>'
                    '<div class="body sm" style="margin-top:8px">'
                    '已下载的探险日志仍可查看，召唤副本需要联网。</div></div></div>'
                    '<div class="spacer"></div>'
                    + btn("重新连接")
                    + btn("查看历史日志", "ghost"))

    s8 = phone("历史日志",
               head=nav("历史探险日志"),
               foot=tabbar(2),
               desc="所有闯关记录的入口，按时间倒序。",
               title="每条记录显示正确率与获得 XP，点击进入当时的报告，可完整回看。",
               body=card('<div class="between"><div><div class="h sm">RAG 入门闯关</div>'
                         '<div class="tiny" style="margin-top:4px">今天 14:20 · 5 题</div></div>'
                         '<div style="text-align:right"><div class="stat sm c-ok">80%</div>'
                         '<div class="tiny">+180 XP</div></div></div>', "plain")
                    + card('<div class="between"><div><div class="h sm">近代史纲要 · 第三章</div>'
                           '<div class="tiny" style="margin-top:4px">昨天 21:05 · 5 题</div></div>'
                           '<div style="text-align:right"><div class="stat sm c-ok">100%</div>'
                           '<div class="tiny">+240 XP</div></div></div>', "plain")
                    + card('<div class="between"><div><div class="h sm">Prompt 工程入门</div>'
                           '<div class="tiny" style="margin-top:4px">9 月 11 日 · 5 题</div></div>'
                           '<div style="text-align:right"><div class="stat sm c-gold">60%</div>'
                           '<div class="tiny">+110 XP</div></div></div>', "plain")
                    + card('<div class="between"><div><div class="h sm">向量数据库选型</div>'
                           '<div class="tiny" style="margin-top:4px">9 月 9 日 · 5 题</div></div>'
                           '<div style="text-align:right"><div class="stat sm c-ok">80%</div>'
                           '<div class="tiny">+175 XP</div></div></div>', "plain")
                    + '<div class="spacer"></div>'
                    + '<div style="display:flex;flex-direction:column;align-items:center;gap:6px">'
                    + shishi("sleep", 64)
                    + '<div class="tiny">已经到底了 · 共 12 份日志</div></div>')

    html = doc("03", "冒险探险日志",
               "通关之后的复盘与分享，共 8 屏。这一组承担产品的第二个核心价值——"
               "让一次闯关变成可留存、可回看、可传播的学习资产。"
               "报告只做三件事：告诉用户学得怎么样、哪里薄弱、接下来做什么。"
               "分享海报刻意不放排名，避免社交压力劝退。",
               ["正确率环形图", "三句话知识总结", "掌握 / 薄弱知识点",
                "遗忘曲线复习计划", "金句海报无排名", "8 屏"],
               grid([s1, s2, s3, s4, s5, s6, s7, s8]))
    w("03-冒险日志.html", html)


if __name__ == "__main__":
    print("generating 00-03 ...")
    build_ds()
    build_01()
    build_02()
    build_03()
    print("done.")
