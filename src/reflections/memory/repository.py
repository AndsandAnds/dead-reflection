from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid

MemoryScope = Literal["user", "avatar"]
MemoryKind = Literal["card", "chunk"]


@dataclass(frozen=True)
class MemoryRow:
    id: UUID
    user_id: UUID
    avatar_id: UUID | None
    scope: MemoryScope
    kind: MemoryKind
    content: str
    created_at: datetime


metadata = sa.MetaData()


memory_items = sa.Table(
    "memory_items",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("avatar_id", sa.Uuid(), nullable=True),
    sa.Column("scope", sa.Text(), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("content", sa.Text(), nullable=False),
    # We store as pgvector in Postgres; for type-checking we keep as Text here and
    # rely on raw SQL operator usage.
    sa.Column("embedding", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column("source_session_id", sa.Text(), nullable=True),
    sa.Column("metadata", sa.JSON(), nullable=True),
)


class MemoryRepository:
    async def list_items(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        limit: int,
        offset: int,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
    ) -> list[MemoryRow]:
        conditions: list[Any] = [memory_items.c.user_id == user_id]

        scope_conds: list[Any] = []
        if include_user_scope:
            scope_conds.append(memory_items.c.scope == "user")
        if include_avatar_scope and avatar_id is not None:
            scope_conds.append(
                sa.and_(
                    memory_items.c.scope == "avatar",
                    memory_items.c.avatar_id == avatar_id,
                )
            )
        if scope_conds:
            conditions.append(sa.or_(*scope_conds))

        kind_conds: list[Any] = []
        if include_cards:
            kind_conds.append(memory_items.c.kind == "card")
        if include_chunks:
            kind_conds.append(memory_items.c.kind == "chunk")
        if kind_conds:
            conditions.append(sa.or_(*kind_conds))

        stmt = (
            sa.select(
                memory_items.c.id,
                memory_items.c.user_id,
                memory_items.c.avatar_id,
                memory_items.c.scope,
                memory_items.c.kind,
                memory_items.c.content,
                memory_items.c.created_at,
            )
            .where(sa.and_(*conditions))
            .order_by(memory_items.c.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        rows = (await session.execute(stmt)).all()
        return [
            MemoryRow(
                id=r.id,
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def delete_items(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        ids: list[UUID],
    ) -> int:
        stmt = sa.delete(memory_items).where(
            sa.and_(memory_items.c.user_id == user_id, memory_items.c.id.in_(ids))
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    async def insert_item(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        scope: MemoryScope,
        kind: MemoryKind,
        content: str,
        embedding: list[float],
        source_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """
        Insert a memory row.

        No error handling here; service owns exceptions/transactions.
        """
        item_id = uuid7_uuid()
        # Pass embedding as pgvector literal: '[0.1,0.2,...]'
        embedding_literal = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        stmt = (
            sa.insert(memory_items)
            .values(
                id=item_id,
                user_id=user_id,
                avatar_id=avatar_id,
                scope=scope,
                kind=kind,
                content=content,
                embedding=embedding_literal,
                source_session_id=source_session_id,
                metadata=metadata,
            )
            .returning(memory_items.c.id)
        )
        res = await session.execute(stmt)
        await session.flush()
        return res.scalar_one()

    async def search(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        query_embedding: list[float],
        top_k: int,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
    ) -> list[MemoryRow]:
        """
        Vector search using pgvector inner product (vectors are L2-normalized).

        We use `<#>` operator (negative inner product distance) so ASC order is
        "most similar".
        """
        emb_lit = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"

        conditions: list[Any] = [memory_items.c.user_id == user_id]

        scope_conds: list[Any] = []
        if include_user_scope:
            scope_conds.append(memory_items.c.scope == "user")
        if include_avatar_scope and avatar_id is not None:
            scope_conds.append(
                sa.and_(
                    memory_items.c.scope == "avatar",
                    memory_items.c.avatar_id == avatar_id,
                )
            )
        if scope_conds:
            conditions.append(sa.or_(*scope_conds))

        kind_conds: list[Any] = []
        if include_cards:
            kind_conds.append(memory_items.c.kind == "card")
        if include_chunks:
            kind_conds.append(memory_items.c.kind == "chunk")
        if kind_conds:
            conditions.append(sa.or_(*kind_conds))

        order_expr = sa.text(f"embedding <#> '{emb_lit}'::vector")

        stmt = (
            sa.select(
                memory_items.c.id,
                memory_items.c.user_id,
                memory_items.c.avatar_id,
                memory_items.c.scope,
                memory_items.c.kind,
                memory_items.c.content,
                memory_items.c.created_at,
            )
            .where(sa.and_(*conditions))
            .order_by(order_expr.asc())
            .limit(top_k)
        )

        rows = (await session.execute(stmt)).all()
        return [
            MemoryRow(
                id=str(r.id),
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            for r in rows
        ]
