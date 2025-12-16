from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session
from reflections.conversations.exceptions import (
    CONVERSATION_NOT_FOUND,
    ConversationsServiceException,
)
from reflections.conversations.schemas import (
    ConversationPublic,
    ConversationTurnPublic,
    GetConversationResponse,
    ListConversationsResponse,
)
from reflections.conversations.service import ConversationsService


router = APIRouter(prefix="/conversations", tags=["conversations"])


@lru_cache
def get_conversations_service() -> ConversationsService:
    return ConversationsService.create()


def _to_conversation_public(c) -> ConversationPublic:  # type: ignore[no-untyped-def]
    return ConversationPublic(
        id=c.id,
        user_id=c.user_id,
        avatar_id=c.avatar_id,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _to_turn_public(t) -> ConversationTurnPublic:  # type: ignore[no-untyped-def]
    return ConversationTurnPublic(
        id=t.id,
        conversation_id=t.conversation_id,
        seq=t.seq,
        role=t.role,
        content=t.content,
        created_at=t.created_at,
    )


@router.get("", response_model=ListConversationsResponse)
async def list_conversations(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ConversationsService, Depends(get_conversations_service)],
    user=Depends(current_user_required),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ListConversationsResponse:
    items = await svc.list_conversations(session, user=user, limit=limit, offset=offset)
    return ListConversationsResponse(items=[_to_conversation_public(c) for c in items])


@router.get("/{conversation_id}", response_model=GetConversationResponse)
async def get_conversation(
    conversation_id: str,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ConversationsService, Depends(get_conversations_service)],
    user=Depends(current_user_required),
) -> GetConversationResponse:
    try:
        cid = UUID(conversation_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    try:
        c, turns = await svc.get_conversation(session, user=user, conversation_id=cid)
    except ConversationsServiceException as exc:
        if getattr(exc, "details", None) == CONVERSATION_NOT_FOUND:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        raise

    return GetConversationResponse(
        conversation=_to_conversation_public(c),
        turns=[_to_turn_public(t) for t in turns],
    )


