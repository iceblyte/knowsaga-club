"""知拾冒险社 · 原型设计系统 (kit)
共用 CSS + 组件工厂函数。所有 HTML 原型文件由 gen_a.py / gen_b.py 调用本模块生成。

设计语言：纸与印
  1) 一切都必须是「纸上的东西」：纸、墨、印、铜 —— 不是「卡片」。
  2) 内容默认不装进圆角盒子，靠纸面明暗 / 虚实线 / 压痕分组。
  3) 全站唯一的「响亮」元素是印章（朱砂、微旋转、压在纸边）。
  4) 动效只在有意义时出现：生成中（功能性）、答题反馈（响应动作）。
  5) 层级靠材质，不靠阴影。
"""
import math

# =====================================================================
# 纸张颗粒：feTurbulence 去饱和后低透明度叠加，纯内联、无外部依赖
# =====================================================================
GRAIN = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
         "width='200' height='200'%3E%3Cfilter id='g'%3E%3CfeTurbulence "
         "type='fractalNoise' baseFrequency='.8' numOctaves='4' stitchTiles='stitch'/%3E"
         "%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E"
         "%3Crect width='200' height='200' filter='url(%23g)' opacity='.13'/%3E%3C/svg%3E\")")

CSS = r"""
*{box-sizing:border-box;-webkit-font-smoothing:antialiased;}

/* ================= 字体 =================
   拉丁与数字用 Baloo 2：圆润、暖、带一点喜剧感，呼应《为美好的世界献上祝福！》
   的调性；数字在游戏化产品里到处都是（XP / 等级 / 分数 / 进度），值得一个有个性
   的face。中文因小程序主包 2MB 上限不引入网络字体，个性改由字重、字距、行高承担。 */
:root{
  --f-disp:"Baloo 2","Segoe UI Variable Display",ui-rounded,-apple-system,"PingFang SC",sans-serif;
  --f-body:-apple-system,BlinkMacSystemFont,"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif;
  --grain:__GRAIN__;

  /* 纸与墨：明亮的黄调纸色。避开 AI 默认的 #F4F1EA —— 那个色饱和度只有 4%
     且近乎中性，读作「奶油」；这里的纸色饱和度 14%、黄调明确，再叠加纸浆颗粒，
     读作「纸」。差异化不靠压暗底色，靠材质与字体。 */
  --board:#F1E8D0;   /* 公告板 / 桌底：明亮，但黄调明确 */
  --paper:#FEFCF6;   /* 纸面：接近白，保证阅读明亮度 */
  --paper2:#F5EDD8;  /* 次级纸面 / 压痕 */
  --paper3:#EADFC4;  /* 深压痕 / 纸边 */
  --line:#C9B48D;    /* 纸上的线 */
  --ink:#2A2018;     /* 墨 */
  --ink2:#6B5A45;    /* 淡墨 */
  --ink3:#9A8870;    /* 更淡墨 */

  --seal:#A63A2E;    /* 朱砂：印章专用 */
  --magic:#2F6BD8;   /* 魔法蓝：降一档饱和，让它落在纸上像墨而不像 UI 蓝 */
  --magic-d:#1F4694;
  --gold:#C8912A;    /* 黄铜：比 emoji 金更沉 */
  --gold-d:#9C6E15;
  --ok:#2F7D4F;
  --bad:#A63A2E;
  --rare:#6D4BC4;
}

body{margin:0;color:var(--ink);font-family:var(--f-body);
  background-color:var(--board);
  background-image:
    radial-gradient(130% 90% at 10% -10%,rgba(255,255,255,.55),transparent 58%),
    radial-gradient(110% 80% at 92% 108%,rgba(120,88,38,.10),transparent 62%),
    var(--grain);
  background-attachment:fixed;}
a{color:var(--magic);text-decoration:none;}

.wrap{max-width:1300px;margin:0 auto;padding:46px 28px 96px;}

/* ================= 页头：一份归档卷宗的抬头 =================
   编号是真实的阅读顺序（00→07），所以编号有意义，不是装饰性 01/02/03。 */
.phead{margin-bottom:28px;}
.idx{display:flex;align-items:baseline;gap:8px;margin-bottom:9px;}
.idx b{font-family:var(--f-disp);font-size:21px;font-weight:800;color:var(--seal);
  letter-spacing:-.01em;line-height:1;}
.idx span{font-size:11.5px;color:var(--ink3);}
.phead h1{font-family:var(--f-disp);font-size:31px;font-weight:700;margin:0;
  letter-spacing:-.015em;line-height:1.18;color:var(--ink);}
.dbl{height:3px;border-top:1px solid var(--ink);border-bottom:1px solid var(--ink);
  margin:13px 0 15px;opacity:.5;}
.phead p{font-size:13.5px;line-height:1.85;color:var(--ink2);margin:0;max-width:68ch;}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:17px;}
/* 方形归档标签，不是圆胶囊 —— 纸上的东西有角 */
.tag{font-size:11.5px;padding:3px 9px;background:var(--paper2);color:var(--ink2);
  border-radius:2px;border:1px solid rgba(150,120,72,.32);}

.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:38px 26px;}
@media(max-width:1120px){.grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:740px){.grid{grid-template-columns:minmax(0,1fr);}}

.slot{display:flex;flex-direction:column;align-items:center;gap:11px;}
.cap{font-size:12.5px;color:var(--ink2);text-align:center;line-height:1.65;max-width:330px;}
.cap b{color:var(--ink);font-weight:600;display:block;margin-bottom:3px;font-size:13px;}
.cap .anno{display:block;margin-top:5px;font-size:11.5px;color:var(--ink3);line-height:1.6;}

/* ================= 手机：一块被钉在板上的纸 =================
   方向性硬投影 + 暖色描边，替代原先「同一个 .10 黑色柔投影」的通用卡影。 */
.phone{width:100%;max-width:332px;height:700px;background:var(--paper);
  background-image:var(--grain);
  border-radius:15px;overflow:hidden;display:flex;flex-direction:column;position:relative;
  box-shadow:0 0 0 1px rgba(120,92,48,.36),
             3px 5px 0 -1px rgba(120,92,48,.15),
             0 20px 28px -22px rgba(42,32,24,.60);}

.sbar{height:26px;display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;font-size:11px;color:var(--ink3);flex:none;
  font-family:var(--f-disp);font-weight:600;letter-spacing:.02em;}
.sbi{width:13px;height:7px;border:1px solid var(--line);border-radius:2px;margin-left:3px;display:inline-block;}

.nav{height:48px;display:flex;align-items:center;justify-content:space-between;
  padding:0 14px;flex:none;}
.nav .t{font-size:15px;font-weight:600;flex:1;text-align:center;}
.nvb{width:38px;font-size:21px;color:var(--ink2);line-height:1;}
.nvr{width:38px;text-align:right;font-size:12px;color:var(--ink3);}

.screen{flex:1;padding:6px 14px 14px;display:flex;flex-direction:column;gap:10px;
  overflow-y:auto;overflow-x:hidden;}
.screen::-webkit-scrollbar{width:4px;}
.screen::-webkit-scrollbar-thumb{background:var(--paper3);border-radius:999px;}
.screen::-webkit-scrollbar-track{background:transparent;}
.screen.center{justify-content:center;align-items:center;text-align:center;}
.screen.scroll{overflow-y:auto;}
.spacer{flex:1;}

.tabbar{flex:none;height:58px;border-top:1px dashed rgba(150,120,72,.45);display:flex;
  background:var(--paper2);padding-bottom:7px;}
.tabbar>div{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
  font-size:10.5px;color:var(--ink3);position:relative;}
.tabbar>div.on{color:var(--magic);font-weight:600;}
.tabbar>div.on::after{content:"";position:absolute;top:0;width:26px;height:2px;border-radius:0 0 2px 2px;
  background:var(--magic);}
.tabbar svg{display:block;width:21px;height:21px;flex:none;}
/* 通用线性图标语法：fi 描边、so 填充，颜色一律跟随 currentColor */
.fi{fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;
  stroke-linejoin:round;}
.so{fill:currentColor;stroke:none;}

/* ================= 材质层级 =================
   L0 裸内容      —— 什么都不装，直接落在纸上
   L1 .card 纸面  —— 阅读面。明亮纸色 + 可见细边，无外投影。读作「纸上的一个区域」
   L2 .slip 纸片  —— 真正的离散物件，硬投影 + 细描边。读作「一张单独的纸」
   L3 .stamp 印章 —— 朱砂、微旋转、压在纸边。全站唯一的响亮元素
   规则：纸面(paper)承载阅读，压痕面(paper2)承载控件与标签 —— 两者必须能分辨。 */
.card{background:var(--paper);border-radius:6px;padding:12px 13px;flex:none;
  box-shadow:inset 0 0 0 1px rgba(150,120,72,.34),inset 0 1px 0 rgba(255,255,255,.7);}
.card.plain{background:#FFFDF6;}
.card.parch{background:var(--paper2);}
.card.blue{background:#E7EFFB;box-shadow:inset 0 0 0 1px rgba(47,107,216,.32);}
.card.ok{background:#E6F2E9;box-shadow:inset 0 0 0 1px rgba(47,125,79,.34);}
.card.bad{background:#F8E9E6;box-shadow:inset 0 0 0 1px rgba(166,58,46,.34);}
.card.gold{background:#F8EFD6;box-shadow:inset 0 0 0 1px rgba(200,145,42,.36);}
.card.rare{background:#EDE8FA;box-shadow:inset 0 0 0 1px rgba(109,75,196,.32);}
.card.grow{flex:1;min-height:0;overflow:hidden;}

.slip{background:var(--paper);background-image:var(--grain);border-radius:3px;padding:13px;flex:none;
  position:relative;box-shadow:2px 3px 0 rgba(120,92,48,.20),0 0 0 1px rgba(120,92,48,.36);}

.stamp{display:inline-block;position:relative;font-family:var(--f-disp);font-weight:800;
  font-size:11.5px;letter-spacing:.09em;color:var(--seal);border:2px solid var(--seal);
  border-radius:2px;padding:2px 8px 3px;transform:rotate(-2.2deg);opacity:.9;line-height:1.35;}
.stamp::after{content:"";position:absolute;inset:2px;border:1px solid var(--seal);
  opacity:.45;border-radius:1px;}
.stamp.ok{color:var(--ok);border-color:var(--ok);}
.stamp.gold{color:var(--gold-d);border-color:var(--gold);}

.rule{height:0;border-top:1px dashed rgba(150,120,72,.45);margin:11px 0;}

.h{font-size:15px;font-weight:600;line-height:1.45;}
.h.sm{font-size:13.5px;}
.sub{font-size:11.5px;color:var(--ink3);line-height:1.55;}
.body{font-size:12.5px;line-height:1.8;color:var(--ink2);}
.body.sm{font-size:11.5px;}
.tiny{font-size:11px;color:var(--ink3);line-height:1.55;}
.strong{font-weight:600;color:var(--ink);}
.c-blue{color:var(--magic);}.c-gold{color:var(--gold-d);}.c-ok{color:var(--ok);}
.c-bad{color:var(--bad);}.c-mute{color:var(--ink3);}.c-rare{color:var(--rare);}
/* 数字统一交给 Baloo 2 —— 游戏化产品里数字承担了大量情绪 */
.num{font-family:var(--f-disp);font-weight:700;letter-spacing:-.01em;}

.btn{display:block;width:100%;border:0;border-radius:7px;background:var(--magic);color:#FFF9EA;
  font-family:var(--f-disp);font-size:15px;font-weight:700;letter-spacing:.01em;padding:11px 0;
  text-align:center;border-bottom:3px solid var(--magic-d);cursor:pointer;}
.btn.gold{background:var(--gold);border-bottom-color:var(--gold-d);color:#3D2A05;}
.btn.ok{background:var(--ok);border-bottom-color:#1F5A38;}
.btn.ghost{background:var(--paper);color:var(--ink2);border:1px solid rgba(150,120,72,.38);
  border-bottom:3px solid rgba(150,120,72,.30);}
.btn.sm{padding:8px 0;font-size:13px;border-bottom-width:2px;}
.btn.dis{background:var(--paper3);border-bottom-color:#D3C29F;color:var(--ink3);}

.row{display:flex;align-items:center;gap:8px;}
.between{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.stack{display:flex;flex-direction:column;gap:8px;}
.stack.tight{gap:6px;}

.chip{font-size:11px;padding:4px 10px;border-radius:3px;background:var(--paper2);
  color:var(--ink2);border:1px solid rgba(150,120,72,.32);white-space:nowrap;}
/* 并列项的标记：方块，不是数字编号。编号只用于真正的序列（流程 / 时间线 / 优先级），
   并列的陈述或权益用编号是纯装饰，读起来像模板。 */
.dotmark{width:6px;height:6px;border-radius:1px;background:var(--magic);flex:none;}
.dotmark.gold{background:var(--gold);}
.dotmark.ok{background:var(--ok);}
.pill{font-size:10.5px;padding:2px 7px;border-radius:3px;background:var(--paper2);
  color:var(--ink2);font-weight:600;font-family:var(--f-disp);letter-spacing:.02em;}
.pill.blue{background:#E7EFFB;color:var(--magic-d);}
.pill.gold{background:#F8EFD6;color:var(--gold-d);}
.pill.ok{background:#E6F2E9;color:var(--ok);}
.pill.bad{background:#F8E9E6;color:var(--bad);}
.pill.rare{background:#EDE8FA;color:var(--rare);}

.bar{height:8px;border-radius:2px;background:var(--paper3);overflow:hidden;}
.bar>i{display:block;height:100%;border-radius:2px;background:var(--gold);}
.bar.blue>i{background:var(--magic);}
.bar.ok>i{background:var(--ok);}
.bar.rare>i{background:var(--rare);}

/* 选项：压痕面（控件）而不是纸面 —— 才能在纸底上读出「这是可以填的」
   题号用方块而不是圆形，读作「卷宗里的一条」，而不是通用 UI 徽标 */
.opt{display:flex;align-items:center;gap:10px;padding:11px 12px;border-radius:5px;
  background:var(--paper2);box-shadow:inset 0 0 0 1px rgba(150,120,72,.30);}
.opt .k{width:22px;height:22px;border-radius:4px;background:var(--paper);
  box-shadow:inset 0 0 0 1px rgba(150,120,72,.34);color:var(--ink2);
  font-size:11.5px;display:flex;align-items:center;justify-content:center;flex:none;
  font-family:var(--f-disp);font-weight:700;}
.opt .x{font-size:12.5px;line-height:1.5;flex:1;}
.opt.sel{background:#DCE9FB;box-shadow:inset 0 0 0 1.5px var(--magic);}
.opt.sel .k{background:var(--magic);color:#FFF9EA;box-shadow:none;}
.opt.ok{background:#DFF0E4;box-shadow:inset 0 0 0 1.5px var(--ok);}
.opt.ok .k{background:var(--ok);color:#FFF9EA;box-shadow:none;}
.opt.bad{background:#F7E3DF;box-shadow:inset 0 0 0 1.5px var(--bad);}
.opt.bad .k{background:var(--bad);color:#FFF9EA;box-shadow:none;}

.avatar{width:36px;height:36px;border-radius:50%;background:#E7EFFB;
  box-shadow:inset 0 0 0 1px rgba(47,107,216,.34);flex:none;}
.avatar.gold{background:#F8EFD6;box-shadow:inset 0 0 0 1px rgba(200,145,42,.42);}
.avatar.rare{background:#EDE8FA;box-shadow:inset 0 0 0 1px rgba(109,75,196,.36);}
.avatar.sm{width:26px;height:26px;}

.field{background:var(--paper2);border:1px dashed rgba(150,120,72,.52);border-radius:5px;
  padding:12px;flex:none;}
.field.solid{border-style:solid;border-color:rgba(150,120,72,.38);}
.ph{font-size:12.5px;color:var(--ink3);line-height:1.75;}

.stat{font-family:var(--f-disp);font-size:25px;font-weight:800;line-height:1.15;letter-spacing:-.02em;}
.stat.sm{font-size:18px;}
.statlab{font-size:11px;color:var(--ink3);margin-top:3px;}

/* 列表：账本横格行，而不是一摞一模一样的圆角卡 */
.li{display:flex;align-items:center;gap:10px;padding:9px 2px;background:transparent;
  border-bottom:1px dashed rgba(150,120,72,.34);}
.li:last-child{border-bottom:0;}
.li .ico{width:28px;height:28px;border-radius:4px;background:var(--paper2);flex:none;
  display:flex;align-items:center;justify-content:center;font-size:12.5px;color:var(--ink2);
  font-family:var(--f-disp);font-weight:700;}
.li .tx{flex:1;min-width:0;}
.li .tx .n{font-size:12.5px;font-weight:600;}
.li .tx .d{font-size:11px;color:var(--ink3);margin-top:2px;}

.mask{position:absolute;inset:0;background:rgba(42,32,24,.44);display:flex;
  align-items:center;justify-content:center;padding:26px;}
.sheet{position:absolute;left:0;right:0;bottom:0;background:var(--paper);border-radius:8px 8px 0 0;
  padding:18px 16px 22px;display:flex;flex-direction:column;gap:12px;
  box-shadow:0 -3px 0 rgba(120,92,48,.18);}
.grab{width:38px;height:4px;border-radius:999px;background:var(--paper3);margin:0 auto;}

.mcircle{width:104px;height:104px;border-radius:50%;border:2px dashed var(--magic);
  display:flex;align-items:center;justify-content:center;position:relative;flex:none;opacity:.75;}
.mcircle::before{content:"";position:absolute;inset:12px;border-radius:50%;
  border:1.5px solid rgba(47,107,216,.42);}
.mcircle .core{width:34px;height:34px;border-radius:50%;background:#E7EFFB;
  border:1.5px solid var(--magic);}

.spark{position:absolute;width:6px;height:6px;border-radius:50%;background:var(--gold);}
.badge{width:62px;height:62px;border-radius:50%;background:#F8EFD6;
  box-shadow:inset 0 0 0 1.5px rgba(200,145,42,.5);display:flex;align-items:center;
  justify-content:center;font-family:var(--f-disp);font-size:20px;font-weight:800;
  color:var(--gold-d);flex:none;}
.badge.off{background:var(--paper2);box-shadow:inset 0 0 0 1.5px rgba(150,120,72,.34);color:var(--ink3);}
.badge.rare{background:#EDE8FA;box-shadow:inset 0 0 0 1.5px rgba(109,75,196,.44);color:var(--rare);}

.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;}

/* ---- 设计规范页专用 ---- */
.ds-sec{margin-bottom:40px;}
.ds-sec>h2{font-size:17px;font-weight:700;margin:0 0 6px;font-family:var(--f-disp);
  letter-spacing:-.01em;}
.ds-sec>p{font-size:13px;color:var(--ink2);margin:0 0 18px;line-height:1.8;max-width:70ch;}
.ds-row{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start;}
.sw{width:118px;}
.sw .box{height:58px;border-radius:3px;border:1px solid rgba(120,92,48,.28);}
/* 色值是字面数据，等宽是语义正确的，不是装饰 */
.sw .hx{font-size:11.5px;font-weight:600;margin-top:7px;font-family:ui-monospace,Menlo,monospace;}
.sw .nm{font-size:11px;color:var(--ink3);margin-top:2px;}
.spec{background:var(--paper);border-radius:6px;padding:18px;flex:1;min-width:260px;
  box-shadow:inset 0 0 0 1px rgba(150,120,72,.22);}
.spec h3{font-size:13px;margin:0 0 12px;color:var(--ink2);font-weight:600;}
.spec ul{margin:0;padding-left:18px;font-size:12.5px;line-height:1.95;color:var(--ink2);}

/* ================= 动效 =================
   只在两处使用：生成中（stage，功能性——它在说「正在发生什么」）
   与答题反馈（shake，响应人的动作）。静态场景一律不动。 */
@keyframes floaty{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
@keyframes twinkle{0%,100%{opacity:.25;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
@keyframes spin-r{from{transform:rotate(0)}to{transform:rotate(-360deg)}}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-2px)}75%{transform:translateX(2px)}}
.floaty{animation:floaty 3.6s ease-in-out infinite;}
.floaty.slow{animation-duration:5.4s;}
.floaty.fast{animation-duration:2.4s;}
.twinkle{animation:twinkle 2.4s ease-in-out infinite;}
.twinkle.d1{animation-delay:.5s;}
.twinkle.d2{animation-delay:1.1s;}
.spin{animation:spin 16s linear infinite;}
.spin-r{animation:spin-r 24s linear infinite;}
.shake{animation:shake .45s ease-in-out 2;}
@media(prefers-reduced-motion:reduce){.floaty,.twinkle,.spin,.spin-r,.shake{animation:none}}

/* ---------- 拾拾舞台 ---------- */
.stage{position:relative;display:flex;align-items:center;justify-content:center;flex:none;}
.stage>.spin,.stage>.spin-r{position:absolute;inset:0;}
.stage-c{position:relative;z-index:2;}
.sprite{display:block;overflow:visible;}
/* 角色行：多个角色并排时统一对齐 */
.cast{display:flex;align-items:flex-end;gap:10px;flex:none;}
.cast>div{display:flex;flex-direction:column;align-items:center;gap:5px;}
/* 鸢鸢飘行：只在「等待对方回应」这一处使用，幅度极小 */
@keyframes drift{0%,100%{transform:translate(0,0) rotate(0)}50%{transform:translate(3px,-5px) rotate(-2.5deg)}}
.drift{animation:drift 3.2s ease-in-out infinite;}
@media(prefers-reduced-motion:reduce){.drift{animation:none}}
/* 头像：圆形裁切后的角色，无外投影，靠描边定界 */
.advatar{display:block;flex:none;overflow:visible;}
/* 身份位：头像 + 姓名 + 副信息的横排 */
.who{display:flex;align-items:center;gap:9px;min-width:0;flex:1;}
.who .tx{min-width:0;}
.who .tx .n{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.who .tx .d{font-size:11px;color:var(--ink3);margin-top:2px;}

/* ---------- 卷轴输入框 ---------- */
.scrollbox{position:relative;background:var(--paper2);border-radius:4px;
  padding:16px 14px;margin:8px 0;flex:none;
  box-shadow:inset 0 0 0 1px rgba(150,120,72,.34);}
.scrollbox::before,.scrollbox::after{content:"";position:absolute;top:-7px;bottom:-7px;width:14px;
  border-radius:999px;background:#E8D2A0;box-shadow:inset 0 0 0 1px #C4A874;}
.scrollbox::before{left:-7px;}
.scrollbox::after{right:-7px;}
.scrollbox .inner{background:var(--paper);border:1px dashed rgba(150,120,72,.44);border-radius:3px;
  padding:12px;min-height:100%;display:flex;flex-direction:column;justify-content:space-between;}
"""


