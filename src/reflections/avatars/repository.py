from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.auth.models import Avatar, User
from reflections.commons.ids import uuid7_uuid


@dataclass(frozen=True)
class AvatarsRepository:
    async def list_for_user(self, session: AsyncSession, *, user_id: UUID) -> list[Avatar]:
        stmt = sa.select(Avatar).where(Avatar.user_id == user_id).order_by(Avatar.created_at.desc())
        res = await session.execute(stmt)
        return list(res.scalars().all())

    async def get_for_user(
        self, session: AsyncSession, *, user_id: UUID, avatar_id: UUID
    ) -> Avatar | None:
        stmt = (
            sa.select(Avatar)
            .where(Avatar.id == avatar_id)
            .where(Avatar.user_id == user_id)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        name: str,
        persona_prompt: str | None,
        image_url: str | None,
        voice_config: dict | None,
    ) -> Avatar:
        now = dt.datetime.now(dt.UTC)
        a = Avatar(
            id=uuid7_uuid(),
            user_id=user_id,
            name=name.strip(),
            persona_prompt=persona_prompt,
            image_url=image_url,
            voice_config=voice_config,
            created_at=now,
            updated_at=now,
        )
        session.add(a)
        await session.flush()
        return a

    async def update_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID,
        name: str | None,
        persona_prompt: str | None,
        image_url: str | None,
        voice_config: dict | None,
    ) -> Avatar | None:
        now = dt.datetime.now(dt.UTC)
        values: dict = {"updated_at": now}
        if name is not None:
            values["name"] = name.strip()
        if persona_prompt is not None:
            values["persona_prompt"] = persona_prompt
        if image_url is not None:
            values["image_url"] = image_url
        if voice_config is not None:
            values["voice_config"] = voice_config

        stmt = (
            sa.update(Avatar)
            .where(Avatar.id == avatar_id)
            .where(Avatar.user_id == user_id)
            .values(**values)
            .returning(Avatar)
        )
        res = await session.execute(stmt)
        await session.flush()
        return res.scalar_one_or_none()

    async def set_image_url(
        self, session: AsyncSession, *, user_id: UUID, avatar_id: UUID, image_url: str
    ) -> Avatar | None:
        now = dt.datetime.now(dt.UTC)
        stmt = (
            sa.update(Avatar)
            .where(Avatar.id == avatar_id)
            .where(Avatar.user_id == user_id)
            .values(image_url=image_url, updated_at=now)
            .returning(Avatar)
        )
        res = await session.execute(stmt)
        await session.flush()
        return res.scalar_one_or_none()

    async def delete_for_user(
        self, session: AsyncSession, *, user_id: UUID, avatar_id: UUID
    ) -> int:
        stmt = sa.delete(Avatar).where(Avatar.id == avatar_id).where(Avatar.user_id == user_id)
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    async def set_active_avatar(
        self, session: AsyncSession, *, user_id: UUID, avatar_id: UUID | None
    ) -> None:
        stmt = (
            sa.update(User)
            .where(User.id == user_id)
            .values(active_avatar_id=avatar_id)
        )
        await session.execute(stmt)
        await session.flush()


