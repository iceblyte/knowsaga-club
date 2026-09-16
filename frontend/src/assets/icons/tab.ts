// ⚠️ 本文件由 frontend/scripts/extract_tab_icons.py 自动生成，请勿手工修改。
//
// 重新生成是**两步**，顺序不能反：
//   python frontend/scripts/extract_tab_icons.py    # 原型 → svg/*.svg + 本文件
//   python frontend/scripts/rasterize_tab_icons.py  # svg/*.svg → png/*.png
//
// 标签栏图标源自 prototype/01-核心闭环.html 的内联 SVG，
// 两个状态各烘焙一份颜色：未选中 #9A8870（$ink3） / 选中 #2F6BD8（$magic）。
//
// 为什么标签栏用 PNG 而不是 SVG：微信 image 组件虽然官方支持 svg，但文档同时列出
// 三条限制（不支持百分比单位、不支持 <style>、mode=scaleToFill 时 WebView 会居中），
// 而抽出的图标只有 viewBox、没有 width/height，尺寸推导属于文档未兜底的行为。
// 标签栏是固定 81×81 的位图场景，PNG 一次性消除这个不确定性；
// svg/ 目录保留矢量副本供人工核对。

import hallNormal from './png/hall-normal.png'
import hallActive from './png/hall-active.png'
import workshopNormal from './png/workshop-normal.png'
import workshopActive from './png/workshop-active.png'
import reportNormal from './png/report-normal.png'
import reportActive from './png/report-active.png'
import guildNormal from './png/guild-normal.png'
import guildActive from './png/guild-active.png'
import mineNormal from './png/mine-normal.png'
import mineActive from './png/mine-active.png'

/** 标签标识（顺序与 app.config.ts 的 tabBar.list 一致） */
export type TabKey =
  | 'hall'
  | 'workshop'
  | 'report'
  | 'guild'
  | 'mine';

/** 标签图标：name -> { normal, active }，两个状态各自一张已烘焙颜色的 PNG */
export const TAB_ICONS: Record<TabKey, { normal: string; active: string }> = {
  // 社团大厅
  hall: { normal: hallNormal, active: hallActive },
  // 卷轴工坊
  workshop: { normal: workshopNormal, active: workshopActive },
  // 冒险日志
  report: { normal: reportNormal, active: reportActive },
  // 公会社交
  guild: { normal: guildNormal, active: guildActive },
  // 我的
  mine: { normal: mineNormal, active: mineActive },
};

/** 标签中文名 */
export const TAB_TEXTS: Record<TabKey, string> = {
  hall: '社团大厅',
  workshop: '卷轴工坊',
  report: '冒险日志',
  guild: '公会社交',
  mine: '我的',
};

/** 标签路由（与 app.config.ts 的 tabBar.list 一致） */
export const TAB_PATHS: Record<TabKey, string> = {
  hall: 'pages/hall/index',
  workshop: 'pages/workshop/index',
  report: 'pages/report/index',
  guild: 'pages/guild/index',
  mine: 'pages/mine/index',
};

export default TAB_ICONS;