# ---------- 页面外壳 ----------
def doc(num, name, desc, tags, body):
    tg = "".join('<span class="tag">' + t + "</span>" for t in tags)
    return ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
            "<meta charset=\"UTF-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>" + name + " · 知拾冒险社原型</title>\n"
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link href="https://fonts.googleapis.com/css2?'
            'family=Baloo+2:wght@500;600;700;800&display=swap" rel="stylesheet">\n'
            "<style>" + CSS + "</style>\n</head>\n<body>\n"
            '<div class="wrap">\n'
            '<header class="phead">\n'
            '<div class="idx"><b>' + num + "</b><span>卷宗</span></div>\n"
            "<h1>" + name + "</h1>\n"
            '<div class="dbl"></div>\n'
            "<p>" + desc + "</p>\n"
            '<div class="tags">' + tg + "</div>\n"
            "</header>\n"
            + body +
            "\n</div>\n</body>\n</html>\n")


# ---------- 手机外壳 ----------
def sbar(t="9:41"):
    return ('<div class="sbar"><span>' + t + '</span><span>'
            '<span class="sbi"></span><span class="sbi"></span><span class="sbi"></span>'
            "</span></div>")


def nav(title, back=True, right=""):
    lb = '<span class="nvb">&#8249;</span>' if back else '<span class="nvb"></span>'
    return ('<div class="nav">' + lb + '<span class="t">' + title + "</span>"
            '<span class="nvr">' + right + "</span></div>")


