"""
Private-content gating: admin AND mcp:read_private are BOTH required.

Direct tests of `can_read_private()` in `reflections.mcp.auth` — using
FastMCP's auth context to install a fake AccessToken so we don't need
a full HTTP round-trip.
"""

from __future__ import annotations

from uuid import uuid4

import pytest  # type: ignore[import-not-found]
from fastmcp.server.auth.auth import AccessToken  # type: ignore[import-not-found]


def _install_token(monkeypatch, *, scopes: list[str], is_admin: bool) -> None:
    """Patch `get_access_token` to return a synthetic token for one call."""
    tok = AccessToken(
        token="ref_mcp_FAKE",
        client_id=str(uuid4()),
        scopes=list(scopes),
        expires_at=2**31 - 1,
        claims={"user_id": "u", "scopes": scopes, "is_admin": is_admin},
    )
    # Both the auth module and FastMCP's dependencies import the same
    # symbol; patch at the call site we use.
    import reflections.mcp.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_access_token", lambda: tok)


@pytest.mark.parametrize(
    "scopes,is_admin,expected",
    [
        # Both required → only the (admin, scope) corner returns True.
        (["mcp:read", "mcp:write", "mcp:read_private"], True, True),
        (["mcp:read", "mcp:write", "mcp:read_private"], False, False),
        (["mcp:read", "mcp:write"], True, False),
        (["mcp:read", "mcp:write"], False, False),
        ([], True, False),
        ([], False, False),
    ],
)
def test_can_read_private_truth_table(monkeypatch, scopes, is_admin, expected) -> None:
    _install_token(monkeypatch, scopes=scopes, is_admin=is_admin)
    from reflections.mcp.auth import can_read_private

    assert can_read_private() is expected


def test_helpers_handle_missing_token(monkeypatch) -> None:
    """If no token is in context (shouldn't happen in production), the
    helpers must default to the SAFE answer — no admin, no scopes,
    no private access."""
    import reflections.mcp.auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_access_token", lambda: None)
    from reflections.mcp.auth import (
        can_read_private,
        current_scopes,
        current_user_is_admin,
        has_scope,
    )

    assert current_scopes() == set()
    assert has_scope("mcp:read_private") is False
    assert current_user_is_admin() is False
    assert can_read_private() is False
