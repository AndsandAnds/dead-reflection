from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateMcpTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class McpTokenPublic(BaseModel):
    """Token metadata without the raw secret."""

    id: UUID
    user_id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class McpTokenCreated(McpTokenPublic):
    """Returned exactly once on mint; includes the raw token string."""

    token: str


class McpTokenListResponse(BaseModel):
    items: list[McpTokenPublic]
