import math
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
    ):
        self.page, self.size = page, size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    @classmethod
    def build(cls, items: list, total: int, params: PageParams) -> "Page":
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=max(1, math.ceil(total / params.size)),
        )
