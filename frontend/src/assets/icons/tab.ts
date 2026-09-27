// ⚠️ 本文件由 frontend/scripts/extract_tab_icons.py 自动生成，请勿手工修改。
//
// 重新生成是**两步**，顺序不能反：
//   python frontend/scripts/extract_tab_icons.py    # 原型 → svg/*.svg + 本文件
//   python frontend/scripts/rasterize_tab_icons.py  # svg/*.svg → png/<theme>/*.png
//
// svg/*.svg 只保留**默认主题 paper** 的烘焙色（#9A8870 / #2F6BD8），
// 作为矢量副本供人工核对；各主题的位图由第二步换色光栅化得到。
//
// 为什么每套主题各一套 PNG：**图标颜色在像素里，CSS 变量够不到它**。
// 颜色取自各主题的 --k-ink-3（未选中）/ --k-magic-ink（选中）—— 与标签栏文字同色。
// ⚠️ 选中用 magic-ink（主色的文字档）而不是 magic（填充档）：浅色品牌（青柠）的
// $magic = #70C000 压在自己的标签栏底上只有 2.12:1，配方专门求解了 magic-ink；
// 图标若取 magic 就在资源层把那个坑重挖一遍。
//
// paper 那套与主题化之前的平铺版本**逐字节相同**（生成后已用 sha256 复核）——
// 默认主题的图标没有发生任何变化。
//
// 为什么标签栏用 PNG 而不是 SVG：微信 image 组件虽然官方支持 svg，但文档同时列出
// 三条限制（不支持百分比单位、不支持 <style>、mode=scaleToFill 时 WebView 会居中），
// 而抽出的图标只有 viewBox、没有 width/height，尺寸推导属于文档未兜底的行为。
// 标签栏是固定 81×81 的位图场景，PNG 一次性消除这个不确定性。

import type { UiThemeId } from '../../constants/ui-theme-tokens'

import paperHallNormal from './png/paper/hall-normal.png'
import paperHallActive from './png/paper/hall-active.png'
import paperWorkshopNormal from './png/paper/workshop-normal.png'
import paperWorkshopActive from './png/paper/workshop-active.png'
import paperReportNormal from './png/paper/report-normal.png'
import paperReportActive from './png/paper/report-active.png'
import paperGuildNormal from './png/paper/guild-normal.png'
import paperGuildActive from './png/paper/guild-active.png'
import paperMineNormal from './png/paper/mine-normal.png'
import paperMineActive from './png/paper/mine-active.png'
import indigoHallNormal from './png/indigo/hall-normal.png'
import indigoHallActive from './png/indigo/hall-active.png'
import indigoWorkshopNormal from './png/indigo/workshop-normal.png'
import indigoWorkshopActive from './png/indigo/workshop-active.png'
import indigoReportNormal from './png/indigo/report-normal.png'
import indigoReportActive from './png/indigo/report-active.png'
import indigoGuildNormal from './png/indigo/guild-normal.png'
import indigoGuildActive from './png/indigo/guild-active.png'
import indigoMineNormal from './png/indigo/mine-normal.png'
import indigoMineActive from './png/indigo/mine-active.png'
import vermilionHallNormal from './png/vermilion/hall-normal.png'
import vermilionHallActive from './png/vermilion/hall-active.png'
import vermilionWorkshopNormal from './png/vermilion/workshop-normal.png'
import vermilionWorkshopActive from './png/vermilion/workshop-active.png'
import vermilionReportNormal from './png/vermilion/report-normal.png'
import vermilionReportActive from './png/vermilion/report-active.png'
import vermilionGuildNormal from './png/vermilion/guild-normal.png'
import vermilionGuildActive from './png/vermilion/guild-active.png'
import vermilionMineNormal from './png/vermilion/mine-normal.png'
import vermilionMineActive from './png/vermilion/mine-active.png'
import midnightHallNormal from './png/midnight/hall-normal.png'
import midnightHallActive from './png/midnight/hall-active.png'
import midnightWorkshopNormal from './png/midnight/workshop-normal.png'
import midnightWorkshopActive from './png/midnight/workshop-active.png'
import midnightReportNormal from './png/midnight/report-normal.png'
import midnightReportActive from './png/midnight/report-active.png'
import midnightGuildNormal from './png/midnight/guild-normal.png'
import midnightGuildActive from './png/midnight/guild-active.png'
import midnightMineNormal from './png/midnight/mine-normal.png'
import midnightMineActive from './png/midnight/mine-active.png'
import limeHallNormal from './png/lime/hall-normal.png'
import limeHallActive from './png/lime/hall-active.png'
import limeWorkshopNormal from './png/lime/workshop-normal.png'
import limeWorkshopActive from './png/lime/workshop-active.png'
import limeReportNormal from './png/lime/report-normal.png'
import limeReportActive from './png/lime/report-active.png'
import limeGuildNormal from './png/lime/guild-normal.png'
import limeGuildActive from './png/lime/guild-active.png'
import limeMineNormal from './png/lime/mine-normal.png'
import limeMineActive from './png/lime/mine-active.png'

