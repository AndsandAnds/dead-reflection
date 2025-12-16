from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field  # type: ignore[import-not-found]


TurnRole = Literal["user", "assistant", "system"]


class ConversationPublic(BaseModel):
    id: UUID
    user_id: UUID
    avatar_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ConversationTurnPublic(BaseModel):
    id: UUID
    conversation_id: UUID
    seq: int
    role: TurnRole
    content: str
    created_at: datetime


class ListConversationsResponse(BaseModel):
    items: list[ConversationPublic]


class GetConversationResponse(BaseModel):
    conversation: ConversationPublic
    turns: list[ConversationTurnPublic]


class ListConversationsQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