# 底部标签栏：5 个一级入口。
# 每个入口配一个可区分的图形 —— 5 个标签只靠文字认路太慢，且原先所有标签
# 共用同一个灰方块 `dot`，等于没有图标。active 索引即本列表下标。
TAB_ITEMS = [
    ("社团大厅",
     '<path class="fi" d="M3 9.4 10 3.6l7 5.8"/><path class="fi" d="M5.3 8.6v7.8h9.4V8.6"/>'
     '<path class="fi" d="M8.2 16.4v-4.1h3.6v4.1"/>'),
    ("卷轴工坊",
     '<path class="fi" d="M5.2 2.8h6.2l3.4 3.4v11H5.2z"/><path class="fi" d="M11.4 2.8v3.4h3.4"/>'
     '<path class="fi" d="M10 10.4v4M8 12.4h4"/>'),
    ("冒险日志",
     '<path class="fi" d="M10 5.8C8.5 4.6 6.3 4.2 3.7 4.4v10.8c2.6-.2 4.8.2 6.3 1.4 1.5-1.2 3.7-1.6 '
     '6.3-1.4V4.4C13.7 4.2 11.5 4.6 10 5.8z"/><path class="fi" d="M10 5.8v10.8"/>'),
    ("公会社交",
     '<circle class="fi" cx="7.6" cy="7.4" r="2.7"/>'
     '<path class="fi" d="M3.3 16.4c0-2.7 1.9-4.6 4.3-4.6s4.3 1.9 4.3 4.6"/>'
     '<circle class="fi" cx="14.1" cy="8.3" r="2.1"/>'
     '<path class="fi" d="M12.7 12.5c1.9.3 3.3 1.9 3.3 3.9"/>'),
    ("我的",
     '<circle class="fi" cx="10" cy="7" r="3"/>'
     '<path class="fi" d="M4.7 16.9c0-3.1 2.4-5.4 5.3-5.4s5.3 2.3 5.3 5.4"/>'),
]


