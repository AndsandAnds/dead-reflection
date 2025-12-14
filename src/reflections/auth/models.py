from __future__ import annotations

import datetime as dt
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column  # type: ignore[import-not-found]


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(sa.Uuid(), primary_key=True)
    email: Mapped[str] = mapped_column(sa.Text(), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    active_avatar_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("avatars.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[dt.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(sa.Uuid(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(sa.Text(), nullable=False, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    ip: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)


class Avatar(Base):
    __tablename__ = "avatars"

    id: Mapped[UUID] = mapped_column(sa.Uuid(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    persona_prompt: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    image_url: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    voice_config: Mapped[dict | None] = mapped_column(sa.JSON(), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


