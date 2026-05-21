from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.entities.repository import (
    entities_table,
    memory_entity_links_table,
)

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


@dataclass(frozen=True)
class LinkedEntityRow:
    id: UUID
    kind: str
    name: str
    slug: str


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
    # Phase 8a: pointer back to the source artifact when this chunk came
    # from an extractor (PDF page, audio segment, image caption, ...).
    sa.Column("artifact_id", sa.Uuid(), nullable=True),
    sa.Column("artifact_locator", sa.JSON(), nullable=True),
    # Phase 8e: when true, the chunk is excluded from MCP recall
    # responses unless the caller's token has the `mcp:read_private`
    # scope. Web UI (session cookie) sees everything regardless.
    sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        include_private: bool = True,
    ) -> list[MemoryRow]:
        conditions: list[Any] = [memory_items.c.user_id == user_id]
        if not include_private:
            conditions.append(memory_items.c.private.is_(False))

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
        artifact_id: UUID | None = None,
        artifact_locator: dict[str, Any] | None = None,
        private: bool = False,
    ) -> UUID:
        """
        Insert a memory row.

        No error handling here; service owns exceptions/transactions.
        """
        item_id = uuid7_uuid()
        # Pass embedding as pgvector literal: '[0.1,0.2,...]'
        embedding_literal = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        # IMPORTANT: The Postgres column type is `vector`, so we must explicitly
        # cast the literal; otherwise SQLAlchemy will bind it as VARCHAR.
        embedding_expr = sa.literal_column(f"'{embedding_literal}'::vector")
        stmt = (
            sa.insert(memory_items)
            .values(
                id=item_id,
                user_id=user_id,
                avatar_id=avatar_id,
                scope=scope,
                kind=kind,
                content=content,
                embedding=embedding_expr,
                source_session_id=source_session_id,
                artifact_id=artifact_id,
                artifact_locator=artifact_locator,
                private=private,
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
        entity_ids: list[UUID] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        include_private: bool = True,
    ) -> list[MemoryRow]:
        """
        Vector search using pgvector inner product (vectors are L2-normalized).

        We use `<#>` operator (negative inner product distance) so ASC order is
        "most similar". Supports optional filtering by linked entities and
        a created_at date range.
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

        if date_from is not None:
            conditions.append(memory_items.c.created_at >= date_from)
        if date_to is not None:
            conditions.append(memory_items.c.created_at <= date_to)

        if entity_ids:
            # Restrict to memories linked to ANY of the supplied entities.
            link_subq = (
                sa.select(memory_entity_links_table.c.memory_item_id)
                .where(memory_entity_links_table.c.entity_id.in_(entity_ids))
                .distinct()
                .subquery()
            )
            conditions.append(memory_items.c.id.in_(sa.select(link_subq)))

        if not include_private:
            conditions.append(memory_items.c.private.is_(False))

        # SQLAlchemy 2.x: a TextClause is not orderable on its own; use
        # literal_column so we can apply .asc() and keep ASC explicit.
        order_expr = sa.literal_column(
            f"embedding <#> '{emb_lit}'::vector"
        ).asc()

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
            .order_by(order_expr)
            .limit(top_k)
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

    async def get_linked_entities(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory_ids: list[UUID],
    ) -> dict[UUID, list[LinkedEntityRow]]:
        """
        Bulk-fetch entity links for a list of memory ids. Returns a dict
        keyed by memory_item_id. Entities not owned by the user are excluded
        (defense-in-depth even though links should always match user).
        """
        if not memory_ids:
            return {}
        stmt = (
            sa.select(
                memory_entity_links_table.c.memory_item_id,
                entities_table.c.id,
                entities_table.c.kind,
                entities_table.c.name,
                entities_table.c.slug,
            )
            .join(
                entities_table,
                entities_table.c.id == memory_entity_links_table.c.entity_id,
            )
            .where(
                sa.and_(
                    memory_entity_links_table.c.memory_item_id.in_(memory_ids),
                    entities_table.c.user_id == user_id,
                )
            )
            .order_by(entities_table.c.kind, entities_table.c.name)
        )
        out: dict[UUID, list[LinkedEntityRow]] = {mid: [] for mid in memory_ids}
        for r in (await session.execute(stmt)).all():
            out[r.memory_item_id].append(
                LinkedEntityRow(id=r.id, kind=r.kind, name=r.name, slug=r.slug)
            )
        return out

    async def update_content(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory_id: UUID,
        content: str,
        embedding: list[float],
    ) -> int:
        """Replace the content + embedding of a memory the caller owns."""
        emb_lit = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        emb_expr = sa.literal_column(f"'{emb_lit}'::vector")
        stmt = (
            sa.update(memory_items)
            .where(
                sa.and_(
                    memory_items.c.id == memory_id,
                    memory_items.c.user_id == user_id,
                )
            )
            .values(content=content, embedding=emb_expr)
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory_id: UUID,
    ) -> MemoryRow | None:
        stmt = sa.select(
            memory_items.c.id,
            memory_items.c.user_id,
            memory_items.c.avatar_id,
            memory_items.c.scope,
            memory_items.c.kind,
            memory_items.c.content,
            memory_items.c.created_at,
        ).where(
            sa.and_(
                memory_items.c.id == memory_id,
                memory_items.c.user_id == user_id,
            )
        )
        r = (await session.execute(stmt)).first()
        if r is None:
            return None
        return MemoryRow(
            id=r.id,
            user_id=r.user_id,
            avatar_id=r.avatar_id,
            scope=r.scope,
            kind=r.kind,
            content=r.content,
            created_at=r.created_at,
        )

    async def graph(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        entity_id: UUID | None = None,
        limit_memories: int = 500,
    ) -> tuple[
        list[MemoryRow],
        list[LinkedEntityRow],
        list[tuple[UUID, UUID, str]],
    ]:
        """
        Returns (memories, entities, edges) for the graph view.

        - If `entity_id` is set, restricts to memories linked to that entity.
        - Otherwise, returns memories in the date range (or all if no range).
        - Entities returned are exactly those linked to the returned memories.
        - Edges are (memory_item_id, entity_id, relation) tuples.
        """
        mem_conds: list[Any] = [memory_items.c.user_id == user_id]
        if date_from is not None:
            mem_conds.append(memory_items.c.created_at >= date_from)
        if date_to is not None:
            mem_conds.append(memory_items.c.created_at <= date_to)

        if entity_id is not None:
            link_subq = (
                sa.select(memory_entity_links_table.c.memory_item_id)
                .where(memory_entity_links_table.c.entity_id == entity_id)
                .subquery()
            )
            mem_conds.append(memory_items.c.id.in_(sa.select(link_subq)))

        mem_stmt = (
            sa.select(
                memory_items.c.id,
                memory_items.c.user_id,
                memory_items.c.avatar_id,
                memory_items.c.scope,
                memory_items.c.kind,
                memory_items.c.content,
                memory_items.c.created_at,
            )
            .where(sa.and_(*mem_conds))
            .order_by(memory_items.c.created_at.desc())
            .limit(limit_memories)
        )
        mem_rows = [
            MemoryRow(
                id=r.id,
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            for r in (await session.execute(mem_stmt)).all()
        ]
        if not mem_rows:
            return [], [], []

        mem_ids = [m.id for m in mem_rows]
        edge_stmt = (
            sa.select(
                memory_entity_links_table.c.memory_item_id,
                memory_entity_links_table.c.entity_id,
                memory_entity_links_table.c.relation,
            )
            .where(memory_entity_links_table.c.memory_item_id.in_(mem_ids))
        )
        edges = [
            (r.memory_item_id, r.entity_id, r.relation or "")
            for r in (await session.execute(edge_stmt)).all()
        ]
        if not edges:
            return mem_rows, [], []

        entity_ids = list({e[1] for e in edges})
        ent_stmt = (
            sa.select(
                entities_table.c.id,
                entities_table.c.kind,
                entities_table.c.name,
                entities_table.c.slug,
            )
            .where(
                sa.and_(
                    entities_table.c.user_id == user_id,
                    entities_table.c.id.in_(entity_ids),
                )
            )
            .order_by(entities_table.c.kind, entities_table.c.name)
        )
        ent_rows = [
            LinkedEntityRow(id=r.id, kind=r.kind, name=r.name, slug=r.slug)
            for r in (await session.execute(ent_stmt)).all()
        ]
        return mem_rows, ent_rows, edges
