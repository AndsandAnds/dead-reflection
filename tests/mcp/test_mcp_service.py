from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

import pytest  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.mcp.exceptions import McpTokenNotFoundException
from reflections.mcp.repository import McpTokenRow
from reflections.mcp.service import McpService, _hash


@dataclass
class FakeRepo:
    rows: list[McpTokenRow] = field(default_factory=list)
    hashes_by_id: dict[UUID, str] = field(default_factory=dict)
    scopes_by_id: dict[UUID, list[str]] = field(default_factory=dict)

    async def insert(
        self,
        _session,
        *,
        token_id: UUID,
        user_id: UUID,
        name: str,
        token_hash: str,
        scopes: list[str] | None = None,
    ) -> McpTokenRow:
        eff = scopes if scopes is not None else ["mcp:read", "mcp:write"]
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
        self.hashes_by_id[token_id] = token_hash
        self.scopes_by_id[token_id] = eff
        return row

    async def list_for_user(self, _session, *, user_id: UUID):
        return [r for r in self.rows if r.user_id == user_id]

    async def revoke(self, _session, *, user_id: UUID, token_id: UUID) -> int:
        for i, r in enumerate(self.rows):
            if r.id == token_id and r.user_id == user_id and r.revoked_at is None:
                self.rows[i] = McpTokenRow(
                    id=r.id,
                    user_id=r.user_id,
                    name=r.name,
                    scopes=r.scopes,
                    created_at=r.created_at,
                    last_used_at=r.last_used_at,
                    revoked_at=dt.datetime.now(dt.UTC),
                )
                return 1
        return 0

    async def get_active_user_id_by_token_hash(
        self, _session, *, token_hash: str
    ) -> UUID | None:
        pair = await self.get_active_user_and_scopes_by_token_hash(
            _session, token_hash=token_hash
        )
        return pair[0] if pair else None

    async def get_active_user_and_scopes_by_token_hash(
        self, _session, *, token_hash: str
    ):
        for r in self.rows:
            if (
                self.hashes_by_id.get(r.id) == token_hash
                and r.revoked_at is None
            ):
                return r.user_id, list(self.scopes_by_id.get(r.id, []))
        return None

    async def touch_last_used(self, _session, *, token_hash: str) -> None:
        # No-op in fake.
        return None


class FakeSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.anyio
async def test_mint_returns_raw_token_and_persists_hash() -> None:
    repo = FakeRepo()
    svc = McpService(repo=repo)  # type: ignore[arg-type]
    user_id = uuid7_uuid()

    row, raw = await svc.mint(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        name="Claude Desktop",
    )

    assert raw.startswith("ref_mcp_")
    assert row.user_id == user_id
    assert row.name == "Claude Desktop"
    # Stored hash matches what we just got back.
    assert repo.hashes_by_id[row.id] == _hash(raw)


@pytest.mark.anyio
async def test_verify_roundtrips_and_revoke_invalidates() -> None:
    repo = FakeRepo()
    svc = McpService(repo=repo)  # type: ignore[arg-type]
    user_id = uuid7_uuid()
    row, raw = await svc.mint(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        name="t",
    )

    verified = await svc.verify_and_get_user_id(
        FakeSession(),  # type: ignore[arg-type]
        raw_token=raw,
    )
    assert verified == user_id

    await svc.revoke(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        token_id=row.id,
    )

    after = await svc.verify_and_get_user_id(
        FakeSession(),  # type: ignore[arg-type]
        raw_token=raw,
    )
    assert after is None


@pytest.mark.anyio
async def test_verify_empty_or_unknown_returns_none() -> None:
    repo = FakeRepo()
    svc = McpService(repo=repo)  # type: ignore[arg-type]

    assert await svc.verify_and_get_user_id(
        FakeSession(),  # type: ignore[arg-type]
        raw_token="",
    ) is None
    assert await svc.verify_and_get_user_id(
        FakeSession(),  # type: ignore[arg-type]
        raw_token="ref_mcp_nope",
    ) is None


@pytest.mark.anyio
async def test_revoke_unknown_raises_not_found() -> None:
    repo = FakeRepo()
    svc = McpService(repo=repo)  # type: ignore[arg-type]
    with pytest.raises(McpTokenNotFoundException):
        await svc.revoke(
            FakeSession(),  # type: ignore[arg-type]
            user_id=uuid7_uuid(),
            token_id=uuid7_uuid(),
        )
