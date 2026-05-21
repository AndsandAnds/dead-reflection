"""MCP scope plumbing: mint accepts scopes, verify round-trips them."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

import pytest  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.mcp.exceptions import McpServiceException
from reflections.mcp.repository import (
    DEFAULT_SCOPES,
    McpTokenRow,
)
from reflections.mcp.service import McpService, _hash


@dataclass
class FakeRepo:
    rows: list[McpTokenRow] = field(default_factory=list)
    hashes: dict[UUID, str] = field(default_factory=dict)
    scopes_by_id: dict[UUID, list[str]] = field(default_factory=dict)

    async def insert(
        self,
        _s,
        *,
        token_id,
        user_id,
        name,
        token_hash,
        scopes=None,
    ):
        eff = scopes if scopes is not None else list(DEFAULT_SCOPES)
        row = McpTokenRow(
            id=token_id,
            user_id=user_id,
            name=name,
            scopes=eff,
            created_at=dt.datetime.now(dt.UTC),
            last_used_at=None,
            revoked_at=None,
        )
        self.rows.append(row)
        self.hashes[token_id] = token_hash
        self.scopes_by_id[token_id] = eff
        return row

    async def get_active_user_and_scopes_by_token_hash(
        self, _s, *, token_hash
    ):
        for r in self.rows:
            if self.hashes.get(r.id) == token_hash and r.revoked_at is None:
                return r.user_id, list(self.scopes_by_id.get(r.id, []))
        return None

    async def get_active_user_id_by_token_hash(self, _s, *, token_hash):
        pair = await self.get_active_user_and_scopes_by_token_hash(
            None, token_hash=token_hash
        )
        return pair[0] if pair else None

    async def touch_last_used(self, _s, *, token_hash):
        return None


class FakeSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.anyio
async def test_mint_default_scopes_do_not_include_read_private() -> None:
    svc = McpService(repo=FakeRepo())  # type: ignore[arg-type]
    row, _raw = await svc.mint(
        FakeSession(),  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        name="Claude Desktop",
    )
    assert "mcp:read" in row.scopes
    assert "mcp:write" in row.scopes
    assert "mcp:read_private" not in row.scopes


@pytest.mark.anyio
async def test_mint_with_explicit_scopes_includes_read_private() -> None:
    svc = McpService(repo=FakeRepo())  # type: ignore[arg-type]
    row, _raw = await svc.mint(
        FakeSession(),  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        name="trusted",
        scopes=["mcp:read", "mcp:write", "mcp:read_private"],
    )
    assert "mcp:read_private" in row.scopes


@pytest.mark.anyio
async def test_mint_filters_unknown_scopes() -> None:
    svc = McpService(repo=FakeRepo())  # type: ignore[arg-type]
    row, _raw = await svc.mint(
        FakeSession(),  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        name="x",
        scopes=["mcp:read", "mcp:bogus"],
    )
    assert "mcp:bogus" not in row.scopes
    assert "mcp:read" in row.scopes


@pytest.mark.anyio
async def test_mint_rejects_all_unknown_scopes() -> None:
    svc = McpService(repo=FakeRepo())  # type: ignore[arg-type]
    with pytest.raises(McpServiceException):
        await svc.mint(
            FakeSession(),  # type: ignore[arg-type]
            user_id=uuid7_uuid(),
            name="x",
            scopes=["completely:unknown"],
        )


@pytest.mark.anyio
async def test_verify_returns_user_and_scopes() -> None:
    svc = McpService(repo=FakeRepo())  # type: ignore[arg-type]
    user = uuid7_uuid()
    row, raw = await svc.mint(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user,
        name="x",
        scopes=["mcp:read", "mcp:read_private"],
    )
    out = await svc.verify(
        FakeSession(),  # type: ignore[arg-type]
        raw_token=raw,
    )
    assert out is not None
    uid, scopes = out
    assert uid == user
    assert "mcp:read_private" in scopes
