from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field  # type: ignore[import-not-found]


class AvatarPublic(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    persona_prompt: str | None = None
    image_url: str | None = None
    voice_config: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ListAvatarsResponse(BaseModel):
    items: list[AvatarPublic]
    active_avatar_id: UUID | None = None


class CreateAvatarRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    persona_prompt: str | None = Field(default=None, max_length=8000)
    image_url: str | None = Field(default=None, max_length=2048)
    voice_config: dict[str, Any] | None = None
    set_active: bool = True


class UpdateAvatarRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    persona_prompt: str | None = Field(default=None, max_length=8000)
    image_url: str | None = Field(default=None, max_length=2048)
    voice_config: dict[str, Any] | None = None


class SetActiveAvatarRequest(BaseModel):
    avatar_id: UUID | None = None


class DeleteAvatarRequest(BaseModel):
    avatar_id: UUID


class OkResponse(BaseModel):
    ok: bool = True