def tabbar(active=0):
    out = []
    for i, (n, ico) in enumerate(TAB_ITEMS):
        cls = ' class="on"' if i == active else ""
        out.append("<div" + cls + '><svg viewBox="0 0 20 20" aria-hidden="true">'
                   + ico + "</svg>" + n + "</div>")
    return '<div class="tabbar">' + "".join(out) + "</div>"


def phone(cap, body, head="", foot="", title="", desc="", bg=""):
    st = ' style="background:' + bg + '"' if bg else ""
    return ('<figure class="slot">\n<div class="phone">\n'
            + sbar() + head + '<div class="screen"' + st + ">" + body + "</div>" + foot +
            "\n</div>\n<figcaption class=\"cap\"><b>" + cap + "</b>"
            + desc + ("<span class=\"anno\">" + title + "</span>" if title else "")
            + "</figcaption>\n</figure>")


def grid(items):
    return '<div class="grid">\n' + "\n".join(items) + "\n</div>"


# ---------- 组件 ----------
def card(inner, cls="", style=""):
    c = "card" + (" " + cls if cls else "")
    s = ' style="' + style + '"' if style else ""
    return '<div class="' + c + '"' + s + ">" + inner + "</div>"


def slip(inner, cls="", style=""):
    """L2 纸片：真正的离散物件（任务令 / 结算单）。"""
    c = "slip" + (" " + cls if cls else "")
    s = ' style="' + style + '"' if style else ""
    return '<div class="' + c + '"' + s + ">" + inner + "</div>"


def stamp(text, cls=""):
    """L3 印章：全站唯一的响亮元素。"""
    c = "stamp" + (" " + cls if cls else "")
    return '<span class="' + c + '">' + text + "</span>"


def rule():
    return '<div class="rule"></div>'


def btn(text, cls=""):
    c = "btn" + (" " + cls if cls else "")
    return '<button class="' + c + '">' + text + "</button>"


def opt(k, text, cls=""):
    c = "opt" + (" " + cls if cls else "")
    return ('<div class="' + c + '"><span class="k">' + k + '</span>'
            '<span class="x">' + text + "</span></div>")


def bar(pct, cls="", style=""):
    c = "bar" + (" " + cls if cls else "")
    s = ' style="' + style + '"' if style else ""
    return '<div class="' + c + '"' + s + '><i style="width:' + str(pct) + '%"></i></div>'


def ring(pct, color="#2F7D4F", size=84, stroke=9, label=None, track="#E6D6B4", lab_size=19,
         sub=None, sub_size=8.5, tint=True):
    """环形进度。环心默认是空的，但只要给了 label 就一定要给 sub ——
    单独一个大数字读不出「这是什么」，配一行小字说明才成立。
    tint 会在环内铺一层极淡的主色，避免环心显得空荡。"""
    r = (size - stroke) / 2.0
    c = 2 * 3.14159265 * r
    off = c * (1 - pct / 100.0)
    cx = cy = size / 2.0
    txt = ""
    if tint:
        txt += ('<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="'
                + str(round(r - stroke / 2.0 - 1, 1)) + '" fill="' + color + '" opacity=".09"/>')
    if label is not None:
        dy = -3.6 if sub else 0
        txt += ('<text x="' + str(cx) + '" y="' + str(cy + dy) + '" text-anchor="middle" '
                'dominant-baseline="central" font-size="' + str(lab_size) + '" '
                'font-weight="800" fill="#2A2018" '
                'font-family="Baloo 2, sans-serif">' + label + "</text>")
    if sub:
        txt += ('<text x="' + str(cx) + '" y="' + str(cy + lab_size * 0.62 + 2) + '" '
                'text-anchor="middle" dominant-baseline="central" font-size="' + str(sub_size)
                + '" font-weight="600" fill="#8A7A62">' + sub + "</text>")
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 '
            + str(size) + " " + str(size) + '" style="flex:none">'
            '<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="' + str(r) + '" fill="none" stroke="'
            + track + '" stroke-width="' + str(stroke) + '"/>'
            '<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="' + str(r) + '" fill="none" stroke="'
            + color + '" stroke-width="' + str(stroke) + '" stroke-dasharray="' + str(round(c, 1))
            + '" stroke-dashoffset="' + str(round(off, 1)) + '" stroke-linecap="round" '
            'transform="rotate(-90 ' + str(cx) + " " + str(cy) + ')"/>' + txt + "</svg>")


def li(ico, name, desc, right="", cls=""):
    c = "li" + (" " + cls if cls else "")
    r = '<span class="pill">' + right + "</span>" if right else ""
    return ('<div class="' + c + '"><span class="ico">' + ico + '</span>'
            '<span class="tx"><span class="n">' + name + '</span>'
            '<span class="d">' + desc + "</span></span>" + r + "</div>")


def magic(size=104):
    return ('<div class="mcircle" style="width:' + str(size) + "px;height:" + str(size)
            + 'px"><span class="core"></span>'
            '<span class="spark" style="top:6px;left:50%"></span>'
            '<span class="spark" style="bottom:10px;right:14px"></span>'
            '<span class="spark" style="bottom:16px;left:12px"></span></div>')


# =====================================================================
# SVG 卡通形象系统
# =====================================================================
INK = "#2A2018"
AQUA = "#E4F0FB"
AQUA_LINE = "#2F6BD8"
AQUA_WING = "#C2DFF7"
WING_LINE = "#7FA9D8"
BLUSH = "#E8A0AE"
GOLD = "#C8912A"
GOLD_LINE = "#9C6E15"
CREAM = "#FAF3E0"
SEAL = "#A63A2E"


def star_path(cx, cy, r, fill, stroke=None, sw=1.2, pts=5):
    out = []
    for i in range(pts * 2):
        a = -math.pi / 2 + i * math.pi / pts
        rr = r if i % 2 == 0 else r * 0.42
        out.append("%.2f,%.2f" % (cx + rr * math.cos(a), cy + rr * math.sin(a)))
    s = '<polygon points="' + " ".join(out) + '" fill="' + fill + '"'
    if stroke:
        s += ' stroke="' + stroke + '" stroke-width="' + str(sw) + '" stroke-linejoin="round"'
    return s + "/>"


