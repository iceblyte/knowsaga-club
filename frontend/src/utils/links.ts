/**
 * 从用户输入里抽出网页链接（**与后端 `app/utils/links.py` 同源**）。
 *
 * ## 为什么前端也要有一份
 *
 * 大厅那只 pill（「AI 将联网补充」/「读取链接并联网补充」）要按「输入里有没有链接」
 * 分成两句文案，这是**展示**用途。真正要读哪些页面必须由服务端独立算 ——
 * 否则一个前端 bug 就能让「我贴了链接」变成「服务端不知道有链接」。
 * 也就是说：两份实现**都要有**，而且必须给出同一个答案。
 *
 * ## 一致性怎么保证
 *
 * 不靠人眼。判据在 `shared/link-cases.json`，两端各自对着同一份数据断言：
 * 后端 `backend/tests/test_links.py`、前端 `frontend/scripts/check_links_parity.mjs`
 * （`npm run check:links`）。做法与 `shared/scoring-cases.json` 完全相同。
 * **改规则先改那份共享用例。**
 *
 * ## 规则
 *
 * 只有两种形态算链接：
 *
 * 1. `http://…` / `https://…`
 * 2. `www.…`
 *
 * **不做猜测式补全**：`example.com/docs` 不算链接。一句话里出现 `example.com`
 * 太常见（可能只是句中的域名举例），猜错的表现是「模型跑去读一个用户没打算给的页面」，
 * 比「没识别出来」更糟 —— 后者用户会再说一遍，前者他根本不知道。
 *
 * `www.` 形态会补上 `https://` 前缀。这**不是**猜测：`www.` 开头本身就是
 * 「这是一个网址」的声明，而 Tavily 的 extract 只接受带 scheme 的 URL。
 *
 * ## 为什么不用 `matchAll` / `for…of`
 *
 * 这里是**小程序端也要跑**的代码，`matchAll`（ES2020）与字符串迭代器依赖运行时支持。
 * Taro 默认的 polyfill 覆盖到哪一档不值得为这点便利去赌 —— 赌输的表现是
 * 「H5 正常、小程序上贴了链接却没反应」。所以用最保守的 `exec` 循环 + 下标遍历。
 */

/**
 * 匹配「以 http(s):// 或 www. 开头的一段合法字符」。与后端同一组形态。
 *
 * 字符集里排除中文标点：中文句子里 `。` 紧跟在链接后面不带空格，
 * 不排除就会把「。后面还有字」整段吞进 URL。
 *
 * ⚠️ 不能同样排除 ASCII 的 `.` `,` `)` —— 它们在 URL 内部是合法的
 * （`?q=1,2`、`wiki/Foo_(bar)`、`v1.2`），只在**结尾**时才是标点，
 * 交给 `stripTrailing` 在末尾剥。
 */
const URL_SOURCE = '(?:https?://|www\\.)[^\\s<>"\'`。，、；：！？（）【】《》「」『』\\u3000]+'

/** 尾部的 ASCII 标点：无需配对判断，直接剥。 */
const TRAILING = '.,;:!?'

/** 需要配对判断才敢剥的成对符号，键是闭合符。
 *
 * 闭合符只有在**数量多于**它的开括号时才剥 ——
 * `(https://a.example/p)` 尾部的 `)` 是标点，而 `Foo_(bar)` 尾部的是路径的一部分。 */
const BRACKETS: Record<string, string> = { ')': '(', ']': '[', '}': '{' }

const DEFAULT_SCHEME = 'https://'

/** 数出某个字符出现几次。用 `indexOf` 递进，不用 `split` / 迭代器。 */
function countOf(text: string, char: string): number {
  let count = 0
  let index = text.indexOf(char)
  while (index !== -1) {
    count += 1
    index = text.indexOf(char, index + 1)
  }
  return count
}

/** 剥掉贴在链接末尾的标点。逐字符判，遇到非标点就停。 */
function stripTrailing(url: string): string {
  let result = url
  while (result.length > 0) {
    const char = result.charAt(result.length - 1)
    const opener = BRACKETS[char]
    if (opener) {
      if (countOf(result, char) > countOf(result, opener)) {
        result = result.slice(0, -1)
        continue
      }
      break
    }
    if (TRAILING.indexOf(char) !== -1) {
      result = result.slice(0, -1)
      continue
    }
    break
  }
  return result
}

/**
 * 抽出输入里的全部链接，**去重且保序**。
 *
 * @param text 用户原始输入。
 * @returns 链接数组，按首次出现顺序排列。没有链接时是空数组。
 */
export function extractUrls(text: string): string[] {
  const found: string[] = []
  const seen: Record<string, true> = {}
  // 每次调用新建一份：带 `g` 的正则把 `lastIndex` 存在对象上，
  // 复用模块级实例会让连续两次调用从上次的位置接着找（第一次之后的调用全都漏匹配）
  const pattern = new RegExp(URL_SOURCE, 'gi')

  let match = pattern.exec(text || '')
  while (match !== null) {
    let url = stripTrailing(match[0])
    if (url) {
      if (url.toLowerCase().indexOf('www.') === 0) {
        url = DEFAULT_SCHEME + url
      }
      if (!seen[url]) {
        seen[url] = true
        found.push(url)
      }
    }
    match = pattern.exec(text || '')
  }
  return found
}

/** 输入里有没有链接。大厅 pill 的四态判定用它；它与后端 `has_url` 必须同一答案。 */
export function hasUrl(text: string): boolean {
  return extractUrls(text).length > 0
}
