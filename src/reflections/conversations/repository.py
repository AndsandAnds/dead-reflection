from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.conversations.models import Conversation, ConversationTurn


@dataclass(frozen=True)
class ConversationsRepository:
    async def list_for_user(
        self, session: AsyncSession, *, user_id: UUID, limit: int, offset: int
    ) -> list[Conversation]:
        stmt = (
            sa.select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    async def get_for_user(
        self, session: AsyncSession, *, user_id: UUID, conversation_id: UUID
    ) -> Conversation | None:
        stmt = (
            sa.select(Conversation)
            .where(Conversation.id == conversation_id)
            .where(Conversation.user_id == user_id)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_turns(
        self, session: AsyncSession, *, conversation_id: UUID
    ) -> list[ConversationTurn]:
        stmt = (
            sa.select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
            .order_by(ConversationTurn.seq.asc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    async def create_conversation(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
    ) -> Conversation:
        now = dt.datetime.now(dt.UTC)
        c = Conversation(
            id=uuid7_uuid(),
            user_id=user_id,
            avatar_id=avatar_id,
            created_at=now,
            updated_at=now,
        )
        session.add(c)
        await session.flush()
        return c

    async def next_seq(self, session: AsyncSession, *, conversation_id: UUID) -> int:
        stmt = sa.select(sa.func.max(ConversationTurn.seq)).where(
            ConversationTurn.conversation_id == conversation_id
        )
        res = await session.execute(stmt)
        max_seq = res.scalar_one_or_none()
        return int(max_seq + 1) if max_seq is not None else 0

    async def append_turn(
        self,
        session: AsyncSession,
        *,
        conversation_id: UUID,
        seq: int,
        role: str,
        content: str,
    ) -> ConversationTurn:
        now = dt.datetime.now(dt.UTC)
        t = ConversationTurn(
            id=uuid7_uuid(),
            conversation_id=conversation_id,
            seq=seq,
            role=role,
            content=content,
            created_at=now,
        )
        session.add(t)
        # also touch conversation.updated_at
        await session.execute(
            sa.update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=now)
        )
        await session.flush()
        return t


