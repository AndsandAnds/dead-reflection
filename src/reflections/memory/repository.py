from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.artifacts.repository import (
    artifact_entity_links_table,
    artifacts_table,
)
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
class MemoryCandidate:
    """One candidate from a single retrieval leg (vector or BM25).

    Carries the full row so the service can fuse, decay, rerank, and
    return without a second SELECT to materialize content.
    """

    row: MemoryRow
    score: float
    rank: int  # 1-based rank within the producing leg


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

    def _filter_conditions(
        self,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
        entity_ids: list[UUID] | None,
        date_from: datetime | None,
        date_to: datetime | None,
        include_private: bool,
    ) -> list[Any]:
        """Build the WHERE clauses shared by vector and BM25 candidate paths.

        Keeping this in one place is load-bearing: the two retrieval legs MUST
        see the same candidate pool for RRF to be meaningful. Privacy gate
        (`include_private=False`) flows through here unchanged.
        """
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
            link_subq = (
                sa.select(memory_entity_links_table.c.memory_item_id)
                .where(memory_entity_links_table.c.entity_id.in_(entity_ids))
                .distinct()
                .subquery()
            )
            conditions.append(memory_items.c.id.in_(sa.select(link_subq)))

        if not include_private:
            conditions.append(memory_items.c.private.is_(False))

        return conditions

    async def vector_candidates(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        query_embedding: list[float],
        limit: int,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
        entity_ids: list[UUID] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        include_private: bool = True,
    ) -> list[MemoryCandidate]:
        """Top-N candidates by pgvector inner-product similarity.

        Vectors are L2-normalized so `<#>` (negative inner product) is the
        right distance and ASC = most similar. The score returned is the
        positive similarity (so larger == more similar) to match the
        BM25 leg's convention.
        """
        emb_lit = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
        conditions = self._filter_conditions(
            user_id=user_id,
            avatar_id=avatar_id,
            include_user_scope=include_user_scope,
            include_avatar_scope=include_avatar_scope,
            include_cards=include_cards,
            include_chunks=include_chunks,
            entity_ids=entity_ids,
            date_from=date_from,
            date_to=date_to,
            include_private=include_private,
        )

        distance_expr = sa.literal_column(f"(embedding <#> '{emb_lit}'::vector)")
        stmt = (
            sa.select(
                memory_items.c.id,
                memory_items.c.user_id,
                memory_items.c.avatar_id,
                memory_items.c.scope,
                memory_items.c.kind,
                memory_items.c.content,
                memory_items.c.created_at,
                distance_expr.label("distance"),
            )
            .where(sa.and_(*conditions))
            .order_by(distance_expr.asc())
            .limit(limit)
        )

        rows = (await session.execute(stmt)).all()
        out: list[MemoryCandidate] = []
        for rank, r in enumerate(rows, start=1):
            # `<#>` returns negative inner product; flip sign so larger == better.
            score = -float(r.distance) if r.distance is not None else 0.0
            row = MemoryRow(
                id=r.id,
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            out.append(MemoryCandidate(row=row, score=score, rank=rank))
        return out

    async def bm25_candidates(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        avatar_id: UUID | None,
        query_text: str,
        limit: int,
        include_user_scope: bool,
        include_avatar_scope: bool,
        include_cards: bool,
        include_chunks: bool,
        entity_ids: list[UUID] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        include_private: bool = True,
    ) -> list[MemoryCandidate]:
        """Top-N candidates by Postgres BM25-style lexical scoring.

        Uses the `content_tsv` GENERATED STORED column + GIN index added by
        migration 0015. `ts_rank_cd` weights term frequency and proximity;
        higher == more relevant. Empty query (no tokens after parsing)
        produces no candidates.
        """
        if not (query_text or "").strip():
            return []

        conditions = self._filter_conditions(
            user_id=user_id,
            avatar_id=avatar_id,
            include_user_scope=include_user_scope,
            include_avatar_scope=include_avatar_scope,
            include_cards=include_cards,
            include_chunks=include_chunks,
            entity_ids=entity_ids,
            date_from=date_from,
            date_to=date_to,
            include_private=include_private,
        )
        # plainto_tsquery handles user phrasing without operators; ts_rank_cd
        # is the cover-density variant which rewards proximity.
        tsquery = sa.func.plainto_tsquery("english", query_text)
        tsv_col = sa.literal_column("content_tsv")
        rank_expr = sa.func.ts_rank_cd(tsv_col, tsquery)
        conditions.append(tsv_col.op("@@")(tsquery))

        stmt = (
            sa.select(
                memory_items.c.id,
                memory_items.c.user_id,
                memory_items.c.avatar_id,
                memory_items.c.scope,
                memory_items.c.kind,
                memory_items.c.content,
                memory_items.c.created_at,
                rank_expr.label("bm25_score"),
            )
            .where(sa.and_(*conditions))
            .order_by(rank_expr.desc())
            .limit(limit)
        )

        rows = (await session.execute(stmt)).all()
        out: list[MemoryCandidate] = []
        for rank, r in enumerate(rows, start=1):
            score = float(r.bm25_score) if r.bm25_score is not None else 0.0
            row = MemoryRow(
                id=r.id,
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            out.append(MemoryCandidate(row=row, score=score, rank=rank))
        return out

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
        include_private: bool = True,
        include_artifacts: bool = True,
    ) -> tuple[
        list[MemoryRow],
        list[LinkedEntityRow],
        list[tuple[UUID, UUID, str]],
        list[dict[str, Any]],  # artifact rows (id, kind, label, mtime, mime)
        list[tuple[UUID, UUID]],  # memory→artifact edges (mem_id, art_id)
        list[tuple[UUID, UUID, str]],  # artifact→entity edges
    ]:
        """
        Returns (memories, entities, mem_ent_edges, artifacts,
        mem_art_edges, art_ent_edges) for the graph view.

        - If `entity_id` is set, restricts to memories linked to that entity.
        - Otherwise, returns memories in the date range (or all if no range).
        - Entities returned are exactly those linked to the returned memories.
        - When `include_artifacts`, returns artifacts that EITHER are
          referenced by a surfaced memory (memory_items.artifact_id) OR
          have mtime in the requested date range.
        - When `include_private` is False, private memory rows are filtered
          out before the graph is built (admin-gated upstream).
        """
        mem_conds: list[Any] = [memory_items.c.user_id == user_id]
        if not include_private:
            mem_conds.append(memory_items.c.private.is_(False))
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
                memory_items.c.artifact_id,
            )
            .where(sa.and_(*mem_conds))
            .order_by(memory_items.c.created_at.desc())
            .limit(limit_memories)
        )
        raw_mems = (await session.execute(mem_stmt)).all()
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
            for r in raw_mems
        ]
        # Track memory→artifact links so we can draw edges later.
        mem_art_edges: list[tuple[UUID, UUID]] = [
            (r.id, r.artifact_id)
            for r in raw_mems
            if r.artifact_id is not None
        ]

        # --- entities linked to surfaced memories ---
        ent_rows: list[LinkedEntityRow] = []
        edges: list[tuple[UUID, UUID, str]] = []
        if mem_rows:
            mem_ids = [m.id for m in mem_rows]
            edge_stmt = sa.select(
                memory_entity_links_table.c.memory_item_id,
                memory_entity_links_table.c.entity_id,
                memory_entity_links_table.c.relation,
            ).where(
                memory_entity_links_table.c.memory_item_id.in_(mem_ids)
            )
            edges = [
                (r.memory_item_id, r.entity_id, r.relation or "")
                for r in (await session.execute(edge_stmt)).all()
            ]
            if edges:
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
                    LinkedEntityRow(
                        id=r.id, kind=r.kind, name=r.name, slug=r.slug
                    )
                    for r in (await session.execute(ent_stmt)).all()
                ]

        # --- artifacts ---
        artifact_rows: list[dict[str, Any]] = []
        art_ent_edges: list[tuple[UUID, UUID, str]] = []
        if include_artifacts:
            # Union: artifacts referenced by surfaced memories OR with
            # mtime in the requested date range. Either set may be empty.
            art_conds_outer: list[Any] = [
                artifacts_table.c.user_id == user_id
            ]
            referenced_ids = list({a for (_m, a) in mem_art_edges})
            date_or_ref: list[Any] = []
            if referenced_ids:
                date_or_ref.append(artifacts_table.c.id.in_(referenced_ids))
            range_conds: list[Any] = []
            if date_from is not None:
                range_conds.append(artifacts_table.c.mtime >= date_from)
            if date_to is not None:
                range_conds.append(artifacts_table.c.mtime <= date_to)
            if range_conds:
                date_or_ref.append(sa.and_(*range_conds))
            if date_or_ref:
                art_conds_outer.append(sa.or_(*date_or_ref))
            else:
                # No date range and no memory references → don't load every
                # artifact in the user's catalog (could be millions).
                art_conds_outer.append(sa.false())

            art_stmt = (
                sa.select(
                    artifacts_table.c.id,
                    artifacts_table.c.kind,
                    artifacts_table.c.relative_path,
                    artifacts_table.c.mtime,
                    artifacts_table.c.mime,
                )
                .where(sa.and_(*art_conds_outer))
                .order_by(artifacts_table.c.mtime.desc())
                .limit(2000)
            )
            for r in (await session.execute(art_stmt)).all():
                artifact_rows.append(
                    {
                        "id": r.id,
                        "kind": r.kind,
                        "label": r.relative_path.rsplit("/", 1)[-1],
                        "relative_path": r.relative_path,
                        "mtime": r.mtime,
                        "mime": r.mime,
                    }
                )

            if artifact_rows:
                art_ids = [a["id"] for a in artifact_rows]
                ael_stmt = sa.select(
                    artifact_entity_links_table.c.artifact_id,
                    artifact_entity_links_table.c.entity_id,
                    artifact_entity_links_table.c.relation,
                ).where(
                    artifact_entity_links_table.c.artifact_id.in_(art_ids)
                )
                art_ent_edges = [
                    (r.artifact_id, r.entity_id, r.relation or "")
                    for r in (await session.execute(ael_stmt)).all()
                ]
                # Surface any newly-referenced entities (from artifact
                # links) that weren't already loaded via memory edges.
                already = {e.id for e in ent_rows}
                new_eids = list(
                    {e[1] for e in art_ent_edges} - already
                )
                if new_eids:
                    extra_stmt = (
                        sa.select(
                            entities_table.c.id,
                            entities_table.c.kind,
                            entities_table.c.name,
                            entities_table.c.slug,
                        )
                        .where(
                            sa.and_(
                                entities_table.c.user_id == user_id,
                                entities_table.c.id.in_(new_eids),
                            )
                        )
                    )
                    for r in (await session.execute(extra_stmt)).all():
                        ent_rows.append(
                            LinkedEntityRow(
                                id=r.id, kind=r.kind, name=r.name, slug=r.slug
                            )
                        )

        return (
            mem_rows,
            ent_rows,
            edges,
            artifact_rows,
            mem_art_edges,
            art_ent_edges,
        )
