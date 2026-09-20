/**
 * 设置与账号（原型 07·5 / 07·6 / 07·8，以及原型外的「头像与昵称」）。
 *
 * | 函数 | 接口 | 用在 |
 * |---|---|---|
 * | `fetchSettings` | `GET /users/me/settings` | 07·5 / 07·6 |
 * | `updateSettings` | `PATCH /users/me/settings` | 07·5 的开关、07·6 的保存 |
 * | `updateProfile` | `PATCH /users/me` | 头像与昵称（预置头像 / 昵称） |
 * | `uploadAvatar` | `POST /users/me/avatar` | 头像与昵称（自选图片） |
 *
 * ## 为什么与 `archive.ts` 分开
 *
 * 那边全是**读**接口，失败后果统一是「这页没数据」；这里全是**写**接口，
 * 失败后果是「我这次改动到底存没存进去」。两类接口的调用方要做的判断
 * 完全不同，混在一个模块里迟早会把「读失败就 `reload()`」的习惯
 * 带到写接口上。
 *
 * ## `PATCH` 的语义：只提交改过的字段
 *
 * 后端的 `UserSettingsUpdateRequest` 每个字段都可选，**没传的就是不改**。
 * 所以调用方传的 `patch` 要尽量小 —— 把整份设置回传（哪怕值一样）
 * 也「能用」，但那样两个页面同时开着时，后保存的那个会把自己进页面时
 * 读到的旧值盖回去。只传改动过的字段能让这种覆盖窗口变得极小。
 *
 * ## 两个返回值都是 `{ user }`，而不是完整资料
 *
 * `updateProfile` 与 `uploadAvatar` 都返回 `{ user }`，**没有 `stats`**
 * —— 改昵称不会影响副本数。所以调用方**不要**拿它替换页面数据，
 * 那样 `stats` 会消失。用返回的 `user` 更新本地登录态快照
 * （`session.updateUser`）后 `reload()` 一次，是最省心的做法：
 * 多一个几十毫秒的 GET，换来的是页面上的数字仍然来自同一个接口。
 */

import type {
  UserPublic,
  UserSettingsPublic,
  UserSettingsUpdateRequest
} from '../types/api'
import { request, upload } from './request'

/** `GET /users/me/settings`（原型 07·5 / 07·6 的数据面）。 */
export function fetchSettings(): Promise<UserSettingsPublic> {
  return request<UserSettingsPublic>({
    path: '/users/me/settings'
  })
}

/**
 * `PATCH /users/me/settings`：只提交要改的字段。
 *
 * @param patch 只放改动过的键；空对象会被服务端当成「什么都没改」并原样返回
 * @throws {ApiError} 4000（时间格式不是 `HH:MM`、星期为空 / 越界 / 重复）、4010
 */
export function updateSettings(patch: UserSettingsUpdateRequest): Promise<UserSettingsPublic> {
  return request<UserSettingsPublic>({
    path: '/users/me/settings',
    method: 'PATCH',
    data: patch as Record<string, unknown>
  })
}

/**
 * `PATCH /users/me`：改昵称或换成预置头像。
 *
 * 昵称不合规（空 / 纯空白 / 超长 / 含不允许的字符）由后端判 4001，
 * **不在前端再拦一道** —— 两处各有一套规则时，总有一处先过期，
 * 于是出现「前端说能存、后端说不行」。前端只做「空的时候不发请求」。
 *
 * **`avatar_url` 传不进来**：自定义头像地址只能由上传接口产生，
 * 否则可以指向任意外部图床。
 *
 * @throws {ApiError} 4000（`avatar_key` 不在 6 个预置键里）、4001（昵称不合规）
 */
export function updateProfile(patch: {
  nickname?: string
  avatar_key?: string
}): Promise<{ user: UserPublic }> {
  return request<{ user: UserPublic }>({
    path: '/users/me',
    method: 'PATCH',
    data: patch as Record<string, unknown>
  })
}

/**
 * `POST /users/me/avatar`：上传自定义头像（multipart）。
 *
 * 后端只信文件内容（读魔数判断是不是 jpg / png / webp），不看扩展名，
 * 也**不使用客户端提供的文件名**。所以这里只要把本地路径传上去，
 * 不需要先在前端判断格式 —— 前端判断只能拦住「能读到的」，
 * 拦不住「把 .exe 改名成 .jpg」，两道规则还会不一致。
 *
 * 前端唯一需要先拦的是**大小**：2 MB 的图片上传要几十秒，
 * 让用户等完再收到 4002 是最差的一种失败。见 `utils/avatar.ts`。
 *
 * @param filePath `chooseImage` / `chooseAvatar` 给出的本地路径
 * @throws {ApiError} 4002（内容不是允许的图片格式 / 超过大小上限）、4010
 */
export function uploadAvatar(filePath: string): Promise<{ user: UserPublic }> {
  return upload<{ user: UserPublic }>({
    path: '/users/me/avatar',
    filePath
  })
}
