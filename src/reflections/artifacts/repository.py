from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid

metadata = sa.MetaData()


volumes_table = sa.Table(
    "volumes",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("label", sa.Text(), nullable=False),
    sa.Column("volume_uuid", sa.Text(), nullable=True),
    sa.Column("fingerprint", sa.Text(), nullable=True),
    sa.Column("mount_hints", sa.JSON(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
)


artifacts_table = sa.Table(
    "artifacts",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("volume_id", sa.Uuid(), nullable=False),
    sa.Column("relative_path", sa.Text(), nullable=False),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("mime", sa.Text(), nullable=True),
    sa.Column("size_bytes", sa.BigInteger(), nullable=False),
    sa.Column("mtime", sa.DateTime(timezone=True), nullable=False),
    sa.Column("sha256", sa.Text(), nullable=True),
    sa.Column("attributes", sa.JSON(), nullable=True),
    sa.Column("catalog_state", sa.Text(), nullable=False),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
    # 8e privacy flag; chunks inherit at extraction time.
    sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.false()),
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


extraction_policies_table = sa.Table(
    "artifact_extraction_policies",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("user_id", sa.Uuid(), nullable=False),
    sa.Column("volume_id", sa.Uuid(), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("glob_pattern", sa.Text(), nullable=True),
    sa.Column("mime_prefix", sa.Text(), nullable=True),
    sa.Column("kind", sa.Text(), nullable=True),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
)


@dataclass(frozen=True)
class VolumeRow:
    id: UUID
    user_id: UUID
    label: str
    volume_uuid: str | None
    fingerprint: str | None
    mount_hints: list[dict[str, Any]] | None
    created_at: dt.datetime
    last_seen_at: dt.datetime | None


def _vol_row(r: Any) -> VolumeRow:
    return VolumeRow(
        id=r.id,
        user_id=r.user_id,
        label=r.label,
        volume_uuid=r.volume_uuid,
        fingerprint=r.fingerprint,
        mount_hints=r.mount_hints,
        created_at=r.created_at,
        last_seen_at=r.last_seen_at,
    )


@dataclass(frozen=True)
class ArtifactRow:
    id: UUID
    user_id: UUID
    volume_id: UUID
    relative_path: str
    kind: str
    mime: str | None
    size_bytes: int
    mtime: dt.datetime
    sha256: str | None
    attributes: dict[str, Any] | None
    catalog_state: str
    error: str | None
    extracted_at: dt.datetime | None
    private: bool
    created_at: dt.datetime
    updated_at: dt.datetime


def _art_row(r: Any) -> ArtifactRow:
    return ArtifactRow(
        id=r.id,
        user_id=r.user_id,
        volume_id=r.volume_id,
        relative_path=r.relative_path,
        kind=r.kind,
        mime=r.mime,
        size_bytes=r.size_bytes,
        mtime=r.mtime,
        sha256=r.sha256,
        attributes=r.attributes,
        catalog_state=r.catalog_state,
        error=r.error,
        extracted_at=r.extracted_at,
        private=bool(r.private),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


@dataclass(frozen=True)
class PolicyRow:
    id: UUID
    user_id: UUID
    volume_id: UUID
    position: int
    glob_pattern: str | None
    mime_prefix: str | None
    kind: str | None
    action: str
    created_at: dt.datetime


def _policy_row(r: Any) -> PolicyRow:
    return PolicyRow(
        id=r.id,
        user_id=r.user_id,
        volume_id=r.volume_id,
        position=r.position,
        glob_pattern=r.glob_pattern,
        mime_prefix=r.mime_prefix,
        kind=r.kind,
        action=r.action,
        created_at=r.created_at,
    )


@dataclass(frozen=True)
class UpsertOutcome:
    inserted: int
    updated: int
    unchanged: int


@dataclass(frozen=True)
class ArtifactsRepository:
    # --- volumes ----------------------------------------------------------

    async def find_volume(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_uuid: str | None,
        fingerprint: str | None,
    ) -> VolumeRow | None:
        """Locate a volume by either identifier. We prefer fingerprint
        (it's user-controlled and survives reformats) and fall back to
        the OS volume UUID."""
        clauses: list[Any] = []
        if fingerprint:
            clauses.append(volumes_table.c.fingerprint == fingerprint)
        if volume_uuid:
            clauses.append(volumes_table.c.volume_uuid == volume_uuid)
        if not clauses:
            return None
        stmt = (
            sa.select(
                volumes_table.c.id,
                volumes_table.c.user_id,
                volumes_table.c.label,
                volumes_table.c.volume_uuid,
                volumes_table.c.fingerprint,
                volumes_table.c.mount_hints,
                volumes_table.c.created_at,
                volumes_table.c.last_seen_at,
            )
            .where(volumes_table.c.user_id == user_id)
            .where(sa.or_(*clauses))
            .limit(1)
        )
        r = (await session.execute(stmt)).first()
        return _vol_row(r) if r else None

    async def insert_volume(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        label: str,
        volume_uuid: str | None,
        fingerprint: str | None,
        mount_hints: list[dict[str, Any]] | None = None,
    ) -> VolumeRow:
        new_id = uuid7_uuid()
        stmt = (
            sa.insert(volumes_table)
            .values(
                id=new_id,
                user_id=user_id,
                label=label,
                volume_uuid=volume_uuid,
                fingerprint=fingerprint,
                mount_hints=mount_hints,
                last_seen_at=sa.func.now(),
            )
            .returning(
                volumes_table.c.id,
                volumes_table.c.user_id,
                volumes_table.c.label,
                volumes_table.c.volume_uuid,
                volumes_table.c.fingerprint,
                volumes_table.c.mount_hints,
                volumes_table.c.created_at,
                volumes_table.c.last_seen_at,
            )
        )
        r = (await session.execute(stmt)).first()
        await session.flush()
        return _vol_row(r)

    async def touch_volume(
        self,
        session: AsyncSession,
        *,
        volume_id: UUID,
        mount_path: str | None,
    ) -> None:
        """Update last_seen_at and merge mount_path into mount_hints."""
        # Read current hints to merge.
        cur = await self.get_volume(session, volume_id=volume_id)
        if cur is None:
            return
        hints = list(cur.mount_hints or [])
        if mount_path and not any(
            h.get("path") == mount_path for h in hints if isinstance(h, dict)
        ):
            hints.append({"path": mount_path})
        stmt = (
            sa.update(volumes_table)
            .where(volumes_table.c.id == volume_id)
            .values(last_seen_at=sa.func.now(), mount_hints=hints)
        )
        await session.execute(stmt)
        await session.flush()

    async def list_volumes(
        self, session: AsyncSession, *, user_id: UUID
    ) -> list[VolumeRow]:
        stmt = (
            sa.select(
                volumes_table.c.id,
                volumes_table.c.user_id,
                volumes_table.c.label,
                volumes_table.c.volume_uuid,
                volumes_table.c.fingerprint,
                volumes_table.c.mount_hints,
                volumes_table.c.created_at,
                volumes_table.c.last_seen_at,
            )
            .where(volumes_table.c.user_id == user_id)
            .order_by(volumes_table.c.created_at.desc())
        )
        rows = (await session.execute(stmt)).all()
        return [_vol_row(r) for r in rows]

    async def get_volume(
        self, session: AsyncSession, *, volume_id: UUID
    ) -> VolumeRow | None:
        stmt = sa.select(
            volumes_table.c.id,
            volumes_table.c.user_id,
            volumes_table.c.label,
            volumes_table.c.volume_uuid,
            volumes_table.c.fingerprint,
            volumes_table.c.mount_hints,
            volumes_table.c.created_at,
            volumes_table.c.last_seen_at,
        ).where(volumes_table.c.id == volume_id)
        r = (await session.execute(stmt)).first()
        return _vol_row(r) if r else None

    async def delete_volume(
        self, session: AsyncSession, *, user_id: UUID, volume_id: UUID
    ) -> int:
        # Cascades to artifacts via FK ON DELETE CASCADE.
        stmt = sa.delete(volumes_table).where(
            sa.and_(
                volumes_table.c.id == volume_id,
                volumes_table.c.user_id == user_id,
            )
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    # --- artifacts: upsert from a walk page -------------------------------

    async def upsert_files(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
        files: list[dict[str, Any]],
    ) -> UpsertOutcome:
        """Upsert one walk page worth of file entries.

        Each entry: {relative_path, size_bytes, mtime, mime, kind}.
        We mark `stale` when (size, mtime) changed on a previously
        extracted artifact, so the extraction worker can re-run.
        """
        if not files:
            return UpsertOutcome(inserted=0, updated=0, unchanged=0)
        # Look up existing rows in one shot.
        rel_paths = [f["relative_path"] for f in files]
        existing_stmt = sa.select(
            artifacts_table.c.id,
            artifacts_table.c.relative_path,
            artifacts_table.c.size_bytes,
            artifacts_table.c.mtime,
            artifacts_table.c.catalog_state,
        ).where(
            sa.and_(
                artifacts_table.c.volume_id == volume_id,
                artifacts_table.c.relative_path.in_(rel_paths),
            )
        )
        existing: dict[str, Any] = {
            r.relative_path: r
            for r in (await session.execute(existing_stmt)).all()
        }

        inserted = 0
        updated = 0
        unchanged = 0
        now = sa.func.now()

        for f in files:
            ex = existing.get(f["relative_path"])
            if ex is None:
                ins = pg_insert(artifacts_table).values(
                    id=uuid7_uuid(),
                    user_id=user_id,
                    volume_id=volume_id,
                    relative_path=f["relative_path"],
                    kind=f["kind"],
                    mime=f.get("mime"),
                    size_bytes=f["size_bytes"],
                    mtime=f["mtime"],
                    catalog_state="catalogued",
                ).on_conflict_do_nothing(
                    index_elements=["volume_id", "relative_path"]
                )
                await session.execute(ins)
                inserted += 1
                continue
            # Compare stat for change detection.
            if (
                ex.size_bytes == f["size_bytes"]
                and ex.mtime == f["mtime"]
            ):
                unchanged += 1
                continue
            # Changed. If we'd previously extracted, mark stale so the
            # extractor knows to re-run; otherwise it's just a refresh.
            next_state = (
                "stale"
                if ex.catalog_state == "extracted"
                else "catalogued"
            )
            upd = (
                sa.update(artifacts_table)
                .where(artifacts_table.c.id == ex.id)
                .values(
                    size_bytes=f["size_bytes"],
                    mtime=f["mtime"],
                    mime=f.get("mime"),
                    kind=f["kind"],
                    catalog_state=next_state,
                    updated_at=now,
                    # sha256 is invalidated on a real change; null it
                    # so the next extract recomputes.
                    sha256=None,
                )
            )
            await session.execute(upd)
            updated += 1

        await session.flush()
        return UpsertOutcome(
            inserted=inserted, updated=updated, unchanged=unchanged
        )

    # --- artifacts: read --------------------------------------------------

    async def list_artifacts(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ArtifactRow]:
        conds: list[Any] = [artifacts_table.c.user_id == user_id]
        if volume_id is not None:
            conds.append(artifacts_table.c.volume_id == volume_id)
        if kind is not None:
            conds.append(artifacts_table.c.kind == kind)
        stmt = (
            sa.select(
                artifacts_table.c.id,
                artifacts_table.c.user_id,
                artifacts_table.c.volume_id,
                artifacts_table.c.relative_path,
                artifacts_table.c.kind,
                artifacts_table.c.mime,
                artifacts_table.c.size_bytes,
                artifacts_table.c.mtime,
                artifacts_table.c.sha256,
                artifacts_table.c.attributes,
                artifacts_table.c.catalog_state,
                artifacts_table.c.error,
                artifacts_table.c.extracted_at,
                artifacts_table.c.created_at,
                artifacts_table.c.updated_at,
            )
            .where(sa.and_(*conds))
            .order_by(artifacts_table.c.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(stmt)).all()
        return [_art_row(r) for r in rows]

    async def get_artifact(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRow | None:
        stmt = sa.select(
            artifacts_table.c.id,
            artifacts_table.c.user_id,
            artifacts_table.c.volume_id,
            artifacts_table.c.relative_path,
            artifacts_table.c.kind,
            artifacts_table.c.mime,
            artifacts_table.c.size_bytes,
            artifacts_table.c.mtime,
            artifacts_table.c.sha256,
            artifacts_table.c.attributes,
            artifacts_table.c.catalog_state,
            artifacts_table.c.error,
            artifacts_table.c.extracted_at,
            artifacts_table.c.private,
            artifacts_table.c.created_at,
            artifacts_table.c.updated_at,
        ).where(
            sa.and_(
                artifacts_table.c.id == artifact_id,
                artifacts_table.c.user_id == user_id,
            )
        )
        r = (await session.execute(stmt)).first()
        return _art_row(r) if r else None

    async def delete_artifact(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        artifact_id: UUID,
    ) -> int:
        stmt = sa.delete(artifacts_table).where(
            sa.and_(
                artifacts_table.c.id == artifact_id,
                artifacts_table.c.user_id == user_id,
            )
        )
        res = await session.execute(stmt)
        await session.flush()
        return int(res.rowcount or 0)

    # --- artifacts: extraction lifecycle ----------------------------------

    async def mark_extracting(
        self,
        session: AsyncSession,
        *,
        artifact_id: UUID,
        user_id: UUID,
    ) -> None:
        stmt = (
            sa.update(artifacts_table)
            .where(
                sa.and_(
                    artifacts_table.c.id == artifact_id,
                    artifacts_table.c.user_id == user_id,
                )
            )
            .values(
                catalog_state="extracting",
                error=None,
                updated_at=sa.func.now(),
            )
        )
        await session.execute(stmt)
        await session.flush()

    async def mark_extracted(
        self,
        session: AsyncSession,
        *,
        artifact_id: UUID,
        user_id: UUID,
        attributes_patch: dict[str, Any] | None = None,
        sha256: str | None = None,
        private: bool | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "catalog_state": "extracted",
            "extracted_at": sa.func.now(),
            "updated_at": sa.func.now(),
            "error": None,
        }
        if sha256 is not None:
            values["sha256"] = sha256
        if private is not None:
            values["private"] = private
        if attributes_patch is not None:
            # We don't have JSONB merge in SQLAlchemy core in a portable
            # way; read-modify-write is fine for this low-frequency op.
            existing = await self.get_artifact(
                session, user_id=user_id, artifact_id=artifact_id
            )
            merged = dict(existing.attributes or {}) if existing else {}
            merged.update(attributes_patch)
            values["attributes"] = merged
        stmt = (
            sa.update(artifacts_table)
            .where(
                sa.and_(
                    artifacts_table.c.id == artifact_id,
                    artifacts_table.c.user_id == user_id,
                )
            )
            .values(**values)
        )
        await session.execute(stmt)
        await session.flush()

    async def mark_extraction_failed(
        self,
        session: AsyncSession,
        *,
        artifact_id: UUID,
        user_id: UUID,
        error: str,
    ) -> None:
        stmt = (
            sa.update(artifacts_table)
            .where(
                sa.and_(
                    artifacts_table.c.id == artifact_id,
                    artifacts_table.c.user_id == user_id,
                )
            )
            .values(
                catalog_state="failed",
                error=error[:500],
                updated_at=sa.func.now(),
            )
        )
        await session.execute(stmt)
        await session.flush()

    async def list_artifacts_ready_for_extraction(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
        limit: int = 1000,
    ) -> list[ArtifactRow]:
        """Anything that's catalogued or stale — extracted/failed/extracting
        are skipped."""
        stmt = (
            sa.select(
                artifacts_table.c.id,
                artifacts_table.c.user_id,
                artifacts_table.c.volume_id,
                artifacts_table.c.relative_path,
                artifacts_table.c.kind,
                artifacts_table.c.mime,
                artifacts_table.c.size_bytes,
                artifacts_table.c.mtime,
                artifacts_table.c.sha256,
                artifacts_table.c.attributes,
                artifacts_table.c.catalog_state,
                artifacts_table.c.error,
                artifacts_table.c.extracted_at,
                artifacts_table.c.private,
                artifacts_table.c.created_at,
                artifacts_table.c.updated_at,
            )
            .where(
                sa.and_(
                    artifacts_table.c.user_id == user_id,
                    artifacts_table.c.volume_id == volume_id,
                    artifacts_table.c.catalog_state.in_(["catalogued", "stale"]),
                )
            )
            .order_by(artifacts_table.c.created_at.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        return [_art_row(r) for r in rows]

    # --- extraction policies ----------------------------------------------

    async def list_policies(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
    ) -> list[PolicyRow]:
        stmt = (
            sa.select(
                extraction_policies_table.c.id,
                extraction_policies_table.c.user_id,
                extraction_policies_table.c.volume_id,
                extraction_policies_table.c.position,
                extraction_policies_table.c.glob_pattern,
                extraction_policies_table.c.mime_prefix,
                extraction_policies_table.c.kind,
                extraction_policies_table.c.action,
                extraction_policies_table.c.created_at,
            )
            .where(
                sa.and_(
                    extraction_policies_table.c.user_id == user_id,
                    extraction_policies_table.c.volume_id == volume_id,
                )
            )
            .order_by(extraction_policies_table.c.position.asc())
        )
        rows = (await session.execute(stmt)).all()
        return [_policy_row(r) for r in rows]

    async def replace_policies(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
        rules: list[dict[str, Any]],
    ) -> list[PolicyRow]:
        """Atomic replace: drop all rows for this volume, insert the new
        set. Position is assigned from list order if not supplied."""
        del_stmt = sa.delete(extraction_policies_table).where(
            sa.and_(
                extraction_policies_table.c.user_id == user_id,
                extraction_policies_table.c.volume_id == volume_id,
            )
        )
        await session.execute(del_stmt)
        for idx, rule in enumerate(rules):
            ins = sa.insert(extraction_policies_table).values(
                id=uuid7_uuid(),
                user_id=user_id,
                volume_id=volume_id,
                position=int(rule.get("position", idx)),
                glob_pattern=rule.get("glob_pattern"),
                mime_prefix=rule.get("mime_prefix"),
                kind=rule.get("kind"),
                action=rule["action"],
            )
            await session.execute(ins)
        await session.flush()
        return await self.list_policies(
            session, user_id=user_id, volume_id=volume_id
        )
