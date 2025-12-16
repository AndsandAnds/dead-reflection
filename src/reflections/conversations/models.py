from __future__ import annotations

import datetime as dt
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.orm import Mapped, mapped_column  # type: ignore[import-not-found]

from reflections.auth.models import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(sa.Uuid(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    avatar_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(), sa.ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[UUID] = mapped_column(sa.Uuid(), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    role: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


