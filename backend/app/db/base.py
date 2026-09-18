"""ORM 基类。

单独一个文件，是为了让「建表的表」与「用表的会话」互不依赖 ——
否则 `tables.py` 想 import `Base`、`session.py` 想 import `tables` 注册元数据，
就会绕成一个环。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    `Base.metadata` 是全部表定义的唯一来源，测试用它核对映射与真实库是否一致。
    """