def sparkle(size=14, cls="twinkle", color=GOLD):
    return ('<svg class="' + cls + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 20 20" style="flex:none">' + star_path(10, 10, 9, color, pts=4) + "</svg>")


def _eyes(kind):
    if kind == "happy":
        return ('<path d="M33 58c2.5-4.8 8.5-4.8 11 0" fill="none" stroke="' + INK
                + '" stroke-width="2.8" stroke-linecap="round"/>'
                '<path d="M56 58c2.5-4.8 8.5-4.8 11 0" fill="none" stroke="' + INK
                + '" stroke-width="2.8" stroke-linecap="round"/>')
    if kind == "star":
        return star_path(39, 57, 6.6, GOLD, GOLD_LINE) + star_path(61, 57, 6.6, GOLD, GOLD_LINE)
    if kind == "closed":
        return ('<path d="M33 57c2.5 4.6 8.5 4.6 11 0" fill="none" stroke="' + INK
                + '" stroke-width="2.8" stroke-linecap="round"/>'
                '<path d="M56 57c2.5 4.6 8.5 4.6 11 0" fill="none" stroke="' + INK
                + '" stroke-width="2.8" stroke-linecap="round"/>')
    if kind == "think":
        return ('<ellipse cx="39" cy="56" rx="5.6" ry="6.8" fill="' + INK + '"/>'
                '<circle cx="37.2" cy="53.2" r="2.2" fill="#FFF"/>'
                '<path d="M56 58.5c2.5-4.2 8.5-4.2 11 0" fill="none" stroke="' + INK
                + '" stroke-width="2.6" stroke-linecap="round"/>')
    if kind == "sad":
        return ('<ellipse cx="39" cy="58.5" rx="5.2" ry="6" fill="' + INK + '"/>'
                '<ellipse cx="61" cy="58.5" rx="5.2" ry="6" fill="' + INK + '"/>'
                '<circle cx="37.4" cy="56" r="2" fill="#FFF"/><circle cx="59.4" cy="56" r="2" fill="#FFF"/>'
                '<path d="M39.5 50.5l-7 2M60.5 50.5l7 2" stroke="' + INK
                + '" stroke-width="1.8" stroke-linecap="round"/>')
    if kind == "dizzy":
        return ('<circle cx="39" cy="57" r="5" fill="none" stroke="' + INK + '" stroke-width="2"/>'
                '<circle cx="61" cy="57" r="5" fill="none" stroke="' + INK + '" stroke-width="2"/>'
                '<path d="M35.5 57h7M57.5 57h7" stroke="' + INK + '" stroke-width="1.6"/>')
    return ('<ellipse cx="39" cy="57" rx="5.6" ry="7.2" fill="' + INK + '"/>'
            '<ellipse cx="61" cy="57" rx="5.6" ry="7.2" fill="' + INK + '"/>'
            '<circle cx="37.2" cy="53.8" r="2.3" fill="#FFF"/>'
            '<circle cx="59.2" cy="53.8" r="2.3" fill="#FFF"/>')


def _mouth(kind):
    if kind == "open":
        return '<path d="M44 70q6 9 12 0z" fill="' + INK + '"/>'
    if kind == "flat":
        return '<path d="M45 72h10" fill="none" stroke="' + INK + '" stroke-width="2.4" stroke-linecap="round"/>'
    if kind == "frown":
        return '<path d="M45 74q5-5 10 0" fill="none" stroke="' + INK + '" stroke-width="2.4" stroke-linecap="round"/>'
    if kind == "small":
        return '<circle cx="50" cy="72" r="2.6" fill="' + INK + '"/>'
    return '<path d="M45 70.5q5 5.5 10 0" fill="none" stroke="' + INK + '" stroke-width="2.4" stroke-linecap="round"/>'


SPRITE_STATES = {
    "normal": ("normal", "smile", ""),
    "happy": ("happy", "open", ""),
    "excited": ("star", "open", "sparkle"),
    "win": ("star", "open", "sparkle"),
    "think": ("think", "flat", ""),
    "sad": ("sad", "frown", ""),
    "sleep": ("closed", "small", "zzz"),
    "dizzy": ("dizzy", "flat", ""),
}


def shishi(state="normal", size=64, cls=""):
    """引导精灵「拾拾」——水蓝色小精灵，表情随场景切换。

    默认不做动画：静态场景（档案页、知识库列表、空态）里的精灵不该无差别漂浮。
    需要动的时候显式传 cls，例如 stage() 内部传 "floaty"。"""
    e, m, extra = SPRITE_STATES.get(state, SPRITE_STATES["normal"])
    wings = ('<path d="M21 57C9 48 0 57 4 68c3 8 12 9 17 3 3-3 2-10 0-14z" fill="' + AQUA_WING
             + '" stroke="' + WING_LINE + '" stroke-width="2" stroke-linejoin="round"/>'
             '<path d="M79 57c12-9 21 0 17 11-3 8-12 9-17 3-3-3-2-10 0-14z" fill="' + AQUA_WING
             + '" stroke="' + WING_LINE + '" stroke-width="2" stroke-linejoin="round"/>')
    feet = ('<ellipse cx="40" cy="89" rx="8" ry="5" fill="' + AQUA + '" stroke="' + AQUA_LINE
            + '" stroke-width="2.2"/>'
            '<ellipse cx="60" cy="89" rx="8" ry="5" fill="' + AQUA + '" stroke="' + AQUA_LINE
            + '" stroke-width="2.2"/>')
    antenna = ('<path d="M50 27C50 18 53 13 58 9" fill="none" stroke="' + AQUA_LINE
               + '" stroke-width="2.2" stroke-linecap="round"/>'
               '<circle cx="59" cy="7.5" r="4.6" fill="' + GOLD + '" stroke="' + GOLD_LINE
               + '" stroke-width="1.4"/>')
    body = ('<path d="M50 25c19 0 33 16 33 34s-14 32-33 32-33-14-33-32 14-34 33-34z" fill="'
            + AQUA + '" stroke="' + AQUA_LINE + '" stroke-width="2.6" stroke-linejoin="round"/>')
    belly = '<ellipse cx="50" cy="68" rx="18" ry="15" fill="#FFFFFF" opacity=".85"/>'
    blush = ('<ellipse cx="27" cy="66" rx="6" ry="3.6" fill="' + BLUSH + '" opacity=".8"/>'
             '<ellipse cx="73" cy="66" rx="6" ry="3.6" fill="' + BLUSH + '" opacity=".8"/>')
    prop = ""
    if extra == "sparkle":
        prop = ('<g class="twinkle">' + star_path(9, 26, 6, GOLD, pts=4) + "</g>"
                '<g class="twinkle d1">' + star_path(93, 40, 5, GOLD, pts=4) + "</g>"
                '<g class="twinkle d2">' + star_path(88, 82, 4.4, GOLD, pts=4) + "</g>")
    elif extra == "zzz":
        prop = ('<text class="twinkle" x="78" y="24" font-size="15" font-weight="700" fill="'
                + AQUA_LINE + '">z</text>'
                '<text class="twinkle d1" x="89" y="13" font-size="11" font-weight="700" fill="'
                + WING_LINE + '">z</text>')
    c = ("sprite " + cls).strip()
    return ('<svg class="' + c + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 100 100" role="img" aria-label="小精灵拾拾">'
            + wings + feet + antenna + body + belly + blush + _eyes(e) + _mouth(m)
            + prop + "</svg>")


def magic_circle(size=150, cls="spin"):
    ticks = []
    for i in range(12):
        a = i * math.pi / 6
        ticks.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2"/>'
                     % (60 + 54 * math.cos(a), 60 + 54 * math.sin(a),
                        60 + 48 * math.cos(a), 60 + 48 * math.sin(a), WING_LINE))
    for i in range(4):
        a = i * math.pi / 2 + math.pi / 4
        ticks.append(star_path(60 + 40 * math.cos(a), 60 + 40 * math.sin(a), 5, "#B9D5F2", pts=4))
    return ('<svg class="' + cls + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 120 120" fill="none">'
            '<circle cx="60" cy="60" r="54" stroke="' + WING_LINE + '" stroke-width="1.2" stroke-dasharray="6 7"/>'
            '<circle cx="60" cy="60" r="44" stroke="#B9D5F2" stroke-width="1"/>'
            '<circle cx="60" cy="60" r="30" stroke="#B9D5F2" stroke-width="1" stroke-dasharray="3 5"/>'
            + "".join(ticks) + "</svg>")


def stage(size=150, state="happy", speed="", circle=True):
    """魔法阵 + 拾拾 的组合舞台。动效在这里是功能性的——它在说「正在发生什么」。"""
    c = magic_circle(size) if circle else ""
    return ('<div class="stage" style="width:' + str(size) + "px;height:" + str(size) + 'px">'
            + c + '<div class="stage-c">' + shishi(state, int(size * 0.46), "floaty" + speed)
            + "</div></div>")


def coin(size=26):
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 32 32" style="flex:none">'
            '<circle cx="16" cy="16" r="13" fill="' + GOLD + '" stroke="' + GOLD_LINE + '" stroke-width="2"/>'
            '<circle cx="16" cy="16" r="8.6" fill="none" stroke="#F7EBCB" stroke-width="1.4"/>'
            + star_path(16, 16, 5.4, "#F7EBCB", pts=4) + "</svg>")


def chest(size=44, open_=True):
    glow = ""
    if open_:
        glow = (star_path(16, 10, 5, "#F7EBCB", GOLD_LINE) + star_path(26, 7, 3.4, "#F7EBCB", GOLD_LINE)
                + star_path(8, 8, 3, "#F7EBCB", GOLD_LINE))
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 44 44" '
            'style="flex:none">' + glow
            + '<path d="M5 21c0-7 5-12 12-12h10c7 0 12 5 12 12z" fill="#C68B22" stroke="#8F6210" '
              'stroke-width="2" stroke-linejoin="round"/>'
            + '<rect x="5" y="20" width="34" height="7" fill="#AE7A1C" stroke="#8F6210" stroke-width="2"/>'
            + '<path d="M7 27h30v10a3 3 0 0 1-3 3H10a3 3 0 0 1-3-3z" fill="#AE7A1C" stroke="#8F6210" '
              'stroke-width="2" stroke-linejoin="round"/>'
            + '<rect x="14" y="20" width="3" height="20" fill="#8F6210" opacity=".55"/>'
            + '<rect x="27" y="20" width="3" height="20" fill="#8F6210" opacity=".55"/>'
            + '<rect x="18" y="23" width="8" height="11" rx="2" fill="' + GOLD + '" stroke="#8F6210" '
              'stroke-width="1.6"/>'
            + '<circle cx="22" cy="28" r="1.7" fill="#6B4408"/>'
            + '<path d="M22 29v3" stroke="#6B4408" stroke-width="1.6" stroke-linecap="round"/>'
            + "</svg>")


