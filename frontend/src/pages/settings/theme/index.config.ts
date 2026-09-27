export default definePageConfig({
  // 内容区交给 `PhoneShell` 的 `ScrollView`：5 套主题在小屏上会超过一屏。
  disableScroll: true,
  // `$board` · 与设置页其它屏一致（卡片浮在板色上）。
  // ⚠️ 这是**编译期**常量，不吃 `var(--k-*)` —— 运行时换主题靠
  // `store.setUiTheme` 里的 `Taro.setBackgroundColor` 补这一刀。
  // 已登记的边界，见 design.md D8。
  backgroundColor: '#F1E8D0'
})
