from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateMcpTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Defaults applied server-side when omitted (mcp:read + mcp:write).
    # Pass ["mcp:read", "mcp:write", "mcp:read_private"] for a trusted
    # client that should be able to see private content.
    scopes: list[str] | None = None


class McpTokenPublic(BaseModel):
    """Token metadata without the raw secret."""

    id: UUID
    user_id: UUID
    name: str
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class McpTokenCreated(McpTokenPublic):
    """Returned exactly once on mint; includes the raw token string."""

    token: str


class McpTokenListResponse(BaseModel):
    items: list[McpTokenPublic]
