from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.conversations.exceptions import (
    CONVERSATION_NOT_FOUND,
    ConversationsServiceException,
)
from reflections.conversations.repository import ConversationsRepository


@dataclass(frozen=True)
class ConversationsService:
    repo: ConversationsRepository

    @classmethod
    def create(cls) -> "ConversationsService":
        return cls(repo=ConversationsRepository())

    async def list_conversations(
        self, session: AsyncSession, *, user, limit: int, offset: int
    ):
        return await self.repo.list_for_user(
            session, user_id=user.id, limit=limit, offset=offset
        )

    async def get_conversation(
        self, session: AsyncSession, *, user, conversation_id: UUID
    ):
        c = await self.repo.get_for_user(
            session, user_id=user.id, conversation_id=conversation_id
        )
        if c is None:
            raise ConversationsServiceException("Conversation not found", CONVERSATION_NOT_FOUND)
        turns = await self.repo.list_turns(session, conversation_id=conversation_id)
        return c, turns

    async def ensure_and_append_turn_pair(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        conversation_id: UUID | None,
        user_text: str,
        assistant_text: str,
    ) -> UUID:
        """
        Ensure there is a conversation and append the (user, assistant) turn pair.

        Returns the conversation_id (created or existing).
        """
        cid = conversation_id
        if cid is None:
            c = await self.repo.create_conversation(
                session, user_id=user_id, avatar_id=avatar_id
            )
            cid = c.id

        seq0 = await self.repo.next_seq(session, conversation_id=cid)
        await self.repo.append_turn(
            session,
            conversation_id=cid,
            seq=seq0,
            role="user",
            content=user_text,
        )
        await self.repo.append_turn(
            session,
            conversation_id=cid,
            seq=seq0 + 1,
            role="assistant",
            content=assistant_text,
        )
        return cid


@lru_cache
def get_conversations_service() -> ConversationsService:
    return ConversationsService.create()


