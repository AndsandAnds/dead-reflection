from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Outcome = Literal["ok", "denied", "error"]


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""


class InternetSearchResult(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)


class OutboundAuditEntry(BaseModel):
    id: UUID
    user_id: UUID
    method: str
    url: str
    purpose: str | None = None
    status_code: int | None = None
    outcome: Outcome
    error: str | None = None
    duration_ms: int | None = None
    ts: datetime


class OutboundAuditPage(BaseModel):
    items: list[OutboundAuditEntry]
    limit: int
    offset: int
