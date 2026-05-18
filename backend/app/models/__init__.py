"""所有 SQLAlchemy 表的统一 import 入口.

alembic env.py 通过 `from app import models` 让 Base.metadata 知道有哪些表.
加新表时在这里 re-export.
"""

from app.models.game import Game, GameEvent, GamePlayer

__all__ = ["Game", "GamePlayer", "GameEvent"]
