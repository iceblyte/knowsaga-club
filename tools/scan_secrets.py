#!/usr/bin/env python3
"""公开仓库的提交前凭证体检。

为什么需要它
------------
本仓库是**公开仓库**（github.com/iceblyte/knowsaga-club）。一次误提交就会永久留在
git 历史里——之后即使把文件删掉，仍能用 `git show <commit>:<path>` 原样取回。
本项目已经发生过一次「真实数据库密码被写进设计文档」的事故，只是发现时尚未提交。
这个脚本就是那道闸门。

用法
----
    python tools/scan_secrets.py             # 扫描工作区（已跟踪 + 未忽略的未跟踪文件）
    python tools/scan_secrets.py --history   # 额外扫描全部提交历史（较慢）

退出码：0 = 干净；1 = 发现问题。

两道检查
--------
1. **反向比对（主力）**：从本地 `.env` 里取出真实值，反查它们有没有出现在任何会入库的
   文件里。这能覆盖「任意格式的自定义密码」——纯模式匹配做不到这一点。
2. **模式匹配（补充）**：`sk-` 开头的模型 Key、带明文口令的连接串、写死的口令赋值。

输出里**绝不回显密文**，只给「文件:行号 + 哪个键」。脚本自身的输出不该成为新的泄漏点。

两个已踩过的坑（改代码前先读）
------------------------------
- **路径必须关掉转义**：git 默认 `core.quotepath=1`，中文名会被输出成
  `"docs/\\346\\226\\271\\346\\241\\210.md"` 这种八进制串。拿它拼路径必然找不到文件，
  于是「静默跳过」——而本项目最可能藏凭证的恰恰是中文名文档。故所有 git 调用都带
  `-c core.quotepath=false`，并统计「实际读取 / 跳过」数量，让跳过不再无声。
- **git grep 走 POSIX ERE**：不支持 `\\b`、`(?i)`、`\\s`。历史扫描因此先用 ERE 粗筛定位，
  再用 Python 正则对命中行**精判**，避免两套语义不一致产生误报。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent

# 只有名字像凭证的键，才值得拿它的值去反查；否则会把 LOG_LEVEL=INFO 之类也当成秘密
SECRET_NAME_RE = re.compile(
    r"SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?TOKEN|DATABASE_URL|DSN",
    re.IGNORECASE,
)

PLACEHOLDER_RE = re.compile(
    r"[<>{}]|xxx|your[_-]?|change[_-]?me|\*\*\*|placeholder|示例|占位",
    re.IGNORECASE,
)

# 「值」如果长这样，它其实是另一个环境变量的名字，不是密钥本身（如 `api_key = DEEPSEEK_API_KEY`）
VARNAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{4,}$")

SKIP_VALUES = {"true", "false", "none", "dev", "prod", "test", "info", "debug"}

# 值必须以字母或数字开头：否则 `secret=&js_code=` 这种「空参数 + 下一个参数」会被误判
GENERIC_PATTERNS = [
    ("模型 API Key", re.compile(r"\bsk-[A-Za-z0-9]{16,}"), None),
    ("连接串含明文口令", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^:/\s]+:[^@\s]+@"), None),
    (
        "写死的口令/密钥赋值",
        re.compile(
            r"\b(?:pass(?:word|wd)?|secret|api_?key|access_?token)"
            r"\s*[=:]\s*[\"']?([A-Za-z0-9][A-Za-z0-9!@#$%^&*_+\-]{7,})",
            re.IGNORECASE,
        ),
        1,
    ),
]

# git grep 用的粗筛版本（POSIX ERE，只用于定位候选行，随后交给上面的 Python 正则精判）
GENERIC_PATTERNS_ERE = [
    ("模型 API Key", r"sk-[A-Za-z0-9]{16,}"),
    ("连接串含明文口令", r"[a-z][a-z0-9+.-]*://[^:/[:space:]]+:[^@[:space:]]+@"),
    (
        "写死的口令/密钥赋值",
        r"(pass(word|wd)?|secret|api[_-]?key|access[_-]?token)"
        r"[[:space:]]*[=:][[:space:]]*[\"']?[A-Za-z0-9][A-Za-z0-9!@#$%^&*_+-]{7,}",
    ),
]

DSN_CRED_RE = re.compile(r"://([^:/\s]+):([^@\s]+)@")


def run_git(args: list[str]) -> str:
    """所有 git 调用都关掉路径转义，否则中文名会被拼成不存在的路径而静默跳过。"""
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return proc.stdout.decode("utf-8", "replace")


def mask(value: str) -> str:
    return f"（{len(value)} 字符，已隐藏）"


def find_real_secrets(line: str) -> list[str]:
    """对单行做模式匹配，并过滤掉两类已知误报。返回可直接展示的命中说明。"""
    hits: list[str] = []
    for label, pattern, group in GENERIC_PATTERNS:
        for match in pattern.finditer(line):
            if PLACEHOLDER_RE.search(match.group(0)):
                continue
            value = match.group(group) if group else ""
            if value and VARNAME_RE.match(value):
                continue
            hits.append(f"[{label}] {mask(value or match.group(0))}")
    return hits


def collect_needles() -> dict[str, str]:
    """从本地 .env 提取真实凭证值，含连接串里的口令部分与未转义形态。"""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return {}
    needles: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not SECRET_NAME_RE.search(key):
            continue
        if len(value) < 8 or value.lower() in SKIP_VALUES or value.isdigit():
            continue
        if PLACEHOLDER_RE.search(value):
            continue
        needles[key] = value
        match = DSN_CRED_RE.search(value)
        if match and len(match.group(2)) >= 6:
            password = match.group(2)
            needles[f"{key} 的口令部分"] = password
            plain = unquote(password)
            if plain != password:
                needles[f"{key} 的口令部分（未转义）"] = plain
    return needles


def candidate_files() -> list[str]:
    tracked = run_git(["ls-files"]).splitlines()
    untracked = run_git(["ls-files", "--others", "--exclude-standard"]).splitlines()
    return [f for f in dict.fromkeys(tracked + untracked) if f]


def scan_worktree(needles: dict[str, str]) -> tuple[list[str], int, int]:
    findings: list[str] = []
    read_ok = 0
    skipped = 0
    for rel in candidate_files():
        path = REPO_ROOT / rel
        if not path.is_file():
            skipped += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped += 1
            continue
        read_ok += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            for note in find_real_secrets(line):
                findings.append(f"{rel}:{lineno}  {note}")
            for key, value in needles.items():
                if value in line:
                    findings.append(f"{rel}:{lineno}  [与 .env 的 {key} 相同] {mask(value)}")
    return findings, read_ok, skipped


def locate(grep_args: list[str]) -> list[tuple[str, str, int]]:
    """git grep 会把命中行的原文一起打出来，这里只保留 commit / 路径 / 行号。"""
    out: list[tuple[str, str, int]] = []
    for line in run_git(["grep", "-I", "-n", *grep_args]).splitlines():
        parts = line.split(":", 3)
        if len(parts) == 4 and parts[2].isdigit():
            out.append((parts[0], parts[1], int(parts[2])))
    return out


def blob_lines(commit: str, path: str) -> list[str]:
    return run_git(["show", f"{commit}:{path}"]).splitlines()


def scan_history(needles: dict[str, str]) -> list[str]:
    commits = run_git(["rev-list", "--all"]).split()
    if not commits:
        return []
    findings: list[str] = []
    for key, value in needles.items():
        for commit, path, lineno in locate(["-F", value, *commits]):
            findings.append(f"{commit[:8]}  {path}:{lineno}  [历史里出现 .env 的 {key}]")

    # 粗筛 → 精判：ERE 拿到的候选行，回到该 commit 的原文用 Python 正则复核
    blob_cache: dict[tuple[str, str], list[str]] = {}
    for label, pattern in GENERIC_PATTERNS_ERE:
        for commit, path, lineno in locate(["-i", "-E", pattern, *commits]):
            cache_key = (commit, path)
            if cache_key not in blob_cache:
                blob_cache[cache_key] = blob_lines(commit, path)
            lines = blob_cache[cache_key]
            if lineno > len(lines):
                continue
            if find_real_secrets(lines[lineno - 1]):
                findings.append(f"{commit[:8]}  {path}:{lineno}  [历史里的{label}]")
    return findings


def check_gitignore_guard() -> list[str]:
    """守卫：.env 若已存在，必须被忽略且未被跟踪。"""
    problems: list[str] = []
    if (REPO_ROOT / ".env").exists():
        if run_git(["ls-files", ".env"]).strip():
            problems.append(".env 已被纳入版本控制！必须 git rm --cached .env 并更换其中全部凭证")
        elif not run_git(["check-ignore", "-v", ".env"]).strip():
            problems.append(".env 不再被 .gitignore 忽略！提交前先恢复忽略规则")
    return problems


def hook_enabled() -> bool:
    return run_git(["config", "core.hooksPath"]).strip() == "tools/hooks"


def main() -> int:
    parser = argparse.ArgumentParser(description="公开仓库的凭证体检")
    parser.add_argument("--history", action="store_true", help="额外扫描全部提交历史")
    args = parser.parse_args()

    needles = collect_needles()
    problems = check_gitignore_guard()
    findings, read_ok, skipped = scan_worktree(needles)
    if args.history:
        findings += scan_history(needles)

    print(f"仓库：{REPO_ROOT}")
    print(f"反向比对的凭证键：{', '.join(needles) or '（.env 缺失或无可比对项）'}")
    print(f"读取 {read_ok} 个文件，跳过 {skipped} 个（二进制或不存在）"
          + ("；并已扫描全部提交历史" if args.history else ""))
    print()

    if problems:
        print("配置守卫未通过：")
        for item in problems:
            print(f"  ! {item}")
        print()

    if findings:
        print(f"发现 {len(findings)} 处疑似凭证泄漏：")
        for item in findings:
            print(f"  ! {item}")
        print()
        print("这些内容一旦提交就会永久留在公开的 git 历史里。请先改成占位符再提交。")
        return 1

    print("干净：未在会入库的内容里发现任何真实凭证。")
    if not args.history:
        print("（提交前想更彻底，可再跑一次 --history）")
    if not hook_enabled():
        print("提示：尚未启用 pre-commit 钩子。启用后每次提交会自动体检：")
        print("  git config core.hooksPath tools/hooks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
