from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.mcp.exceptions import (
    McpServiceException,
    McpTokenNotFoundException,
)
from reflections.mcp.repository import (
    DEFAULT_SCOPES,
    KNOWN_SCOPES,
    McpTokenRow,
    McpTokensRepository,
)

TOKEN_PREFIX = "ref_mcp_"
TOKEN_BYTES = 32  # 256 bits of entropy


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_raw_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


@dataclass
class McpService:
    repo: McpTokensRepository

    @classmethod
    def default(cls) -> "McpService":
        return cls(repo=McpTokensRepository())

    async def mint(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        name: str,
        scopes: list[str] | None = None,
    ) -> tuple[McpTokenRow, str]:
        name_stripped = name.strip()
        if not name_stripped:
            raise McpServiceException(
                "empty_name", "Token name must be non-empty"
            )
        if scopes is None:
            effective_scopes = list(DEFAULT_SCOPES)
        else:
            # Quietly drop unknown scope strings to avoid persisting typos
            # ("mcp:rread") that would never grant anything anyway.
            effective_scopes = sorted(set(scopes) & KNOWN_SCOPES)
            if not effective_scopes:
                raise McpServiceException(
                    "no_valid_scopes",
                    f"At least one of {sorted(KNOWN_SCOPES)} must be set.",
                )
        raw = generate_raw_token()
        try:
            row = await self.repo.insert(
                session,
                token_id=uuid7_uuid(),
                user_id=user_id,
                name=name_stripped,
                token_hash=_hash(raw),
                scopes=effective_scopes,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise McpServiceException(
                "token_insert_failed", str(exc)
            ) from exc
        return row, raw

    async def list_for_user(
        self, session: AsyncSession, *, user_id: UUID
    ) -> list[McpTokenRow]:
        return await self.repo.list_for_user(session, user_id=user_id)

    async def revoke(
        self, session: AsyncSession, *, user_id: UUID, token_id: UUID
    ) -> None:
        n = await self.repo.revoke(session, user_id=user_id, token_id=token_id)
        if n == 0:
            raise McpTokenNotFoundException(
                "token_not_found",
                "No active token with that id for this user",
            )
        await session.commit()

    async def verify_and_get_user_id(
        self, session: AsyncSession, *, raw_token: str
    ) -> UUID | None:
        """Back-compat wrapper. Use `verify` for new callers."""
        result = await self.verify(session, raw_token=raw_token)
        return result[0] if result else None

    async def verify(
        self, session: AsyncSession, *, raw_token: str
    ) -> tuple[UUID, list[str]] | None:
        """
        Resolve a raw token → (user_id, scopes). Returns None on invalid
        or revoked tokens. Touches last_used_at best-effort.
        """
        if not raw_token:
            return None
        token_hash = _hash(raw_token)
        pair = await self.repo.get_active_user_and_scopes_by_token_hash(
            session, token_hash=token_hash
        )
        if pair is None:
            return None
        try:
            await self.repo.touch_last_used(session, token_hash=token_hash)
            await session.commit()
        except Exception:
            await session.rollback()
        return pair
