from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.auth.models import Session, User


@dataclass(frozen=True)
class AuthRepository:
    async def get_user_by_email(
        self, session: AsyncSession, *, email: str
    ) -> User | None:
        stmt = sa.select(User).where(sa.func.lower(User.email) == email.lower())
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_user_by_id(self, session: AsyncSession, *, user_id: UUID) -> User | None:
        stmt = sa.select(User).where(User.id == user_id)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def insert_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        email: str,
        name: str,
        password_hash: str,
    ) -> User:
        user = User(
            id=user_id, email=email.lower(), name=name.strip(), password_hash=password_hash
        )
        session.add(user)
        await session.flush()
        return user

    async def touch_last_login(self, session: AsyncSession, *, user_id: UUID) -> None:
        stmt = (
            sa.update(User)
            .where(User.id == user_id)
            .values(last_login_at=sa.func.now())
        )
        await session.execute(stmt)
        await session.flush()

    async def insert_session(
        self,
        session: AsyncSession,
        *,
        session_id: UUID,
        user_id: UUID,
        token_hash: str,
        expires_at: dt.datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> Session:
        s = Session(
            id=session_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        session.add(s)
        await session.flush()
        return s

    async def get_active_session_by_token_hash(
        self, session: AsyncSession, *, token_hash: str, now: dt.datetime
    ) -> Session | None:
        stmt = (
            sa.select(Session)
            .where(Session.token_hash == token_hash)
            .where(Session.revoked_at.is_(None))
            .where(Session.expires_at > now)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def revoke_session(
        self, session: AsyncSession, *, token_hash: str
    ) -> int:
        stmt = (
            sa.update(Session)
            .where(Session.token_hash == token_hash)
            .where(Session.revoked_at.is_(None))
            .values(revoked_at=sa.func.now())
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)


