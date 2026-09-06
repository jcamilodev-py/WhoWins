from typing import Generic, TypeVar

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base tipada para los repositorios. La persistencia la gobiernan los
    servicios, que son los duenos de la transaccion (commit/rollback)."""
