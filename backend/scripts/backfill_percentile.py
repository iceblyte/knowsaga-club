#!/usr/bin/env python
"""回算存量答题记录的百分位（`attempts.percentile` / `percentile_pool`）。

## 为什么必须有这个脚本

`percentile` 的算法在 2026-09-23 从「演示值」（`clamp(round(accuracy × 0.9), 5, 95)`）
换成了**真实社团分位**（见 `app/services/percentile_service.py`）。换算法不会
自动改写历史行：库里那 23 条老记录会停在 `percentile_pool = 0` 上，
而界面的规则是「`pool = 0` 就不显示这一格」——

> 结果是老用户打开自己的冒险日志，百分位那一条**整块消失**。诚实，但不完整，
> 而且看起来像坏了。

所以加列（`sql/05_attempts_percentile_pool.sql`）之后必须跑一次这个脚本。

## 口径

**按「现在」的社团算**，不追溯当时。理由：`percentile` 的语义是「你这一局在
社团里排在什么位置」，而位置随社团成长而变 —— 一个昨天考了 80 分的人，
今天社团里多了三个满分新人的话，他的位置确实往下掉了。
脚本只做一件事：让**存量行的数值与今天按下新算法提交时算出来的完全一致**
（同一份 `scoring.pool_percentile`，同一份池子定义）。

## 用法

    cd backend
    ./.venv/Scripts/python.exe scripts/backfill_percentile.py --dry-run   # 先看会改成什么
    ./.venv/Scripts/python.exe scripts/backfill_percentile.py             # 真的写

`--dry-run` 会打印逐条对照（旧值 → 新值），一条不写。
退出码：成功 0；有异常 1。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import get_session_factory  # noqa: E402
from app.db.tables import Attempt, User  # noqa: E402
from app.services import scoring  # noqa: E402


def _bests_by_user(session) -> dict[int, int]:
    """每位冒险者的最佳正确率（每人一条）。

    与 `percentile_service.others_best_accuracy` 同一口径：不加
    `deleted_at` 过滤（FR-B5：删除不影响整体统计），只认 `status='finished'`。
    """
    rows = session.execute(
        select(Attempt.user_id, func.max(Attempt.accuracy))
        .where(Attempt.status == "finished")
        .group_by(Attempt.user_id)
    ).all()
    return {int(uid): int(best) for uid, best in rows if best is not None}


def main() -> int:
    parser = argparse.ArgumentParser(description="回算存量 attempts 的百分位")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印会改成什么，不写库",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="只打印汇总（逐条对照会很长）",
    )
    args = parser.parse_args()

    factory = get_session_factory()
    with factory() as session:
        bests = _bests_by_user(session)
        nicknames = {
            int(uid): nickname or f"user {uid}"
            for uid, nickname in session.execute(select(User.id, User.nickname)).all()
        }
        attempts = list(session.scalars(select(Attempt).order_by(Attempt.user_id, Attempt.id)).all())

        print(f"参与分位的冒险者：{len(bests)} 位")
        print(f"待回算的记录：{len(attempts)} 条")
        if not bests:
            print("\n库里还没有任何答题记录，没什么可回算的。")
            return 0

        changed = 0
        if not args.quiet:
            print("\n旧值 → 新值：")

        for attempt in attempts:
            uid = int(attempt.user_id)
            others = [best for other_id, best in bests.items() if other_id != uid]
            new_percentile = scoring.pool_percentile(int(attempt.accuracy), others)
            new_pool = len(others)

            old_percentile = int(attempt.percentile)
            old_pool = int(attempt.percentile_pool)
            # 池子为空时列里写 0（而不是 None）—— 与 `attempt_service._write_attempt` 一致
            stored = 0 if new_percentile is None else new_percentile
            dirty = (old_percentile, old_pool) != (stored, new_pool)
            if dirty:
                changed += 1

            if not args.quiet:
                marker = "改" if dirty else "同"
                print(
                    f"  [{marker}] attempt={attempt.id:<3} "
                    f"{nicknames.get(uid, uid)[:12]:<12} "
                    f"正确率 {int(attempt.accuracy):>3}%  "
                    f"旧 {old_percentile:>3}% (池 {old_pool})  →  "
                    f"新 {'—' if new_percentile is None else str(new_percentile) + '%'} "
                    f"(池 {new_pool})"
                )

            if not args.dry_run:
                attempt.percentile = stored
                attempt.percentile_pool = new_pool

        if args.dry_run:
            print(f"\n[dry-run] 需要改写 {changed} 条，一行都没动。")
            return 0

        session.commit()
        print(f"\n已回算 {len(attempts)} 条（其中数值发生变化的 {changed} 条）。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
