/**
 * 随机标识符。
 *
 * ## 为什么必须是「十六进制 + 连字符」的形状
 *
 * `POST /attempts` 的 `client_token` 在后端被 `^[0-9a-fA-F-]{8,36}$` 校验
 * （见 `backend/app/models/attempt.py`）：这个值会进唯一索引，形状太自由
 * 等于让别人往索引里塞任意内容。
 *
 * 所以**不能用 `Math.random().toString(36)`** —— base36 会产出 `g`–`z`，
 * 直接落在正则之外，交卷会以 4000 失败。这里生成的是 v4 形状的 UUID：
 * 36 字符，恰好在上限内。
 *
 * ## 为什么 `Math.random` 够用
 *
 * 小程序里没有全局 `crypto`，拿不到密码学安全的随机源。而这个值**不是安全边界**：
 * 服务端用它做幂等去重，并且在命中别人的令牌时会拒绝（`attempt_service`
 * 会比对 `user_id`）—— 猜中别人的令牌只会拿到一个 4000，泄漏不了任何东西。
 * 它要防的只是「同一次交卷被写两遍」，122 位随机数足够。
 */

/** 生成一个 v4 形状的 UUID（36 字符，全小写十六进制）。 */
export function uuidV4(): string {
  const bytes: number[] = []
  for (let index = 0; index < 16; index += 1) {
    bytes.push(Math.floor(Math.random() * 256))
  }
  // 版本位（4）与变体位（10xx）：让形状与标准 UUID 一致，
  // 将来后端若改成严格 UUID 校验也不必再动前端
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80

  const hex = bytes.map((byte) => byte.toString(16).padStart(2, '0'))
  return [
    hex.slice(0, 4).join(''),
    hex.slice(4, 6).join(''),
    hex.slice(6, 8).join(''),
    hex.slice(8, 10).join(''),
    hex.slice(10, 16).join('')
  ].join('-')
}
