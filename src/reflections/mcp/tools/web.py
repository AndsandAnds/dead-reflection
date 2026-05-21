"""MCP tools for outbound web access. Admin-only by construction."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from reflections.auth.repository import AuthRepository
from reflections.core.db import database_manager
from reflections.mcp.auth import current_user_id
from reflections.outbound.exceptions import OutboundForbiddenException
from reflections.outbound.service import OutboundService, UserCtx

_outbound: OutboundService | None = None
_auth_repo: AuthRepository | None = None


def _outbound_service() -> OutboundService:
    global _outbound
    if _outbound is None:
        _outbound = OutboundService.default()
    return _outbound


def _auth_repository() -> AuthRepository:
    global _auth_repo
    if _auth_repo is None:
        _auth_repo = AuthRepository()
    return _auth_repo


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    @mcp.tool
    async def internet_search(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        top_k: Annotated[int, Field(ge=1, le=20)] = 5,
    ) -> dict:
        """
        Search the public web (DuckDuckGo Lite) for the given query.

        ADMIN ONLY. Non-admin callers receive an `internet_forbidden` error.
        Every attempt — successful or denied — is recorded to
        outbound_audit_log so the admin can see who tried what.

        Returns: {query, hits: [{title, url, snippet}]}
        """
        uid = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            user = await _auth_repository().get_user_by_id(session, user_id=uid)
            if user is None:
                # Token resolves to a user_id but the user vanished — treat as
                # forbidden rather than 500.
                raise OutboundForbiddenException(
                    "user_not_found",
                    "Authenticated user no longer exists",
                )
            ctx = UserCtx(id=user.id, is_admin=bool(user.is_admin))
            result = await _outbound_service().internet_search(
                session, user=ctx, query=query, top_k=top_k
            )
        return result.model_dump(mode="json")