/** 标签标识（顺序与 app.config.ts 的 tabBar.list 一致） */
export type TabKey =
  | 'hall'
  | 'workshop'
  | 'report'
  | 'guild'
  | 'mine';

/** 一个标签的两个状态，各一张已烘焙颜色的 PNG */
export interface TabIconPair {
  normal: string
  active: string
}

/** 一套主题下的全部标签图标 */
export type TabIconSet = Record<TabKey, TabIconPair>

/**
 * 主题 -> 图标集。
 *
 * 用 `Record<UiThemeId, …>` 而不是 `Partial<…>`：漏掉一套主题时 `tsc` 当场报错，
 * 不会等到运行时才发现某个主题下图标全空白。
 */
export const TAB_ICONS: Record<UiThemeId, TabIconSet> = {
  // 纸与印
  paper: {
    // 社团大厅
    hall: { normal: paperHallNormal, active: paperHallActive },
    // 卷轴工坊
    workshop: { normal: paperWorkshopNormal, active: paperWorkshopActive },
    // 冒险日志
    report: { normal: paperReportNormal, active: paperReportActive },
    // 公会社交
    guild: { normal: paperGuildNormal, active: paperGuildActive },
    // 我的
    mine: { normal: paperMineNormal, active: paperMineActive },
  },
  // 宣纸靛墨
  indigo: {
    // 社团大厅
    hall: { normal: indigoHallNormal, active: indigoHallActive },
    // 卷轴工坊
    workshop: { normal: indigoWorkshopNormal, active: indigoWorkshopActive },
    // 冒险日志
    report: { normal: indigoReportNormal, active: indigoReportActive },
    // 公会社交
    guild: { normal: indigoGuildNormal, active: indigoGuildActive },
    // 我的
    mine: { normal: indigoMineNormal, active: indigoMineActive },
  },
  // 素白墨朱
  vermilion: {
    // 社团大厅
    hall: { normal: vermilionHallNormal, active: vermilionHallActive },
    // 卷轴工坊
    workshop: { normal: vermilionWorkshopNormal, active: vermilionWorkshopActive },
    // 冒险日志
    report: { normal: vermilionReportNormal, active: vermilionReportActive },
    // 公会社交
    guild: { normal: vermilionGuildNormal, active: vermilionGuildActive },
    // 我的
    mine: { normal: vermilionMineNormal, active: vermilionMineActive },
  },
  // 夜航公会
  midnight: {
    // 社团大厅
    hall: { normal: midnightHallNormal, active: midnightHallActive },
    // 卷轴工坊
    workshop: { normal: midnightWorkshopNormal, active: midnightWorkshopActive },
    // 冒险日志
    report: { normal: midnightReportNormal, active: midnightReportActive },
    // 公会社交
    guild: { normal: midnightGuildNormal, active: midnightGuildActive },
    // 我的
    mine: { normal: midnightMineNormal, active: midnightMineActive },
  },
  // 青柠
  lime: {
    // 社团大厅
    hall: { normal: limeHallNormal, active: limeHallActive },
    // 卷轴工坊
    workshop: { normal: limeWorkshopNormal, active: limeWorkshopActive },
    // 冒险日志
    report: { normal: limeReportNormal, active: limeReportActive },
    // 公会社交
    guild: { normal: limeGuildNormal, active: limeGuildActive },
    // 我的
    mine: { normal: limeMineNormal, active: limeMineActive },
  },
}

/**
 * 取某套主题的标签图标集。
 *
 * 兜底到 `paper`：`UiThemeId` 是闭集，类型上到不了兜底分支；但本地镜像
 * （`knowsaga.uiTheme`）可能是旧版本写下的脏值，运行时兜一层，好过把
 * `undefined` 交给 `<Image src>` 渲染成空白。
 */
export function tabIconsOf(theme: UiThemeId): TabIconSet {
  return TAB_ICONS[theme] ?? TAB_ICONS.paper
}

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
