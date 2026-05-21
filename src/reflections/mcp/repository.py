from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

metadata = sa.MetaData()


mcp_tokens_table = sa.Table(
    "mcp_tokens",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
    sa.Column("scopes", sa.JSON(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
)


@dataclass(frozen=True)
class McpTokenRow:
    id: UUID
    user_id: UUID
    name: str
    scopes: list[str]
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    revoked_at: dt.datetime | None


def _row(r) -> McpTokenRow:  # type: ignore[no-untyped-def]
    raw_scopes = getattr(r, "scopes", None) or []
    if not isinstance(raw_scopes, list):
        raw_scopes = []
    return McpTokenRow(
        id=r.id,
        user_id=r.user_id,
        name=r.name,
        scopes=[str(s) for s in raw_scopes],
        created_at=r.created_at,
        last_used_at=r.last_used_at,
        revoked_at=r.revoked_at,
    )


# Default scopes minted for every token. `mcp:read_private` is OPT-IN
# at mint time so non-private content is the default visibility.
DEFAULT_SCOPES = ["mcp:read", "mcp:write"]
KNOWN_SCOPES = frozenset(
    {"mcp:read", "mcp:write", "mcp:read_private"}
)


@dataclass(frozen=True)
class McpTokensRepository:
    async def insert(
        self,
        session: AsyncSession,
        *,
        token_id: UUID,
        user_id: UUID,
        name: str,
        token_hash: str,
        scopes: list[str] | None = None,
    ) -> McpTokenRow:
        stmt = (
            sa.insert(mcp_tokens_table)
            .values(
                id=token_id,
                user_id=user_id,
                name=name,
                token_hash=token_hash,
                scopes=scopes if scopes is not None else list(DEFAULT_SCOPES),
            )
            .returning(
                mcp_tokens_table.c.id,
                mcp_tokens_table.c.user_id,
                mcp_tokens_table.c.name,
                mcp_tokens_table.c.scopes,
                mcp_tokens_table.c.created_at,
                mcp_tokens_table.c.last_used_at,
                mcp_tokens_table.c.revoked_at,
            )
        )
        r = (await session.execute(stmt)).first()
        await session.flush()
        return _row(r)

    async def list_for_user(
        self, session: AsyncSession, *, user_id: UUID
    ) -> list[McpTokenRow]:
        stmt = (
            sa.select(
                mcp_tokens_table.c.id,
                mcp_tokens_table.c.user_id,
                mcp_tokens_table.c.name,
                mcp_tokens_table.c.scopes,
                mcp_tokens_table.c.created_at,
                mcp_tokens_table.c.last_used_at,
                mcp_tokens_table.c.revoked_at,
            )
            .where(mcp_tokens_table.c.user_id == user_id)
            .order_by(mcp_tokens_table.c.created_at.desc())
        )
        rows = (await session.execute(stmt)).all()
        return [_row(r) for r in rows]

    async def revoke(
        self, session: AsyncSession, *, user_id: UUID, token_id: UUID
    ) -> int:
        stmt = (
            sa.update(mcp_tokens_table)
            .where(
                sa.and_(
                    mcp_tokens_table.c.id == token_id,
                    mcp_tokens_table.c.user_id == user_id,
                    mcp_tokens_table.c.revoked_at.is_(None),
                )
            )
            .values(revoked_at=sa.func.now())
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    async def get_active_user_id_by_token_hash(
        self, session: AsyncSession, *, token_hash: str
    ) -> UUID | None:
        stmt = sa.select(mcp_tokens_table.c.user_id).where(
            sa.and_(
                mcp_tokens_table.c.token_hash == token_hash,
                mcp_tokens_table.c.revoked_at.is_(None),
            )
        )
        r = (await session.execute(stmt)).first()
        return r.user_id if r else None

    async def get_active_user_and_scopes_by_token_hash(
        self, session: AsyncSession, *, token_hash: str
    ) -> tuple[UUID, list[str]] | None:
        """Same lookup as get_active_user_id_by_token_hash but also
        returns the token's scopes for downstream gating."""
        stmt = sa.select(
            mcp_tokens_table.c.user_id, mcp_tokens_table.c.scopes
        ).where(
            sa.and_(
                mcp_tokens_table.c.token_hash == token_hash,
                mcp_tokens_table.c.revoked_at.is_(None),
            )
        )
        r = (await session.execute(stmt)).first()
        if r is None:
            return None
        raw = r.scopes or list(DEFAULT_SCOPES)
        if not isinstance(raw, list):
            raw = list(DEFAULT_SCOPES)
        return r.user_id, [str(s) for s in raw]

    async def touch_last_used(
        self, session: AsyncSession, *, token_hash: str
    ) -> None:
        stmt = (
            sa.update(mcp_tokens_table)
            .where(mcp_tokens_table.c.token_hash == token_hash)
            .values(last_used_at=sa.func.now())
        )
        await session.execute(stmt)
        await session.flush()
