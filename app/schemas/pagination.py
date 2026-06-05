"""
Generic pagination envelope used by every list endpoint.

Shape:
    {
      "data": [...items],
      "meta": {"total": int, "limit": int, "offset": int}
    }

Why we include `total`:
  - Lets the frontend render "X of Y" and disable "next page" at the boundary
  - Computed via SELECT COUNT(*) on the same WHERE clause used for the data
"""

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from app.config import settings

T = TypeVar("T")


class PageMeta(BaseModel):
    total: int = Field(..., ge=0, description="Total rows matching the query (ignoring limit/offset)")
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)


class Page(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class PaginationParams(BaseModel):
    """FastAPI dependency-friendly pagination params with global bounds."""
    limit: int
    offset: int


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=settings.MAX_PAGE_LIMIT)] = settings.DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginationParams:
    return PaginationParams(limit=limit, offset=offset)