def medal(size=44, kind="gold"):
    fill, line = (GOLD, GOLD_LINE) if kind == "gold" else ("#B9A2EE", "#6D4BC4")
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 44 44" style="flex:none">'
            '<path d="M15 4l7 14-7 4-5-14z" fill="#A63A2E" stroke="#7A2820" stroke-width="1.6" stroke-linejoin="round"/>'
            '<path d="M29 4l-7 14 7 4 5-14z" fill="' + AQUA_LINE + '" stroke="#1F4694" stroke-width="1.6" stroke-linejoin="round"/>'
            '<circle cx="22" cy="27" r="13" fill="' + fill + '" stroke="' + line + '" stroke-width="2"/>'
            '<circle cx="22" cy="27" r="8.6" fill="none" stroke="#F7EBCB" stroke-width="1.4"/>'
            + star_path(22, 27, 5.6, "#F7EBCB", pts=5) + "</svg>")


def scroll_icon(size=28, color="#E8D2A0", line="#C4A874"):
    return ('<svg width="' + str(size) + '" height="' + str(size) + '" viewBox="0 0 40 40" style="flex:none">'
            '<rect x="11" y="7" width="18" height="26" rx="2" fill="' + CREAM + '" stroke="' + line + '" stroke-width="1.6"/>'
            '<path d="M15 14h10M15 19h10M15 24h6" stroke="' + line + '" stroke-width="1.6" stroke-linecap="round"/>'
            '<rect x="6" y="5" width="7" height="30" rx="3.5" fill="' + color + '" stroke="' + line + '" stroke-width="1.6"/>'
            '<rect x="27" y="5" width="7" height="30" rx="3.5" fill="' + color + '" stroke="' + line + '" stroke-width="1.6"/>'
            "</svg>")


def scrollbox(inner, grow=False):
    st = "flex:1;min-height:0;" if grow else ""
    return ('<div class="scrollbox" style="' + st + '"><div class="inner">' + inner + "</div></div>")


def coinbar(text, cls="pill gold"):
    return '<span class="' + cls + '" style="display:inline-flex;align-items:center;gap:4px">' \
           + coin(13) + text + "</span>"


# =====================================================================
# 角色谱系 Cast
# ---------------------------------------------------------------------
# 四个角色 + 一套冒险者头像，与拾拾共用同一套线稿语言：墨线描边、平涂、
# 无渐变、纯 path。分工不重叠 —— 每个角色只负责一个语义域，避免「到处
# 贴吉祥物」。剪影刻意互相区分，小尺寸下靠轮廓即可辨认：
#   拾拾 圆润       墨墨 圆润 + 耳羽      鸢鸢 全直边折面      铜宝 方正箱体
# =====================================================================
OWL_BODY = "#EBD6AC"   # 墨墨 · 羽
OWL_LINE = "#8A6534"   # 墨墨 · 线
OWL_WING = "#D6B87F"   # 墨墨 · 翅
OWL_BELLY = "#FBF3E0"  # 墨墨 · 腹
OWL_BEAK = "#C8912A"   # 墨墨 · 喙
OWL_DEEP = "#9C6E15"

PAPER_F = "#FDF9EE"    # 鸢鸢 · 正面
PAPER_S = "#E9DCBB"    # 鸢鸢 · 折面阴影
PAPER_L = "#C2AC85"    # 鸢鸢 · 折线

WOOD = "#C68B22"       # 铜宝 · 木
WOOD_D = "#AE7A1C"     # 铜宝 · 木深
WOOD_LINE = "#8F6210"  # 铜宝 · 箍
WOOD_DARK = "#4A3416"  # 铜宝 · 箱内

_AVID = [0]


def _aid():
    _AVID[0] += 1
    return "av" + str(_AVID[0])


# ---------------- 墨墨 · 猫头鹰书灵 ----------------
OWL_STATES = {
    "normal": ("normal", "shut"),
    "happy": ("happy", "open"),
    "think": ("think", "shut"),
    "sad": ("sad", "shut"),
}


def _owl_eyes(kind):
    if kind == "happy":
        return ('<path d="M29.5 51.5c3.3-6.6 10.7-6.6 14 0" fill="none" stroke="' + INK
                + '" stroke-width="3.2" stroke-linecap="round"/>'
                '<path d="M56.5 51.5c3.3-6.6 10.7-6.6 14 0" fill="none" stroke="' + INK
                + '" stroke-width="3.2" stroke-linecap="round"/>')
    if kind == "think":
        return ('<circle cx="38.8" cy="50" r="7" fill="' + INK + '"/>'
                '<circle cx="66.8" cy="50" r="7" fill="' + INK + '"/>'
                '<circle cx="36.6" cy="47.2" r="2.4" fill="#FFF"/>'
                '<circle cx="64.6" cy="47.2" r="2.4" fill="#FFF"/>'
                '<path d="M28 39.5l9-3" stroke="' + OWL_LINE + '" stroke-width="2.6" stroke-linecap="round"/>')
    if kind == "sad":
        return ('<circle cx="36" cy="51" r="6.2" fill="' + INK + '"/>'
                '<circle cx="64" cy="51" r="6.2" fill="' + INK + '"/>'
                '<circle cx="33.8" cy="48.6" r="2.2" fill="#FFF"/>'
                '<circle cx="61.8" cy="48.6" r="2.2" fill="#FFF"/>'
                '<path d="M28.5 39.5l8.5 4.5M71.5 39.5l-8.5 4.5" stroke="' + OWL_LINE
                + '" stroke-width="2.6" stroke-linecap="round"/>')
    return ('<circle cx="36" cy="50" r="7.6" fill="' + INK + '"/>'
            '<circle cx="64" cy="50" r="7.6" fill="' + INK + '"/>'
            '<circle cx="33.6" cy="47" r="2.6" fill="#FFF"/>'
            '<circle cx="61.6" cy="47" r="2.6" fill="#FFF"/>')


def momo(state="normal", size=64, cls=""):
    """墨墨 · 猫头鹰书灵。负责「知识」这一语义域：讲解、复盘、错题、知识库。

    圆框金丝眼镜是「书灵」最直接的符号，且在任意尺寸下都能读出。
    耳羽提供与拾拾（无耳羽）的剪影区分。"""
    e, m = OWL_STATES.get(state, OWL_STATES["normal"])
    tufts = ('<path d="M34 34 24 12l11 9z" fill="' + OWL_BODY + '" stroke="' + OWL_LINE
             + '" stroke-width="2.4" stroke-linejoin="round"/>'
             '<path d="M66 34 76 12l-11 9z" fill="' + OWL_BODY + '" stroke="' + OWL_LINE
             + '" stroke-width="2.4" stroke-linejoin="round"/>')
    wings = ('<path d="M25 60c-9 2-15 11-15 19 0 6 4 9 9 8 8-1 13-10 14-18 1-6-2-10-8-9z" fill="'
             + OWL_WING + '" stroke="' + OWL_LINE + '" stroke-width="2.2" stroke-linejoin="round"/>'
             '<path d="M75 60c9 2 15 11 15 19 0 6-4 9-9 8-8-1-13-10-14-18-1-6 2-10 8-9z" fill="'
             + OWL_WING + '" stroke="' + OWL_LINE + '" stroke-width="2.2" stroke-linejoin="round"/>')
    feet = ('<ellipse cx="39" cy="89" rx="7.5" ry="4.6" fill="' + OWL_BEAK + '" stroke="' + OWL_DEEP
            + '" stroke-width="1.8"/>'
            '<ellipse cx="61" cy="89" rx="7.5" ry="4.6" fill="' + OWL_BEAK + '" stroke="' + OWL_DEEP
            + '" stroke-width="1.8"/>')
    body = ('<ellipse cx="50" cy="56" rx="30" ry="32" fill="' + OWL_BODY + '" stroke="' + OWL_LINE
            + '" stroke-width="2.6"/>')
    belly = '<ellipse cx="50" cy="74" rx="16" ry="11" fill="' + OWL_BELLY + '"/>'
    glass = ('<circle cx="36" cy="50" r="11" fill="none" stroke="' + OWL_DEEP + '" stroke-width="2.4"/>'
             '<circle cx="64" cy="50" r="11" fill="none" stroke="' + OWL_DEEP + '" stroke-width="2.4"/>'
             '<path d="M47 50h6" stroke="' + OWL_DEEP + '" stroke-width="2.4" stroke-linecap="round"/>')
    beak = ('<path d="M50 58.5 44.4 65.6 50 73 55.6 65.6Z" fill="' + OWL_BEAK + '" stroke="'
            + OWL_DEEP + '" stroke-width="2" stroke-linejoin="round"/>')
    if m == "open":
        beak += ('<path d="M45.2 65.8h9.6" stroke="' + OWL_DEEP
                 + '" stroke-width="1.6" opacity=".7"/>')
    blush = ('<ellipse cx="26" cy="63" rx="5" ry="3.2" fill="' + BLUSH + '" opacity=".75"/>'
             '<ellipse cx="74" cy="63" rx="5" ry="3.2" fill="' + BLUSH + '" opacity=".75"/>')
    c = ("sprite " + cls).strip()
    return ('<svg class="' + c + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 100 100" role="img" aria-label="猫头鹰书灵墨墨">'
            + tufts + wings + feet + body + belly + glass + _owl_eyes(e) + beak + blush + "</svg>")


