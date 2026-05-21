from __future__ import annotations

import datetime as dt
from uuid import UUID

from fastmcp.server.auth.auth import AccessToken, TokenVerifier  # type: ignore[import-not-found]
from fastmcp.server.dependencies import get_access_token  # type: ignore[import-not-found]

from reflections.auth.repository import AuthRepository
from reflections.commons.logging import logger
from reflections.core.db import database_manager
from reflections.mcp.service import McpService


class ReflectionsTokenVerifier(TokenVerifier):
    """
    Verifies an MCP bearer token against the `mcp_tokens` table and stamps the
    resulting AccessToken with the user_id in `client_id`, the token's scopes,
    and the user's current `is_admin` flag (re-checked every verify so a
    demoted user immediately loses elevated tool access).

    Tool implementations read these back via `current_user_id()`,
    `has_scope(...)`, `current_user_is_admin()`, and `can_read_private()`.
    """

    def __init__(self, service: McpService | None = None) -> None:
        super().__init__(required_scopes=None)
        self._service = service or McpService.default()
        self._auth = AuthRepository()

    async def verify_token(self, token: str) -> AccessToken | None:
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                pair = await self._service.verify(
                    session, raw_token=token
                )
                is_admin = False
                if pair is not None:
                    user = await self._auth.get_user_by_id(
                        session, user_id=pair[0]
                    )
                    is_admin = bool(getattr(user, "is_admin", False))
        except Exception as exc:
            logger.warning("mcp_token_verify_error: %s", exc)
            return None
        if pair is None:
            return None
        user_id, scopes = pair
        return AccessToken(
            token=token,
            client_id=str(user_id),
            scopes=list(scopes),
            # No hard expiry on tokens; revocation is via the mcp_tokens table.
            expires_at=int(
                (
                    dt.datetime.now(dt.UTC) + dt.timedelta(days=365)
                ).timestamp()
            ),
            claims={
                "user_id": str(user_id),
                "scopes": list(scopes),
                "is_admin": is_admin,
            },
        )


def current_user_id() -> UUID:
    """
    Extract the authenticated user_id inside an MCP tool. Raises ValueError if
    called outside an authenticated request (which should never happen because
    the TokenVerifier gates every call).
    """
    token = get_access_token()
    if token is None or not token.client_id:
        raise ValueError("MCP request is not authenticated")
    return UUID(token.client_id)


def current_scopes() -> set[str]:
    """Scopes carried on the caller's MCP token, as a set for `in` checks."""
    token = get_access_token()
    if token is None:
        return set()
    return set(token.scopes or [])


def has_scope(scope: str) -> bool:
    return scope in current_scopes()


def current_user_is_admin() -> bool:
    """Read the admin flag stamped on the token at verify time."""
    token = get_access_token()
    if token is None:
        return False
    claims = token.claims or {}
    return bool(claims.get("is_admin"))


def can_read_private() -> bool:
    """
    Gate for surfacing memory_items.private content via MCP tools.

    Two conditions must hold:
      1. The token carries the `mcp:read_private` scope (opt-in at mint).
      2. The user the token belongs to is currently an admin.

    The second check is fresh per-verify, so demoting a user immediately
    revokes private-content access from every token they hold without
    needing to revoke each token individually.
    """
    return has_scope("mcp:read_private") and current_user_is_admin()
