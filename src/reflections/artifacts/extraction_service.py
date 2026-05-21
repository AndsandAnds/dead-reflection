"""
Extraction orchestrator.

For a given artifact:
  1. Resolve the volume's mount path
  2. Create a `read_bytes` closure that pulls the file via the catalog bridge
  3. Dispatch to the kind-specific extractor (pdf/image/audio/video)
  4. For each ExtractedChunk, embed the text and insert a `memory_items`
     row stamped with (artifact_id, artifact_locator, private)
  5. Update the artifact's catalog_state (`extracted` / `failed`) and
     optionally merge attributes (EXIF, page counts, ...)

The entity-extraction pass runs over the new chunks for free — same path
as the existing voice/chat ingest — so a PDF mentioning Sarah and
Brooklyn auto-populates those entities and links them to the artifact's
chunks (and thereby the artifact, via memory_entity_links → memory ↔
artifact graph edges).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.artifacts.exceptions import (
    ArtifactsNotFoundException,
    ArtifactsServiceException,
    ArtifactsUnprocessableException,
)
from reflections.artifacts.policies import Policy, PolicyAction, match
from reflections.artifacts.repository import (
    ArtifactRow,
    ArtifactsRepository,
    PolicyRow,
)
from reflections.commons.logging import logger
from reflections.core.settings import settings
from reflections.extractors.base import (
    ArtifactMeta,
    ExtractedChunk,
    ExtractionError,
    UnsupportedArtifactError,
)
from reflections.extractors.dispatcher import dispatch as dispatch_extract
from reflections.memory.service import MemoryService


@dataclass
class ExtractionResult:
    artifact_id: UUID
    chunks_written: int
    action: str  # "extracted" | "extracted_private" | "ignored" | "failed"
    error: str | None = None


@dataclass
class BulkExtractionResult:
    volume_id: UUID
    considered: int
    extracted: int
    extracted_private: int
    ignored: int
    failed: int
    started_at: dt.datetime
    finished_at: dt.datetime


@dataclass
class ArtifactExtractionService:
    repo: ArtifactsRepository
    memory: MemoryService

    @classmethod
    def default(cls) -> "ArtifactExtractionService":
        return cls(repo=ArtifactsRepository(), memory=MemoryService.create())

    # --- Single artifact -------------------------------------------------

    async def extract_one(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        artifact_id: UUID,
        private: bool | None = None,
    ) -> ExtractionResult:
        """Extract a single artifact synchronously.

        `private=None` keeps the artifact's existing private flag; pass
        True/False to override (e.g. when applying a policy that says
        `extract_private`).
        """
        artifact = await self.repo.get_artifact(
            session, user_id=user_id, artifact_id=artifact_id
        )
        if artifact is None:
            raise ArtifactsNotFoundException(
                "artifact_not_found", str(artifact_id)
            )

        mount_path = await self._resolve_mount_path(
            session, artifact=artifact
        )
        if mount_path is None:
            raise ArtifactsUnprocessableException(
                "volume_offline",
                "Volume has no known mount path; re-register it while mounted.",
            )

        effective_private = artifact.private if private is None else private
        await self.repo.mark_extracting(
            session, artifact_id=artifact.id, user_id=user_id
        )
        await session.commit()

        meta = ArtifactMeta(
            id=artifact.id,
            user_id=user_id,
            mount_path=mount_path,
            relative_path=artifact.relative_path,
            mime=artifact.mime,
            size_bytes=artifact.size_bytes,
            kind=artifact.kind,
        )

        async def _read_bytes() -> bytes:
            return await self._read_via_bridge(meta)

        try:
            chunks = await dispatch_extract(meta=meta, read_bytes=_read_bytes)
        except UnsupportedArtifactError as exc:
            await self.repo.mark_extraction_failed(
                session,
                artifact_id=artifact.id,
                user_id=user_id,
                error=str(exc),
            )
            await session.commit()
            return ExtractionResult(
                artifact_id=artifact.id,
                chunks_written=0,
                action="failed",
                error=str(exc),
            )
        except ExtractionError as exc:
            await self.repo.mark_extraction_failed(
                session,
                artifact_id=artifact.id,
                user_id=user_id,
                error=str(exc),
            )
            await session.commit()
            return ExtractionResult(
                artifact_id=artifact.id,
                chunks_written=0,
                action="failed",
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception(
                "extractor_crashed artifact_id=%s", artifact.id
            )
            await self.repo.mark_extraction_failed(
                session,
                artifact_id=artifact.id,
                user_id=user_id,
                error=f"crash: {type(exc).__name__}",
            )
            await session.commit()
            return ExtractionResult(
                artifact_id=artifact.id,
                chunks_written=0,
                action="failed",
                error=str(exc),
            )

        written = await self._persist_chunks(
            session,
            user_id=user_id,
            artifact=artifact,
            chunks=chunks,
            private=effective_private,
        )

        # Merge any attribute hints from the first chunk's metadata into
        # the artifact attributes (EXIF for images, page counts for PDFs).
        attributes_patch = self._collect_attributes(chunks)
        await self.repo.mark_extracted(
            session,
            artifact_id=artifact.id,
            user_id=user_id,
            attributes_patch=attributes_patch,
            private=effective_private,
        )
        await session.commit()

        # Best-effort: entity extraction over the new chunks so the graph
        # reflects what was in the file. Never let this fail the extract.
        await self._run_entity_extraction(
            session,
            user_id=user_id,
            chunks=chunks,
            written_ids=written,
        )

        return ExtractionResult(
            artifact_id=artifact.id,
            chunks_written=len(written),
            action="extracted_private" if effective_private else "extracted",
        )

    # --- Bulk by policy --------------------------------------------------

    async def extract_by_policy(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
        limit: int = 1000,
    ) -> BulkExtractionResult:
        """Apply each volume's extraction policies to every artifact in
        `catalogued`/`stale` state, in turn. Sync; will get slow on big
        media — async worker is a v2 follow-up."""
        started = dt.datetime.now(dt.UTC)
        policies_rows = await self.repo.list_policies(
            session, user_id=user_id, volume_id=volume_id
        )
        policies = [_to_policy(p) for p in policies_rows]
        candidates = await self.repo.list_artifacts_ready_for_extraction(
            session, user_id=user_id, volume_id=volume_id, limit=limit
        )

        extracted = 0
        extracted_private = 0
        ignored = 0
        failed = 0
        for art in candidates:
            mr = match(
                policies,
                relative_path=art.relative_path,
                mime=art.mime,
                kind=art.kind,
            )
            if mr.action == "ignore":
                ignored += 1
                continue
            private = mr.action == "extract_private"
            try:
                result = await self.extract_one(
                    session,
                    user_id=user_id,
                    artifact_id=art.id,
                    private=private,
                )
            except Exception as exc:
                logger.warning(
                    "extract_by_policy_crash artifact_id=%s err=%s",
                    art.id,
                    exc,
                )
                failed += 1
                continue
            if result.action == "failed":
                failed += 1
            elif result.action == "extracted_private":
                extracted_private += 1
            elif result.action == "extracted":
                extracted += 1

        return BulkExtractionResult(
            volume_id=volume_id,
            considered=len(candidates),
            extracted=extracted,
            extracted_private=extracted_private,
            ignored=ignored,
            failed=failed,
            started_at=started,
            finished_at=dt.datetime.now(dt.UTC),
        )

    # --- Internals -------------------------------------------------------

    async def _resolve_mount_path(
        self, session: AsyncSession, *, artifact: ArtifactRow
    ) -> str | None:
        volume = await self.repo.get_volume(
            session, volume_id=artifact.volume_id
        )
        if volume is None or not volume.mount_hints:
            return None
        for hint in reversed(volume.mount_hints):
            if isinstance(hint, dict) and hint.get("path"):
                return str(hint["path"])
        return None

    async def _read_via_bridge(self, meta: ArtifactMeta) -> bytes:
        if not settings.CATALOG_BRIDGE_URL:
            raise ArtifactsServiceException(
                "catalog_bridge_not_configured",
                "Set CATALOG_BRIDGE_URL to read artifact bytes.",
            )
        base = settings.CATALOG_BRIDGE_URL.rstrip("/")
        headers = {"Accept": "application/octet-stream"}
        if settings.CATALOG_BRIDGE_SECRET:
            headers["X-Catalog-Bridge-Secret"] = settings.CATALOG_BRIDGE_SECRET
        params = {
            "mount_path": meta.mount_path,
            "relative_path": meta.relative_path,
        }
        # Streaming would be nicer for large media; for v1 we buffer
        # because pypdf/Pillow want a bytes blob anyway. Long videos
        # are the pressure point.
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            r = await client.get(
                f"{base}/file", headers=headers, params=params
            )
            r.raise_for_status()
            return r.content

    async def _persist_chunks(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        artifact: ArtifactRow,
        chunks: list[ExtractedChunk],
        private: bool,
    ) -> list[UUID]:
        written: list[UUID] = []
        for c in chunks:
            text = (c.content or "").strip()
            if not text:
                continue
            emb = self.memory.embed_text(text)
            new_id = await self.memory.repository.insert_item(
                session,
                user_id=user_id,
                avatar_id=None,
                scope="user",
                kind="chunk",
                content=text,
                embedding=emb,
                metadata=c.metadata or None,
                artifact_id=artifact.id,
                artifact_locator=c.locator or None,
                private=private,
            )
            written.append(new_id)
        await session.commit()
        return written

    def _collect_attributes(
        self, chunks: list[ExtractedChunk]
    ) -> dict[str, Any] | None:
        """Pull stable per-artifact fields out of chunk metadata."""
        if not chunks:
            return None
        patch: dict[str, Any] = {}
        first = chunks[0].metadata or {}
        # Pull EXIF from image chunks; page-count from any chunk that
        # had it; chunk_count from audio.
        if "exif" in first:
            patch["exif"] = first["exif"]
        for c in chunks:
            loc = c.locator or {}
            if "total_pages" in loc and "total_pages" not in patch:
                patch["page_count"] = loc["total_pages"]
                break
        if not patch:
            return None
        return patch

    async def _run_entity_extraction(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        chunks: list[ExtractedChunk],
        written_ids: list[UUID],
    ) -> None:
        if not chunks or not written_ids:
            return
        if self.memory.entities is None:
            return
        # One entity-extraction call per written chunk so links are
        # accurate (Sarah on page 7 only, not page 1 too).
        for chunk_id, chunk in zip(written_ids, chunks):
            try:
                await self.memory.entities.upsert_and_link(
                    session,
                    user_id=user_id,
                    memory_item_ids=[chunk_id],
                    chunk_text=chunk.content,
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "artifact_entity_extraction_failed chunk_id=%s err=%s",
                    chunk_id,
                    exc,
                )


def _to_policy(row: PolicyRow) -> Policy:
    return Policy(
        glob_pattern=row.glob_pattern,
        mime_prefix=row.mime_prefix,
        kind=row.kind,
        action=row.action,  # type: ignore[arg-type]
    )
