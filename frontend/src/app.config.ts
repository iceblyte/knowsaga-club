export default defineAppConfig({
  // 首屏为启动页（法阵 + 卷轴展开），启动页随后 switchTab 进入「社团大厅」
  pages: [
    'pages/splash/index',
    'pages/hall/index',
    'pages/workshop/index',
    // 冒险日志拆三页：主视图（标签页）+ 三句话总结 + 复习建议。
    // 原型 03 的这三屏各自有独立的导览栏标题，也是
    // docs/用户系统方案设计文档.md §7.3 页面清单里的 12 / 13 号
    'pages/report/index',
    'pages/report/summary/index',
    'pages/report/suggestions/index',
    // 冒险者档案：从「我的」下钻的只读聚合页（Phase D 四页 + Phase E 两页）。
    // app.config 里声明了却没有实现的路由会让 build 直接失败 ——
    // 加一行就必须同时有对应的 `pages/**/index.tsx`。
    'pages/profile/dashboard/index',
    'pages/profile/knowledge-tree/index',
    'pages/profile/review/index',
    'pages/profile/badges/index',
    // 公会卡（04·2）：卡面数据与个人中心同源；「保存到相册」只在非 H5 出现。
    'pages/profile/card/index',
    // 复习提醒（04·8）：大厅与个人中心的页内提醒入口的落地页，亦可从档案进入。
    'pages/profile/reminder/index',
    // 历史卷轴（Phase E）：列表 + 详情。详情靠 `attempt_id` 参数下钻，
    // 参数缺失时页面不发请求、直接给出「不在了」的出口（见该页说明）。
    'pages/profile/scrolls/index',
    'pages/profile/scroll-detail/index',
    // 设置（Phase E）：07·5 列表 → 07·6 学习提醒 / 07·8 帮助与反馈，
    // 外加方案 §7.4 要求新增的「头像与昵称」。
    // 原型给这几屏标的是 `tabbar(4)`（属于「我的」那一栏），但实现一律是
    // **下钻页**（带返回键、不渲染标签栏）——与 04·7 旧识重温同例：
    // `tabbar(n)` 标注的是归属，不是布局。
    'pages/settings/index',
    'pages/settings/profile/index',
    'pages/settings/reminder/index',
    'pages/settings/help/index',
    'pages/guild/index',
    'pages/mine/index',
    'pages/summon/index',
    'pages/confirm/index',
    'pages/quiz/index',
    'pages/settle/index',
    'pages/exception/index'
  ],
  window: {
    // 原型自带状态栏（9:41）与导览栏（返回键 / 标题 / 右文案），
    // 因此必须关掉微信原生导航栏，否则会出现两层标题。
    navigationStyle: 'custom',
    backgroundTextStyle: 'light',
    backgroundColor: '#F1E8D0',
    navigationBarBackgroundColor: '#F1E8D0',
    navigationBarTitleText: '知拾冒险社',
    navigationBarTextStyle: 'black'
  },
  tabBar: {
    // 原型标签栏有「顶部 26px 指示条 + 21px 线性图标 + 高亮换色」三处细节，
    // 微信原生 tabBar 只能做图标+换色，因此改用自定义 tabBar 精确还原。
    // 实现见 src/custom-tab-bar/。
    custom: true,
    color: '#9A8870', // $ink3 · 未选中
    selectedColor: '#2F6BD8', // $magic · 选中
    backgroundColor: '#F5EDD8', // $paper2
    borderStyle: 'white',
    // custom: true 时微信仍要求声明 list（用于页面归属与 switchTab 路由）
    list: [
      { pagePath: 'pages/hall/index', text: '社团大厅' },
      { pagePath: 'pages/workshop/index', text: '卷轴工坊' },
      { pagePath: 'pages/report/index', text: '冒险日志' },
      { pagePath: 'pages/guild/index', text: '公会社交' },
      { pagePath: 'pages/mine/index', text: '我的' }
    ]
  }
})
