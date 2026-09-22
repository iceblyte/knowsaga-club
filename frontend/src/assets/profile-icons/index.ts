// ⚠️ 本文件由 frontend/scripts/generate_profile_icons.py 自动生成，请勿手工修改。
//
// 「我的档案」（04·1）入口行的 6 个线条图标。原来那 6 个 28px 方块里放的是
// 单个汉字（树 / 题 / 账 / 印 / 卡 / 设）—— 换成描边图标后方块的底色与尺寸不变。
//
// 线条色 = tokens 的 `$ink2`（#6b5a45），画在 `$paper2` 方块上。
// 为什么是 base64 的 data URI：小程序没有 <svg> 组件，项目里渲染矢量图形
// 一律走 data URI（同 `assets/sprites`、`assets/badges`）。
// 重新生成：python frontend/scripts/generate_profile_icons.py

/** 入口行图标名 */
export type ProfileIconName =
  | 'knowledgeTree'
  | 'review'
  | 'scrolls'
  | 'badges'
  | 'card'
  | 'settings';

/** 图标名 -> data URI */
export const PROFILE_ICONS: Record<ProfileIconName, string> = {
  knowledgeTree:
    'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIwIDIwIj48ZyBmaWxsPSJub25lIiBzdHJva2U9IiM2QjVBNDUiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0xMCAzLjIgMTUuNiAxMGgtMy40bDQgNC44SDMuOGw0LTQuOEg0LjRaIi8+PHBhdGggZD0iTTEwIDE0Ljh2MyIvPjwvZz48L3N2Zz4=',
  review:
    'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIwIDIwIj48ZyBmaWxsPSJub25lIiBzdHJva2U9IiM2QjVBNDUiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik00LjggMi45aDYuNmwzLjggMy44VjE3SDQuOFoiLz48cGF0aCBkPSJNMTEuMiAyLjl2My45aDMuOSIvPjxwYXRoIGQ9Ik03LjggMTAuNGw0LjQgNC40TTEyLjIgMTAuNGwtNC40IDQuNCIvPjwvZz48L3N2Zz4=',
  scrolls:
    'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIwIDIwIj48ZyBmaWxsPSJub25lIiBzdHJva2U9IiM2QjVBNDUiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik00LjggNS4yaDEwLjR2MTEuNkg0LjhaIi8+PHBhdGggZD0iTTcuNiAzLjJ2My4yTTEyLjQgMy4ydjMuMiIvPjxwYXRoIGQ9Ik03LjQgOWg1LjJNNy40IDExLjZoNS4yTTcuNCAxNC4yaDMuMiIvPjwvZz48L3N2Zz4=',
  badges:
    'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIwIDIwIj48ZyBmaWxsPSJub25lIiBzdHJva2U9IiM2QjVBNDUiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxjaXJjbGUgY3g9IjEwIiBjeT0iOCIgcj0iNC4xIi8+PHBhdGggZD0iTTcuMyAxMS40IDUuOSAxNy40bDQuMS0yLjEgNC4xIDIuMS0xLjQtNiIvPjwvZz48L3N2Zz4=',
  card:
    'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIwIDIwIj48ZyBmaWxsPSJub25lIiBzdHJva2U9IiM2QjVBNDUiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0zLjQgNS40aDEzLjJ2OS4ySDMuNFoiLz48cGF0aCBkPSJNMy40IDguOGgxMy4yIi8+PHBhdGggZD0iTTYuNCAxMmgzLjIiLz48L2c+PC9zdmc+',
  settings:
    'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIwIDIwIj48ZyBmaWxsPSJub25lIiBzdHJva2U9IiM2QjVBNDUiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwYXRoIGQ9Ik0zLjggNi42aDEyLjRNMy44IDEzLjRoMTIuNCIvPjxjaXJjbGUgY3g9IjcuOCIgY3k9IjYuNiIgcj0iMS45Ii8+PGNpcmNsZSBjeD0iMTIuNiIgY3k9IjEzLjQiIHI9IjEuOSIvPjwvZz48L3N2Zz4=',
};
