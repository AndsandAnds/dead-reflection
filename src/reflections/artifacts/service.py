from __future__ import annotations

import datetime as dt
import mimetypes
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.artifacts.bridge_client import CatalogBridgeClient
from reflections.artifacts.exceptions import (
    ArtifactsNotFoundException,
    ArtifactsServiceException,
    ArtifactsUnprocessableException,
)
from reflections.artifacts.repository import (
    ArtifactRow,
    ArtifactsRepository,
    UpsertOutcome,
    VolumeRow,
)
from reflections.commons.logging import logger


def _kind_for(mime: str | None, filename: str) -> str:
    if mime:
        if mime == "application/pdf":
            return "pdf"
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
    # Fallback by extension. HEIC etc. may not be in mimetypes' defaults.
    ext = filename.lower().rsplit(".", 1)
    if len(ext) == 2:
        e = ext[1]
        if e in {"heic", "heif", "raw", "cr2", "nef", "arw", "dng"}:
            return "image"
        if e in {"m4a", "opus", "ogg", "flac"}:
            return "audio"
        if e in {"mkv", "webm", "mov", "avi"}:
            return "video"
    return "other"


@dataclass
class ArtifactsService:
    repo: ArtifactsRepository
    bridge: CatalogBridgeClient

    @classmethod
    def default(cls) -> "ArtifactsService":
        return cls(repo=ArtifactsRepository(), bridge=CatalogBridgeClient())

    # --- volumes ----------------------------------------------------------

    async def register_volume(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        mount_path: str,
        label: str | None = None,
    ) -> VolumeRow:
        """Probe the path via the bridge (which reads/creates the marker
        and reads the OS volume UUID), then find-or-insert a row keyed by
        either identifier."""
        identity = await self.bridge.probe(
            mount_path=mount_path, label=label
        )
        fingerprint = identity.get("fingerprint")
        volume_uuid = identity.get("volume_uuid")
        existing = await self.repo.find_volume(
            session,
            user_id=user_id,
            volume_uuid=volume_uuid,
            fingerprint=fingerprint,
        )
        if existing is not None:
            await self.repo.touch_volume(
                session,
                volume_id=existing.id,
                mount_path=identity.get("mount_path"),
            )
            await session.commit()
            return existing
        row = await self.repo.insert_volume(
            session,
            user_id=user_id,
            label=identity.get("label") or label or mount_path.rstrip("/").split("/")[-1],
            volume_uuid=volume_uuid,
            fingerprint=fingerprint,
            mount_hints=[{"path": identity["mount_path"]}],
        )
        await session.commit()
        return row

    async def list_volumes(
        self, session: AsyncSession, *, user_id: UUID
    ) -> list[tuple[VolumeRow, str | None]]:
        """Returns (volume_row, current_mount_path). Caller decides online
        by checking mount_path is non-None and reachable via the bridge."""
        rows = await self.repo.list_volumes(session, user_id=user_id)
        out: list[tuple[VolumeRow, str | None]] = []
        for r in rows:
            mp = None
            if r.mount_hints:
                hints = [h for h in r.mount_hints if isinstance(h, dict)]
                if hints:
                    mp = hints[-1].get("path")  # most recently used hint
            out.append((r, mp))
        return out

    async def delete_volume(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
    ) -> None:
        n = await self.repo.delete_volume(
            session, user_id=user_id, volume_id=volume_id
        )
        if n == 0:
            raise ArtifactsNotFoundException(
                "volume_not_found",
                "No volume with that id for this user",
            )
        await session.commit()

    # --- catalog walk ----------------------------------------------------

    async def catalog_volume(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        volume_id: UUID,
        subpath: str = "",
        max_pages: int = 200,
        max_entries_per_page: int = 5000,
    ) -> dict[str, Any]:
        """Walk a volume in page-sized chunks, upserting artifact rows.

        `max_pages` caps a single call so it can't run forever on a 10TB
        drive; callers iterate by passing `subpath` to resume from a
        known subtree. The bridge handles the actual scandir + stat.
        """
        volume = await self.repo.get_volume(session, volume_id=volume_id)
        if volume is None or volume.user_id != user_id:
            raise ArtifactsNotFoundException(
                "volume_not_found", str(volume_id)
            )
        mount_path = self._mount_path_for(volume)
        if mount_path is None:
            raise ArtifactsUnprocessableException(
                "volume_offline",
                "No known mount path for this volume — re-register it while mounted.",
            )

        started = dt.datetime.now(dt.UTC)
        total = UpsertOutcome(inserted=0, updated=0, unchanged=0)
        files_seen = 0
        pages = 0
        cursor: str | None = None

        for _ in range(max_pages):
            page = await self.bridge.walk(
                mount_path=mount_path,
                subpath=subpath,
                cursor=cursor,
                max_entries=max_entries_per_page,
            )
            entries = page.get("entries") or []
            pages += 1
            if not entries:
                break
            files_seen += len(entries)
            normalized = [self._normalize_entry(e) for e in entries]
            outcome = await self.repo.upsert_files(
                session,
                user_id=user_id,
                volume_id=volume_id,
                files=normalized,
            )
            await session.commit()
            total = UpsertOutcome(
                inserted=total.inserted + outcome.inserted,
                updated=total.updated + outcome.updated,
                unchanged=total.unchanged + outcome.unchanged,
            )
            cursor = page.get("next_cursor")
            if not cursor:
                break

        await self.repo.touch_volume(
            session, volume_id=volume_id, mount_path=mount_path
        )
        await session.commit()

        finished = dt.datetime.now(dt.UTC)
        return {
            "volume_id": volume_id,
            "files_seen": files_seen,
            "files_added": total.inserted,
            "files_updated": total.updated,
            "files_unchanged": total.unchanged,
            "pages_fetched": pages,
            "started_at": started,
            "finished_at": finished,
        }

    def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        mtime_raw = entry["mtime"]
        if isinstance(mtime_raw, str):
            mtime = dt.datetime.fromisoformat(mtime_raw)
        else:
            mtime = mtime_raw
        mime = entry.get("mime")
        if not mime:
            mime, _ = mimetypes.guess_type(entry["relative_path"])
        kind = _kind_for(mime, entry["relative_path"])
        return {
            "relative_path": entry["relative_path"],
            "size_bytes": entry["size_bytes"],
            "mtime": mtime,
            "mime": mime,
            "kind": kind,
        }

    def _mount_path_for(self, volume: VolumeRow) -> str | None:
        if not volume.mount_hints:
            return None
        for hint in reversed(volume.mount_hints):
            if isinstance(hint, dict) and hint.get("path"):
                return str(hint["path"])
        return None

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
        try:
            return await self.repo.list_artifacts(
                session,
                user_id=user_id,
                volume_id=volume_id,
                kind=kind,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise ArtifactsServiceException(
                "list_failed", str(exc)
            ) from exc

    async def get_artifact(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactRow:
        row = await self.repo.get_artifact(
            session, user_id=user_id, artifact_id=artifact_id
        )
        if row is None:
            raise ArtifactsNotFoundException(
                "artifact_not_found", str(artifact_id)
            )
        return row

    async def delete_artifact(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        artifact_id: UUID,
    ) -> None:
        n = await self.repo.delete_artifact(
            session, user_id=user_id, artifact_id=artifact_id
        )
        if n == 0:
            raise ArtifactsNotFoundException(
                "artifact_not_found", str(artifact_id)
            )
        await session.commit()
        logger.info("artifact_deleted id=%s", artifact_id)
