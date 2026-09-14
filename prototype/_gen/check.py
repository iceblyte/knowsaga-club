"""用官方 tokenizer 检查所有 phone(...) 调用是否闭合到语句边界。"""
import io
import sys
import tokenize


def check(path):
    src = open(path, encoding="utf-8").read()
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    problems = []
    for i, t in enumerate(toks):
        if t.type != tokenize.NAME or t.string != "phone":
            continue
        # 跳过函数定义行（def phone(...)）—— 它本来就不以换行结尾，
        # 之前会稳定误报一次，干扰判断。
        if i > 0 and toks[i - 1].string == "def":
            continue
        if i + 1 >= len(toks) or toks[i + 1].string != "(":
            continue
        depth = 0
        j = i + 1
        while j < len(toks):
            s = toks[j].string
            if s == "(":
                depth += 1
            elif s == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(toks):
            problems.append((t.start[0], "未闭合"))
            continue
        # 闭合后的下一个有效 token 必须是换行
        k = j + 1
        while k < len(toks) and toks[k].type in (tokenize.NL, tokenize.COMMENT):
            k += 1
        nxt = toks[k] if k < len(toks) else None
        if nxt is None or nxt.type != tokenize.NEWLINE:
            problems.append((t.start[0], "闭合位置异常 -> 行 %d %r"
                             % (toks[j].start[0], nxt.string if nxt else "EOF")))
    calls = [i for i, t in enumerate(toks)
             if t.type == tokenize.NAME and t.string == "phone"
             and not (i > 0 and toks[i - 1].string == "def")]
    return len(calls), problems


for f in sys.argv[1:]:
    n, p = check(f)
    print("%-12s phone 调用 %d 处，问题 %d 处" % (f, n, len(p)))
    for line, msg in p:
        print("   L%-5d %s" % (line, msg))
