from __future__ import annotations

import datetime as dt
from uuid import UUID

from fastmcp.server.auth.auth import AccessToken, TokenVerifier  # type: ignore[import-not-found]
from fastmcp.server.dependencies import get_access_token  # type: ignore[import-not-found]

from reflections.commons.logging import logger
from reflections.core.db import database_manager
from reflections.mcp.service import McpService


class ReflectionsTokenVerifier(TokenVerifier):
    """
    Verifies an MCP bearer token against the `mcp_tokens` table and stamps the
    resulting AccessToken with the user_id in `client_id`. Tool implementations
    read it back via `current_user_id()`.
    """

    def __init__(self, service: McpService | None = None) -> None:
        super().__init__(required_scopes=None)
        self._service = service or McpService.default()

    async def verify_token(self, token: str) -> AccessToken | None:
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                user_id = await self._service.verify_and_get_user_id(
                    session, raw_token=token
                )
        except Exception as exc:
            logger.warning("mcp_token_verify_error: %s", exc)
            return None
        if user_id is None:
            return None
        return AccessToken(
            token=token,
            client_id=str(user_id),
            scopes=["mcp:read", "mcp:write"],
            # No hard expiry on tokens; revocation is via the mcp_tokens table.
            expires_at=int(
                (
                    dt.datetime.now(dt.UTC) + dt.timedelta(days=365)
                ).timestamp()
            ),
            claims={"user_id": str(user_id)},
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