# ---------------- 鸢鸢 · 折纸信使 ----------------
def _seal_mark(cx, cy, r=5.2):
    """朱砂印：实心圆 + 内圈。不用叉号——小尺寸下会读成「禁止」符号。"""
    return ('<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="' + str(r) + '" fill="'
            + SEAL + '"/>'
            '<circle cx="' + str(cx) + '" cy="' + str(cy) + '" r="' + str(round(r * 0.48, 2))
            + '" fill="none" stroke="' + CREAM + '" stroke-width="1.3"/>')


def yuanyuan(size=64, cls="", face=True):
    """鸢鸢 · 折纸信使。负责「社交 / 传递」语义域：邀请、等待、分享、提醒。

    一张折纸——把全站的材质主题「纸」直接画成角色本身。
    全直边折面，与圆润的拾拾、墨墨形成剪影区分；下折面用阴影色区分正反，
    一眼能读出「这是折起来的纸」。"""
    far = ('<path d="M92 20 40 62 52 88Z" fill="' + PAPER_S + '" stroke="' + PAPER_L
           + '" stroke-width="2.2" stroke-linejoin="round"/>')
    near = ('<path d="M92 20 8 52 40 62Z" fill="' + PAPER_F + '" stroke="' + PAPER_L
            + '" stroke-width="2.2" stroke-linejoin="round"/>'
            '<path d="M92 20 40 62" stroke="' + PAPER_L
            + '" stroke-width="1.4" opacity=".55" fill="none"/>'
            '<path d="M8 52 56 44" stroke="' + PAPER_L
            + '" stroke-width="1.1" opacity=".38" fill="none"/>')
    seal = _seal_mark(33, 52, 5)
    fc = ""
    if face:
        fc = ('<circle cx="66" cy="38" r="3.4" fill="' + INK + '"/>'
              '<circle cx="76" cy="30" r="3.4" fill="' + INK + '"/>'
              '<circle cx="64.8" cy="36.8" r="1.2" fill="#FFF"/>'
              '<circle cx="74.8" cy="28.8" r="1.2" fill="#FFF"/>'
              '<path d="M68 44q4 3.6 8-1.4" fill="none" stroke="' + INK
              + '" stroke-width="1.8" stroke-linecap="round"/>')
    c = ("sprite " + cls).strip()
    return ('<svg class="' + c + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 100 100" role="img" aria-label="折纸信使鸢鸢">'
            + far + near + seal + fc + "</svg>")


# ---------------- 铜宝 · 宝箱怪 ----------------
def tongbao(size=56, cls="", open_=True, spark=True):
    """铜宝 · 宝箱怪。负责「收获 / 奖励」语义域：结算、金币、通行证、支付。

    比 chest() 多一层「它是活的」：箱盖绕左铰链后掀，两只眼睛从箱口探出来。
    眼睛画在箱体之后、盖子之前，才能正确落在箱口那道缝里。"""
    rot = -30 if open_ else 0
    glow = ""
    if spark:
        glow = ('<g class="twinkle">' + star_path(15, 30, 6, GOLD, pts=4) + "</g>"
                '<g class="twinkle d1">' + star_path(88, 26, 5, GOLD, pts=4) + "</g>"
                '<g class="twinkle d2">' + star_path(84, 76, 4.4, GOLD, pts=4) + "</g>")
    eyes = ""
    if open_:
        eyes = ('<rect x="18" y="38" width="64" height="18" rx="3" fill="' + WOOD_DARK + '"/>'
                '<ellipse cx="40" cy="48" rx="6.6" ry="7" fill="' + INK + '"/>'
                '<ellipse cx="60" cy="48" rx="6.6" ry="7" fill="' + INK + '"/>'
                '<circle cx="37.6" cy="45.2" r="2.3" fill="#FFF"/>'
                '<circle cx="57.6" cy="45.2" r="2.3" fill="#FFF"/>')
    box = ('<path d="M12 52h76v30a6 6 0 0 1-6 6H18a6 6 0 0 1-6-6z" fill="' + WOOD_D
           + '" stroke="' + WOOD_LINE + '" stroke-width="2.2" stroke-linejoin="round"/>'
           '<rect x="22" y="52" width="5" height="36" fill="' + WOOD_LINE + '" opacity=".38"/>'
           '<rect x="73" y="52" width="5" height="36" fill="' + WOOD_LINE + '" opacity=".38"/>'
           '<rect x="42" y="60" width="16" height="15" rx="2.5" fill="' + GOLD + '" stroke="'
           + WOOD_LINE + '" stroke-width="1.8"/>'
           '<circle cx="50" cy="66" r="2.1" fill="' + WOOD_LINE + '"/>'
           '<path d="M50 67.8v3.6" stroke="' + WOOD_LINE + '" stroke-width="1.7" '
           'stroke-linecap="round"/>')
    lid = ('<g transform="rotate(' + str(rot) + ' 12 52)">'
           '<path d="M12 52c0-13 17-22 38-22s38 9 38 22z" fill="' + WOOD + '" stroke="'
           + WOOD_LINE + '" stroke-width="2.2" stroke-linejoin="round"/>'
           '<rect x="23" y="34" width="5" height="18" fill="' + WOOD_LINE + '" opacity=".45"/>'
           '<rect x="72" y="34" width="5" height="18" fill="' + WOOD_LINE + '" opacity=".45"/>'
           '<rect x="41" y="44" width="18" height="9" rx="2" fill="' + GOLD + '" stroke="'
           + WOOD_LINE + '" stroke-width="1.8"/></g>')
    c = ("sprite " + cls).strip()
    return ('<svg class="' + c + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 100 100" role="img" aria-label="宝箱怪铜宝">'
            + glow + eyes + box + lid + "</svg>")


# ---------------- 冒险者头像 ----------------
AV = {
    "apprentice": ("#DCE9FB", "#7FA9D8", "#2F6BD8"),
    "ranger": ("#DFF0E4", "#7FB894", "#2F7D4F"),
    "mage": ("#EDE8FA", "#A695E0", "#6D4BC4"),
    "knight": ("#E5EBF3", "#93A6BE", "#4A6484"),
    "scholar": ("#F8EFD6", "#D6B25E", "#9C6E15"),
    "artisan": ("#F5E5D2", "#C79A6A", "#96603A"),
}
AV_ORDER = ["apprentice", "ranger", "mage", "knight", "scholar", "artisan"]
AV_NAME = {"apprentice": "学徒", "ranger": "游侠", "mage": "法师",
           "knight": "骑士", "scholar": "学者", "artisan": "工匠"}
SKIN = "#FBEBD9"
SKIN_L = "#C9A583"


# 发型基底：外弧贴着颅顶，内缘收成一道刘海。所有款式共用，再叠各自的头饰。
HAIR_D = ("M28.5 47A21.5 21.5 0 0 1 71.5 47C64.5 41.5 58.5 38.5 50 38.5"
          "C41.5 38.5 35.5 41.5 28.5 47Z")


