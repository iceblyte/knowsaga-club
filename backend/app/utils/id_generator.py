"""ID 生成器。

三个约束决定了这里用**随机短串**而不是自增或时间戳：

1. **不能自增**：自增 ID 会把「今天有多少人用了」这类信息泄露给任何拿到 ID 的人。
2. **不能只用时间戳**：同一毫秒内并发提交会撞号，而任务表是按 ID 索引的。
3. **要能在日志里肉眼分辨**：所以保留 `task_` / `quiz_` / `report_` 前缀，
   一眼就能看出这条日志说的是哪种对象。

48 位随机空间（12 个十六进制字符）对「进程内 + 10 分钟 TTL」这个规模绰绰有余：
要撞号需要同进程内积累到千万级任务，而那时任务早就过期回收了。
"""

from __future__ import annotations

import secrets

# 12 个十六进制字符 = 48 位随机空间
_ID_BYTES = 6


def new_id(prefix: str) -> str:
    """生成 `{prefix}_{12位十六进制}` 形式的 ID。

    Args:
        prefix: 语义前缀，如 `task` / `quiz` / `report`。
    """
    return f"{prefix}_{secrets.token_hex(_ID_BYTES)}"


def new_task_id() -> str:
    """任务 ID，形如 `task_9f2c1ab4d7e0`。"""
    return new_id("task")


def new_quiz_id() -> str:
    """题库 ID，形如 `quiz_9f2c1ab4d7e0`。"""
    return new_id("quiz")


def new_report_id() -> str:
    """报告 ID（Phase 3 使用）。"""
    return new_id("report")
