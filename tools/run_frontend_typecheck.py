"""在沙箱里跑前端 tsc 自检。

沙箱的 bash 缺 coreutils（`cat` / `head` / `tail` 都没有），管道与重定向都会翻车。
所以这里用 Python 起进程、直接拿 stdout/stderr，再自己解码打印。

用法（在本仓库根目录）：python tools/run_frontend_typecheck.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
NODE = Path(r"C:\nvm4w\nodejs\node.exe")


def main() -> int:
    node = NODE if NODE.exists() else Path("node")
    tsc = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"

    proc = subprocess.run(
        [str(node), str(tsc), "--noEmit", "--skipLibCheck"],
        cwd=str(FRONTEND),
        capture_output=True,
    )

    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()

    print(f"exit={proc.returncode}")
    if out:
        print("--- stdout ---")
        print(out)
    if err:
        print("--- stderr ---")
        print(err)
    if not out and not err:
        print("(无输出：类型检查通过)")

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
