"""跨模块共用的契约类型。

## 为什么要有这个文件

`UtcDatetime` 原本长在 `app/models/archive.py` 里（那里第一次需要它）。
知识库的契约同样需要它，而「知识库 import 档案」是一条**方向错误**的依赖：
档案是 04 屏的东西、知识库是 05 屏的东西，两者之间没有任何业务关系，
真去 import 只会让后来的人以为它们相关。

## 时间一律带 UTC 偏移

库里存的是 naive UTC，直接序列化会得到 `2026-09-19T03:00:00` 这种**不带偏移**
的串 —— 而 JavaScript 的 `new Date()` 规范上把它当**本地时间**解释，
界面上的日期会整体偏 8 小时，跨零点时就是错一天。
报告页的 `finished_at` 踩过一次，所以这里用类型固定住，不靠人记。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer

from app.utils.timeutil import as_aware_utc

#: 序列化时补上 UTC 偏移的 datetime。
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda value: as_aware_utc(value).isoformat(), return_type=str),
]
