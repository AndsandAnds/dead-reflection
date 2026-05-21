"""MCP tools for the artifact catalog + extraction (Phases 8a + 8b)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from reflections.artifacts.exceptions import (
    ArtifactsNotConfiguredException,
    ArtifactsNotFoundException,
    ArtifactsServiceException,
    ArtifactsUnprocessableException,
    VolumeOfflineException,
)
from reflections.artifacts.extraction_service import ArtifactExtractionService
from reflections.artifacts.service import ArtifactsService
from reflections.core.db import database_manager
from reflections.mcp.auth import current_user_id

_artifacts_service: ArtifactsService | None = None
_extraction_service: ArtifactExtractionService | None = None


def _artifacts() -> ArtifactsService:
    global _artifacts_service
    if _artifacts_service is None:
        _artifacts_service = ArtifactsService.default()
    return _artifacts_service


def _extraction() -> ArtifactExtractionService:
    global _extraction_service
    if _extraction_service is None:
        _extraction_service = ArtifactExtractionService.default()
    return _extraction_service


def _err(exc: Exception) -> dict:
    if isinstance(exc, ArtifactsNotConfiguredException):
        return {"error": "catalog_bridge_not_configured", "hint": exc.details}
    if isinstance(exc, VolumeOfflineException):
        return {"error": "volume_offline", "hint": exc.details}
    if isinstance(exc, ArtifactsNotFoundException):
        return {"error": "not_found", "hint": exc.details}
    if isinstance(exc, ArtifactsUnprocessableException):
        return {"error": "unprocessable", "hint": exc.details}
    if isinstance(exc, ArtifactsServiceException):
        return {"error": "service_error", "hint": exc.details}
    return {"error": type(exc).__name__, "hint": str(exc)[:300]}


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    @mcp.tool
    async def register_volume(
        mount_path: Annotated[str, Field(min_length=1)],
        label: str | None = None,
    ) -> dict:
        """
        Register a filesystem root as a Reflections volume.

        Reads (or creates) `.reflections-volume.json` at the path's root
        so the volume survives remounts. Returns the volume id, label,
        and current mount path. Idempotent — running again on the same
        drive returns the existing row and refreshes mount_hints.
        """
        uid = current_user_id()
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                row = await _artifacts().register_volume(
                    session, user_id=uid, mount_path=mount_path, label=label
                )
        except Exception as exc:
            return _err(exc)
        return {
            "id": str(row.id),
            "label": row.label,
            "volume_uuid": row.volume_uuid,
            "fingerprint": row.fingerprint,
            "mount_path": mount_path,
        }

    @mcp.tool
    async def list_volumes() -> dict:
        """List all volumes registered by this user, with current mount path
        (or null if the bridge can't see them right now)."""
        uid = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            pairs = await _artifacts().list_volumes(session, user_id=uid)
        return {
            "items": [
                {
                    "id": str(r.id),
                    "label": r.label,
                    "volume_uuid": r.volume_uuid,
                    "fingerprint": r.fingerprint,
                    "mount_path": mp,
                    "online": bool(mp),
                    "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                }
                for (r, mp) in pairs
            ]
        }

    @mcp.tool
    async def catalog_volume(
        volume_id: str,
        subpath: str = "",
        max_entries_per_page: Annotated[
            int, Field(ge=1, le=20000)
        ] = 5000,
    ) -> dict:
        """
        Walk a volume, cataloging files (stat-only). Cheap; safe to re-run.
        Idempotent: unchanged files are skipped, real changes update the
        row and mark previously-extracted artifacts `stale` for re-extract.
        """
        uid = current_user_id()
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                result = await _artifacts().catalog_volume(
                    session,
                    user_id=uid,
                    volume_id=UUID(volume_id),
                    subpath=subpath,
                    max_entries_per_page=max_entries_per_page,
                )
        except Exception as exc:
            return _err(exc)
        result["volume_id"] = str(result["volume_id"])
        result["started_at"] = result["started_at"].isoformat()
        result["finished_at"] = result["finished_at"].isoformat()
        return result

    @mcp.tool
    async def list_artifacts(
        volume_id: str | None = None,
        kind: Literal["pdf", "image", "audio", "video", "other"] | None = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
        offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
    ) -> dict:
        """List catalog rows. Filter by volume_id and/or kind."""
        uid = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            rows = await _artifacts().list_artifacts(
                session,
                user_id=uid,
                volume_id=UUID(volume_id) if volume_id else None,
                kind=kind,
                limit=limit,
                offset=offset,
            )
        return {
            "items": [
                {
                    "id": str(r.id),
                    "volume_id": str(r.volume_id),
                    "relative_path": r.relative_path,
                    "kind": r.kind,
                    "mime": r.mime,
                    "size_bytes": r.size_bytes,
                    "catalog_state": r.catalog_state,
                    "private": r.private,
                    "mtime": r.mtime.isoformat(),
                }
                for r in rows
            ]
        }

    @mcp.tool
    async def set_extraction_policy(
        volume_id: str,
        rules: list[dict],
    ) -> dict:
        """
        Replace the extraction policy set for a volume.

        Each rule is a dict with optional `glob_pattern` (e.g.
        "Photos/2024/*.jpg"), `mime_prefix` (e.g. "image/"), `kind`
        (one of pdf|image|audio|video|other), and a REQUIRED `action`
        of `extract` (public), `extract_private`, or `ignore`.

        Rules are evaluated in array order; **first match wins**. Files
        matching no rule default to `ignore`.
        """
        uid = current_user_id()
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                rows = await _artifacts().repo.replace_policies(
                    session,
                    user_id=uid,
                    volume_id=UUID(volume_id),
                    rules=rules,
                )
                await session.commit()
        except Exception as exc:
            return _err(exc)
        return {
            "items": [
                {
                    "id": str(p.id),
                    "position": p.position,
                    "glob_pattern": p.glob_pattern,
                    "mime_prefix": p.mime_prefix,
                    "kind": p.kind,
                    "action": p.action,
                }
                for p in rows
            ]
        }

    @mcp.tool
    async def apply_extraction_policies(
        volume_id: str,
        limit: Annotated[int, Field(ge=1, le=5000)] = 500,
    ) -> dict:
        """
        Iterate every catalogued/stale artifact in the volume, match it
        against the policy set, and run the right extractor (or skip).
        Sync — for big media this can take a while. Returns counts.
        """
        uid = current_user_id()
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                result = await _extraction().extract_by_policy(
                    session,
                    user_id=uid,
                    volume_id=UUID(volume_id),
                    limit=limit,
                )
        except Exception as exc:
            return _err(exc)
        return {
            "volume_id": str(result.volume_id),
            "considered": result.considered,
            "extracted": result.extracted,
            "extracted_private": result.extracted_private,
            "ignored": result.ignored,
            "failed": result.failed,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
        }

    @mcp.tool
    async def extract_artifact(
        artifact_id: str,
        private: bool | None = None,
    ) -> dict:
        """
        Force-extract a single artifact now, regardless of policy. If
        `private` is true, derived memory chunks are flagged private
        (only callers with the `mcp:read_private` scope will see them
        via `recall_memory` / `inspect_memories`).
        """
        uid = current_user_id()
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                result = await _extraction().extract_one(
                    session,
                    user_id=uid,
                    artifact_id=UUID(artifact_id),
                    private=private,
                )
        except Exception as exc:
            return _err(exc)
        return {
            "artifact_id": str(result.artifact_id),
            "chunks_written": result.chunks_written,
            "action": result.action,
            "error": result.error,
        }

    @mcp.tool
    async def delete_artifact(artifact_id: str) -> dict:
        """Delete an artifact row (NOT the file on disk). Cascade-deletes
        any derived memory chunks pointing to it."""
        uid = current_user_id()
        await database_manager.initialize()
        try:
            async with database_manager.session() as session:
                await _artifacts().delete_artifact(
                    session, user_id=uid, artifact_id=UUID(artifact_id)
                )
        except Exception as exc:
            return _err(exc)
        return {"deleted": True}
