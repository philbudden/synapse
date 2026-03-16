from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CaptureRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Memory content to store")
    source: str | None = Field(default=None, description="Optional origin of the memory")


class CaptureResponse(BaseModel):
    status: Literal["stored"]
    id: str


class SearchResult(BaseModel):
    content: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


class ErrorResponse(BaseModel):
    detail: Any
