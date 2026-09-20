export default definePageConfig({
  // 四张卡 + 页脚按钮靠 `.spacer` 撑满一屏（原型就是这样），但小屏上仍可能超高，
  // 所以内容区仍交给 `PhoneShell` 的 `ScrollView`，页面自身不滚。
  disableScroll: true,
  backgroundColor: '#F1E8D0' // $board · 原型的屏底是板色，卡片浮在上面
})
