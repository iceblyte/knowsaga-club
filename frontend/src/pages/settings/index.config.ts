export default definePageConfig({
  // 内容区由 `PhoneShell` 的 `ScrollView` 承载（9 行在小屏上会超出一屏），
  // 所以页面本身不能再滚 —— 两层滚动会互相抢手势。
  disableScroll: true,
  backgroundColor: '#F1E8D0' // $board · 这一屏的行直接铺在板色底上（原型 07·5）
})