def adv_avatar(kind="apprentice", size=38, cls=""):
    """冒险者头像。6 款职业，替换原先的纯色圆占位。

    绘制顺序：底圆 → 肩 → 头饰后层 → 耳 → 头 → 五官 → 头发 → 头饰前层。
    两条硬约束，都是上一版踩过坑之后定下的：
    ① 任何头饰的前缘不得越过眉线（y≈41），否则会盖住眼睛 —— 骑士旧版整张
       脸被头盔罩住，就是这个原因；
    ② 肩用中间调、发与头饰用深调，头饰才能在肩上有轮廓，不会糊成一团。

    六款的剪影刻意拉开：学徒（圆发 + 翘毛）、游侠（尖顶兜帽）、法师（尖顶
    宽檐帽）、骑士（盔顶 + 红缨）、学者（两侧垂发 + 圆框眼镜）、工匠（工帽 +
    额上护目镜）。28px 下靠外轮廓即可区分。"""
    bg, ring, deep = AV.get(kind, AV["apprentice"])
    uid = _aid()
    g = ['<circle cx="50" cy="50" r="47" fill="' + bg + '"/>',
         '<g clip-path="url(#' + uid + ')">']
    # 肩
    g.append('<path d="M50 64c19 0 34 17 34 40H16c0-23 15-40 34-40z" fill="' + ring + '"/>')

    # 头饰 · 后层
    if kind == "ranger":
        # 兜帽：顶部收窄成尖，下摆在中线开一道 V 口
        g.append('<path d="M50 9C57 9 65 18 70 30c5 10 8 20 8 26 0 13-4 21-15 27l-13-5-13 5'
                 'c-11-6-15-14-15-27 0-6 3-16 8-26C35 18 43 9 50 9z" fill="' + deep
                 + '" stroke="' + ring + '" stroke-width="2" stroke-linejoin="round"/>')
    elif kind == "scholar":
        g.append('<path d="M28 42c-3 10-3 20 0 28l10-4c-3-8-3-16-2-24z" fill="' + deep + '"/>')
        g.append('<path d="M72 42c3 10 3 20 0 28l-10-4c3-8 3-16 2-24z" fill="' + deep + '"/>')

    # 耳（会被长发或盔片遮住的款式不画，免得耳朵浮在头饰上面）
    if kind in ("apprentice", "mage", "artisan"):
        g.append('<circle cx="29" cy="47" r="4.4" fill="' + SKIN + '" stroke="' + SKIN_L
                 + '" stroke-width="2"/>')
        g.append('<circle cx="71" cy="47" r="4.4" fill="' + SKIN + '" stroke="' + SKIN_L
                 + '" stroke-width="2"/>')

    # 头
    g.append('<ellipse cx="50" cy="46" rx="21" ry="22" fill="' + SKIN + '" stroke="' + SKIN_L
             + '" stroke-width="2.2"/>')

    # 五官。眼睛加一枚高光，这是让整张脸「活」起来最省的一笔
    if kind != "scholar":
        g.append('<path d="M38 39q4.5-3.8 9 0M53 39q4.5-3.8 9 0" fill="none" stroke="' + SKIN_L
                 + '" stroke-width="1.6" stroke-linecap="round"/>')
    g.append('<circle cx="42.5" cy="47" r="3.5" fill="' + INK + '"/>'
             '<circle cx="57.5" cy="47" r="3.5" fill="' + INK + '"/>'
             '<circle cx="41.3" cy="45.7" r="1.25" fill="#FFF"/>'
             '<circle cx="56.3" cy="45.7" r="1.25" fill="#FFF"/>')
    g.append('<path d="M50 50.6v3.4" stroke="' + SKIN_L + '" stroke-width="1.6" '
             'stroke-linecap="round"/>')
    g.append('<path d="M45.6 57.4q4.4 3.8 8.8 0" fill="none" stroke="' + INK
             + '" stroke-width="1.9" stroke-linecap="round"/>')
    g.append('<ellipse cx="36" cy="54" rx="4.6" ry="2.8" fill="' + BLUSH + '" opacity=".55"/>')
    g.append('<ellipse cx="64" cy="54" rx="4.6" ry="2.8" fill="' + BLUSH + '" opacity=".55"/>')

    # 头发。兜帽款不画刘海 —— 兜帽与头发同色，画了只会让头变成一个色块，
    # 脸反而看不出边缘；改用帽口的一道中间调描边来交代「脸从帽口露出来」。
    if kind != "ranger":
        g.append('<path d="' + HAIR_D + '" fill="' + deep + '"/>')

    # 头饰 · 前层
    if kind == "ranger":
        # 帽口：一圈比脸大一点点的中间调描边，把脸和兜帽分开
        g.append('<ellipse cx="50" cy="46" rx="22.8" ry="23.8" fill="none" stroke="' + ring
                 + '" stroke-width="2.2"/>')
        g.append('<path d="M50 9c3.4 0 6.4 2.6 8.6 7.4" fill="none" stroke="' + ring
                 + '" stroke-width="2" stroke-linecap="round" opacity=".85"/>')
    elif kind == "apprentice":
        # 头顶翘起的三撮毛 —— 最省笔墨的「还没出师」标记
        g.append('<path d="M45 26c-1.4-6 .6-10 2.6-12.2M50 25c0-6.2 1-9.6 3-12.2'
                 'M55 26c1.4-5.2 3.4-8.2 5.4-10.2" fill="none" stroke="' + deep
                 + '" stroke-width="3" stroke-linecap="round"/>')
    elif kind == "mage":
        g.append('<path d="M50 2 74 37 26 37Z" fill="' + deep + '" stroke="' + ring
                 + '" stroke-width="2.2" stroke-linejoin="round"/>')
        g.append('<ellipse cx="50" cy="36" rx="30" ry="6.4" fill="' + deep + '" stroke="' + ring
                 + '" stroke-width="2.2"/>')
        g.append('<g transform="rotate(-14 64 19)">' + star_path(64, 19, 5.2, GOLD, GOLD_LINE)
                 + "</g>")
    elif kind == "knight":
        # 开面盔：盔顶停在眉线之上，两颊护片只包住脸的外侧，中间完全露出
        g.append('<path d="M29 41c0-12 9-21 21-21s21 9 21 21z" fill="' + deep + '" stroke="'
                 + ring + '" stroke-width="2.2" stroke-linejoin="round"/>')
        g.append('<path d="M28 41h44" stroke="' + ring + '" stroke-width="2.2"/>')
        g.append('<path d="M29 41v15c0 6 3 10 7 11V41z" fill="' + deep + '" stroke="' + ring
                 + '" stroke-width="2" stroke-linejoin="round"/>')
        g.append('<path d="M71 41v15c0 6-3 10-7 11V41z" fill="' + deep + '" stroke="' + ring
                 + '" stroke-width="2" stroke-linejoin="round"/>')
        g.append('<path d="M52 20c0-8 6-13 13-16-3 9-5 12-5 17z" fill="' + SEAL
                 + '" stroke="#7A2820" stroke-width="1.6" stroke-linejoin="round"/>')
    elif kind == "scholar":
        # 圆框眼镜：镜片比眼睛大一圈，眼睛仍露在镜片里 —— 这才是它读得出来的原因
        g.append('<circle cx="42.5" cy="47" r="6.4" fill="#FFFDF6" fill-opacity=".2" stroke="'
                 + deep + '" stroke-width="2"/>')
        g.append('<circle cx="57.5" cy="47" r="6.4" fill="#FFFDF6" fill-opacity=".2" stroke="'
                 + deep + '" stroke-width="2"/>')
        g.append('<path d="M48.9 47h2.2M36.1 47h-6M63.9 47h6" stroke="' + deep
                 + '" stroke-width="2" stroke-linecap="round"/>')
    elif kind == "artisan":
        # 工帽 + 推到额上的护目镜。护目镜必须画出镜桥与两侧绑带，否则两个
        # 亮圆片落在额头上会被读成「第二双眼睛」。
        g.append('<path d="M30 37c0-8 9-14 20-14s20 6 20 14z" fill="' + deep + '"/>')
        g.append('<path d="M27 37h46" stroke="' + deep + '" stroke-width="3.4" '
                 'stroke-linecap="round"/>')
        g.append('<path d="M37.6 29.5H32M62.4 29.5H68" stroke="' + deep + '" stroke-width="2.2" '
                 'stroke-linecap="round"/>')
        g.append('<circle cx="43" cy="29.5" r="5.4" fill="#FDF6E3" fill-opacity=".5" stroke="'
                 + deep + '" stroke-width="2.2"/>')
        g.append('<circle cx="57" cy="29.5" r="5.4" fill="#FDF6E3" fill-opacity=".5" stroke="'
                 + deep + '" stroke-width="2.2"/>')
        g.append('<path d="M48.4 29.5h3.2" stroke="' + deep + '" stroke-width="2.2" '
                 'stroke-linecap="round"/>')
    g.append("</g>")
    g.append('<circle cx="50" cy="50" r="47" fill="none" stroke="' + ring + '" stroke-width="2"/>')
    g.append('<defs><clipPath id="' + uid + '"><circle cx="50" cy="50" r="46"/></clipPath></defs>')
    c = ("advatar " + cls).strip()
    return ('<svg class="' + c + '" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 100 100" role="img" aria-label="' + AV_NAME.get(kind, "冒险者")
            + '头像">' + "".join(g) + "</svg>")


def avatar_row(kinds, size=38, gap=8):
    return ('<div class="row" style="gap:' + str(gap) + 'px">'
            + "".join(adv_avatar(k, size) for k in kinds) + "</div>")


def avatar_blank(size=46):
    """未确定的对手：虚线圆 + 问号。用于 PK 邀请这类「等对方入座」的位置。"""
    return ('<svg class="advatar" width="' + str(size) + '" height="' + str(size)
            + '" viewBox="0 0 100 100"><circle cx="50" cy="50" r="46" fill="' + "#F5EDD8"
            + '" stroke="' + "#C9B48D" + '" stroke-width="2" stroke-dasharray="7 6"/>'
            '<text x="50" y="52" text-anchor="middle" dominant-baseline="central" '
            'font-size="36" font-weight="700" fill="' + "#9A8870"
            + '" font-family="Baloo 2,sans-serif">?</text></svg>')


CSS = CSS.replace("__GRAIN__", GRAIN)
