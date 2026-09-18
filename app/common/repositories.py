from typing import TypeVar

T = TypeVar("T")


class BaseRepository[T]:
    """Typed base for repositories. Persistence is governed by the services,
    which own the transaction (commit/rollback)."""
