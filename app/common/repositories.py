from typing import TypeVar

T = TypeVar("T")


class BaseRepository[T]:
    """Base tipada para los repositorios. La persistencia la gobiernan los
    servicios, que son los duenos de la transaccion (commit/rollback)."""
