/**
 * 静态资源的绝对地址。
 *
 * ## 它修的是一个「上传成功、图片永远不显示」的静默故障
 *
 * 后端的自定义头像返回的是**相对路径**（`user_service.save_avatar`：
 * `avatar_url = f"/static/avatars/{filename}"`），而两端的 `<image src>` 对
 * 这种路径的处理都不一样，且**都不会打到后端**：
 *
 * - **小程序端**：`/static/avatars/x.png` 被当成**小程序包内**的路径，
 *   包内没有这个文件 —— 图片静默不显示，不报错，控制台也看不到 404。
 * - **H5 端**：它相对的是**当前页面**的源（本地是预览用的 5173），
 *   而后端在 8000，于是请求 404 —— 同样是「一片空白」。
 *
 * `API_BASE_URL` 本来只用在 `services/request.ts` 里拼接口地址，静态资源
 * 这条路径上没有任何一处做过拼接，所以**上传头像这条路从第一天起就是坏的**，
 * 只是因为此前没有任何用户上传过图片，谁也没看见。
 *
 * ## 为什么放在工具层，而不是在调用处各拼一次
 *
 * 要拼的地方有两个（`components/Avatar` 与 `utils/guildCard` 的 Canvas 头像），
 * 而且它们未来的第三个调用点一定会再忘记一次。规则只有一处时，
 * 「哪里要拼」就不是一个需要记住的知识点。
 *
 * ## 只处理**以 `/` 开头**的路径
 *
 * 传进来的还可能是：临时文件路径（`wxfile://` / `blob:`，`chooseAvatar` 与
 * `chooseImage` 给的）、`data:` URI（预置精灵）、以及将来可能的绝对 URL。
 * 这些带自己的协议头，直接放行 —— 前缀拼接只对「后端给的站内路径」有意义。
 * 没有前缀的裸路径（`static/x.png`）也放行：它不是本项目的后端约定
 * （后端一律以 `/` 开头），猜它属于哪个源只会把错误藏得更深。
 */

import { API_BASE_URL } from '../constants/api'

/**
 * 把后端给的静态资源路径拼成可访问的完整地址。
 *
 * @param url 后端字段原样传进来即可；空值返回空串（调用方可以直接用它做真假判断）
 */
export function absoluteMediaUrl(url: string | null | undefined): string {
  if (!url) return ''
  // 协议相对地址（`//host/path`）要排在「以 / 开头」之前判断
  if (url.startsWith('//')) return url
  if (!url.startsWith('/')) return url
  return `${API_BASE_URL}${url}`
}
