from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.entities.schemas import EntityKind

metadata = sa.MetaData()


entities_table = sa.Table(
    "entities",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("slug", sa.Text(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("attributes", sa.JSON(), nullable=True),
    # pgvector(384) in Postgres; opaque to SQLAlchemy here (raw text in/out).
    sa.Column("embedding", sa.Text(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
)


memory_entity_links_table = sa.Table(
    "memory_entity_links",
    metadata,
    sa.Column("memory_item_id", sa.Uuid(), primary_key=True, nullable=False),
    sa.Column("entity_id", sa.Uuid(), primary_key=True, nullable=False),
    sa.Column("relation", sa.Text(), primary_key=True, nullable=False, default=""),
    sa.Column("weight", sa.Float(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return s or "unnamed"


@dataclass(frozen=True)
class EntityRow:
    id: UUID
    user_id: UUID
    kind: EntityKind
    name: str
    slug: str
    description: str | None
    attributes: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


def _row(r: Any) -> EntityRow:
    return EntityRow(
        id=r.id,
        user_id=r.user_id,
        kind=r.kind,
        name=r.name,
        slug=r.slug,
        description=r.description,
        attributes=r.attributes,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


class EntitiesRepository:
    async def list_entities(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: EntityKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EntityRow]:
        conditions: list[Any] = [entities_table.c.user_id == user_id]
        if kind is not None:
            conditions.append(entities_table.c.kind == kind)
        stmt = (
            sa.select(
                entities_table.c.id,
                entities_table.c.user_id,
                entities_table.c.kind,
                entities_table.c.name,
                entities_table.c.slug,
                entities_table.c.description,
                entities_table.c.attributes,
                entities_table.c.created_at,
                entities_table.c.updated_at,
            )
            .where(sa.and_(*conditions))
            .order_by(entities_table.c.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).all()
        return [_row(r) for r in rows]

    async def get_by_id(
        self, session: AsyncSession, *, user_id: UUID, entity_id: UUID
    ) -> EntityRow | None:
        stmt = sa.select(
            entities_table.c.id,
            entities_table.c.user_id,
            entities_table.c.kind,
            entities_table.c.name,
            entities_table.c.slug,
            entities_table.c.description,
            entities_table.c.attributes,
            entities_table.c.created_at,
            entities_table.c.updated_at,
        ).where(
            sa.and_(
                entities_table.c.id == entity_id,
                entities_table.c.user_id == user_id,
            )
        )
        r = (await session.execute(stmt)).first()
        return _row(r) if r else None

    async def get_by_slug(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: EntityKind,
        slug: str,
    ) -> EntityRow | None:
        stmt = sa.select(
            entities_table.c.id,
            entities_table.c.user_id,
            entities_table.c.kind,
            entities_table.c.name,
            entities_table.c.slug,
            entities_table.c.description,
            entities_table.c.attributes,
            entities_table.c.created_at,
            entities_table.c.updated_at,
        ).where(
            sa.and_(
                entities_table.c.user_id == user_id,
                entities_table.c.kind == kind,
                entities_table.c.slug == slug,
            )
        )
        r = (await session.execute(stmt)).first()
        return _row(r) if r else None

    async def insert(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: EntityKind,
        name: str,
        slug: str,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> UUID:
        entity_id = uuid7_uuid()
        stmt = (
            sa.insert(entities_table)
            .values(
                id=entity_id,
                user_id=user_id,
                kind=kind,
                name=name,
                slug=slug,
                description=description,
                attributes=attributes,
            )
            .returning(entities_table.c.id)
        )
        res = await session.execute(stmt)
        await session.flush()
        return res.scalar_one()

    async def update(
        self,
        session: AsyncSession,
        *,
        entity_id: UUID,
        user_id: UUID,
        name: str | None = None,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> int:
        values: dict[str, Any] = {"updated_at": sa.func.now()}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if attributes is not None:
            values["attributes"] = attributes
        stmt = (
            sa.update(entities_table)
            .where(
                sa.and_(
                    entities_table.c.id == entity_id,
                    entities_table.c.user_id == user_id,
                )
            )
            .values(**values)
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    async def delete(
        self, session: AsyncSession, *, entity_id: UUID, user_id: UUID
    ) -> int:
        stmt = sa.delete(entities_table).where(
            sa.and_(
                entities_table.c.id == entity_id,
                entities_table.c.user_id == user_id,
            )
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    async def insert_link(
        self,
        session: AsyncSession,
        *,
        memory_item_id: UUID,
        entity_id: UUID,
        relation: str = "",
        weight: float | None = None,
    ) -> None:
        # Idempotent upsert: ON CONFLICT DO NOTHING so re-linking is safe.
        from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore[import-not-found]

        stmt = (
            pg_insert(memory_entity_links_table)
            .values(
                memory_item_id=memory_item_id,
                entity_id=entity_id,
                relation=relation,
                weight=weight,
            )
            .on_conflict_do_nothing(
                index_elements=["memory_item_id", "entity_id", "relation"]
            )
        )
        await session.execute(stmt)
        await session.flush()

    async def list_memories_for_entity(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        entity_id: UUID,
        limit: int = 100,
    ) -> list[UUID]:
        # Verify the entity belongs to the user before disclosing links.
        owned = await self.get_by_id(
            session, user_id=user_id, entity_id=entity_id
        )
        if owned is None:
            return []
        stmt = (
            sa.select(memory_entity_links_table.c.memory_item_id)
            .where(memory_entity_links_table.c.entity_id == entity_id)
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        return [r.memory_item_id for r in rows]

    async def repoint_links(
        self,
        session: AsyncSession,
        *,
        from_entity_id: UUID,
        to_entity_id: UUID,
    ) -> int:
        # Move all links from `from` to `to`. Conflicts (the same memory linked to
        # both) are dropped via ON CONFLICT DO NOTHING in two passes.
        from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore[import-not-found]

        select_stmt = sa.select(
            memory_entity_links_table.c.memory_item_id,
            sa.literal(to_entity_id).label("entity_id"),
            memory_entity_links_table.c.relation,
            memory_entity_links_table.c.weight,
        ).where(memory_entity_links_table.c.entity_id == from_entity_id)
        # Insert the copies (idempotently).
        ins_stmt = (
            pg_insert(memory_entity_links_table)
            .from_select(
                ["memory_item_id", "entity_id", "relation", "weight"], select_stmt
            )
            .on_conflict_do_nothing(
                index_elements=["memory_item_id", "entity_id", "relation"]
            )
        )
        await session.execute(ins_stmt)
        # Delete the originals.
        del_stmt = sa.delete(memory_entity_links_table).where(
            memory_entity_links_table.c.entity_id == from_entity_id
        )
        res = await session.execute(del_stmt)
        await session.flush()
        return int(res.rowcount or 0)
