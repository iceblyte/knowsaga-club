export default definePageConfig({
  // 页面自身不滚动：滚动发生在 PhoneShell 的 ScrollView 内，
  // 若页面本身也可滚动，会出现两层滚动互相干扰（尤其在 iOS 上）
  disableScroll: true,
  backgroundColor: '#F1E8D0' // $board
})
