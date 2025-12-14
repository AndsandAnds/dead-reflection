from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.auth.models import User
from reflections.auth.crypto import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from reflections.auth.exceptions import (
    AuthServiceException,
    AuthServiceNotFoundException,
    AuthServiceUnprocessableException,
)
from reflections.auth.repository import AuthRepository
from reflections.commons.ids import uuid7_uuid
from reflections.core.settings import settings


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class AuthService:
    repo: AuthRepository

    @classmethod
    def create(cls) -> "AuthService":
        return cls(repo=AuthRepository())

    async def signup(
        self, session: AsyncSession, *, email: str, name: str, password: str
    ) -> tuple[User, str]:
        existing = await self.repo.get_user_by_email(session, email=email)
        if existing is not None:
            raise AuthServiceUnprocessableException(
                "email_taken", "A user with this email already exists"
            )

        user_id = uuid7_uuid()
        pw_hash = hash_password(password)
        user = await self.repo.insert_user(
            session, user_id=user_id, email=email, name=name, password_hash=pw_hash
        )

        token = new_session_token()
        await self._create_session(
            session,
            user_id=user.id,
            token=token,
            user_agent=None,
            ip=None,
        )
        await session.commit()
        return user, token

    async def login(
        self, session: AsyncSession, *, email: str, password: str
    ) -> tuple[User, str]:
        user = await self.repo.get_user_by_email(session, email=email)
        if user is None:
            raise AuthServiceNotFoundException("invalid_credentials", "User not found")

        if user.disabled_at is not None:
            raise AuthServiceException("user_disabled", "User is disabled")

        if not verify_password(password, user.password_hash):
            raise AuthServiceNotFoundException(
                "invalid_credentials", "Invalid email or password"
            )

        token = new_session_token()
        await self._create_session(
            session,
            user_id=user.id,
            token=token,
            user_agent=None,
            ip=None,
        )
        await self.repo.touch_last_login(session, user_id=user.id)
        await session.commit()
        return user, token

    async def logout(self, session: AsyncSession, *, token: str) -> None:
        token_hash = hash_session_token(token)
        await self.repo.revoke_session(session, token_hash=token_hash)
        await session.commit()

    async def get_user_for_session_token(
        self, session: AsyncSession, *, token: str
    ) -> Optional[User]:
        token_hash = hash_session_token(token)
        now = _utcnow()
        s = await self.repo.get_active_session_by_token_hash(
            session, token_hash=token_hash, now=now
        )
        if s is None:
            return None
        return await self.repo.get_user_by_id(session, user_id=s.user_id)

    async def _create_session(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        token: str,
        user_agent: str | None,
        ip: str | None,
    ) -> None:
        ttl_days = int(settings.AUTH_SESSION_TTL_DAYS)
        expires_at = _utcnow() + dt.timedelta(days=ttl_days)
        await self.repo.insert_session(
            session,
            session_id=uuid7_uuid(),
            user_id=user_id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )


