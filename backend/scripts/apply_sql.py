"""把一个 `sql/*.sql` 文件应用到数据库（业务库 / 测试库）。

## 为什么需要它

`backend/sql/` 下的迁移文件是**手写 DDL**，此前只能照文件头注释里的
`mysql -h ... -D <库名> < 文件名` 手工执行 —— 一次要跑两个库，
漏掉一个的表现是「业务库好了、pytest 全红」（或反过来），
而报错是 `Unknown column ...`，跟「你忘了跑迁移」看不出关系。

这个脚本把「应用到哪些库」变成一行命令，并且**打印自检语句的结果** ——
迁移文件末尾那句 `SELECT ... AS has_column` 就是给它看的。

## 用法

    cd backend
    ./.venv/Scripts/python.exe scripts/apply_sql.py sql/03_attempts_deleted_at.sql
    ./.venv/Scripts/python.exe scripts/apply_sql.py sql/03_attempts_deleted_at.sql --target test
    ./.venv/Scripts/python.exe scripts/apply_sql.py sql/01_schema.sql --target main

默认对**两个库都执行**（业务库 + 测试库）。文件必须写成幂等的
（本仓的迁移都走 `information_schema` 判断 + 预处理语句，可重复执行）。

## 为什么不用 `mysql` CLI

密码会出现在命令行（Windows 上 `ps` 等价物能看到），而且要自己拼引号。
这里复用应用自己的配置读 DSN，凭据不落到命令行上。

## 为什么用 `exec_driver_sql`

它不做参数替换，所以脚本里的字面 `%`（MySQL 注释中可能出现）不会被
SQLAlchemy 当成占位符而报 `immutabledict` 的错。迁移文件是**DDL 文本**，
本来也不该经过参数绑定这一层。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from app.core.config import Settings  # noqa: E402


def split_statements(script: str) -> list[str]:
    """按 `;` 切分语句，并丢掉整行注释。

    只处理**整行**注释（`-- ...`）。行内的 `--` 不动它 —— 迁移文件里
    有 `COMMENT '...'` 这样的字符串字面量，粗暴地找 `--` 会把列注释
    切掉一半，而 MySQL 对切坏的语句只会报一个与真实原因无关的语法错。
    """
    lines = [
        line
        for line in script.splitlines()
        if not line.strip().startswith("--")
    ]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def apply_to(engine: Engine, statements: list[str], label: str) -> bool:
    """在一个库上按顺序执行全部语句，返回是否全部成功。"""
    print(f"\n===== {label} =====")
    ok = True
    with engine.connect() as conn:
        for index, statement in enumerate(statements, start=1):
            head = " ".join(statement.split())[:70]
            try:
                result = conn.exec_driver_sql(statement)
                # SELECT 才有结果集：迁移文件末尾的自检语句靠它显示
                if result.returns_rows:
                    for row in result.fetchall():
                        print(f"  [{index}] {head}... -> {tuple(row)}")
                    result.close()
                else:
                    print(f"  [{index}] ok  {head}...")
            except Exception as exc:  # noqa: BLE001 - 要的就是原样报出来
                print(f"  [{index}] FAIL {head}...")
                print(f"        {type(exc).__name__}: {exc}")
                ok = False
                break
        conn.commit()
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="应用 sql/*.sql 到数据库")
    parser.add_argument("sql_file", help="相对 backend/ 的路径，如 sql/03_xxx.sql")
    parser.add_argument(
        "--target",
        choices=("both", "main", "test"),
        default="both",
        help="应用到哪里；默认两个库都跑",
    )
    args = parser.parse_args()

    path = BACKEND_DIR / args.sql_file
    if not path.exists():
        print(f"找不到文件：{path}")
        return 2

    statements = split_statements(path.read_text(encoding="utf-8"))
    if not statements:
        print("文件里没有可执行的语句（只有注释？）")
        return 2

    print(f"文件：{path}")
    print(f"语句：{len(statements)} 条")

    settings = Settings()
    targets: list[tuple[str, str]] = []
    if args.target in ("both", "main"):
        url = (settings.database_url or "").strip()
        if url:
            targets.append(("业务库", url))
        else:
            print("跳过业务库：未配置 DATABASE_URL")
    if args.target in ("both", "test"):
        url = settings.effective_test_database_url
        if url:
            targets.append(("测试库", url))
        else:
            print("跳过测试库：未配置 TEST_DATABASE_URL")

    if not targets:
        print("没有任何可用的连接串。")
        return 2

    exit_code = 0
    for label, url in targets:
        # 迁移是 DDL，逐条提交即可；连接池与 ping 参数与运行时保持一致
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)
        try:
            if not apply_to(engine, statements, f"{label}（{_dbname(url)}）"):
                exit_code = 1
        finally:
            engine.dispose()

    print("\n完成。" if exit_code == 0 else "\n有失败，请查看上面的输出。")
    return exit_code


def _dbname(url: str) -> str:
    """从 DSN 里取库名，仅用于打印（不打印凭据）。"""
    return url.rsplit("/", 1)[-1].split("?")[0]


if __name__ == "__main__":
    raise SystemExit(main())
