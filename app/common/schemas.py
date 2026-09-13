from typing import TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class PageResponse[T](BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    content: list[T]
    total_elements: int
    total_pages: int
    size: int
    number: int
    first: bool
    last: bool
    empty: bool
    number_of_elements: int
