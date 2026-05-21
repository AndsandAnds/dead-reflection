"""
Unit tests for ArtifactsService with a mocked CatalogBridgeClient.

Live bridge / external-drive exercises are deferred to the user-driven
smoke path; the contract-level tests here cover the upsert state machine
(new / changed / unchanged), volume identity (uuid + fingerprint), and
the API error mapping shape.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest  # type: ignore[import-not-found]

from reflections.artifacts.exceptions import (
    ArtifactsNotFoundException,
    ArtifactsUnprocessableException,
)
from reflections.artifacts.repository import UpsertOutcome, VolumeRow
from reflections.artifacts.service import ArtifactsService, _kind_for
from reflections.commons.ids import uuid7_uuid


# --- fakes --------------------------------------------------------------------


@dataclass
class FakeRepo:
    volumes: list[VolumeRow] = field(default_factory=list)
    upserts: list[list[dict]] = field(default_factory=list)
    touched: list[tuple[UUID, str | None]] = field(default_factory=list)

    async def find_volume(self, _s, *, user_id, volume_uuid, fingerprint):
        for v in self.volumes:
            if v.user_id != user_id:
                continue
            if fingerprint and v.fingerprint == fingerprint:
                return v
            if volume_uuid and v.volume_uuid == volume_uuid:
                return v
        return None

    async def insert_volume(
        self,
        _s,
        *,
        user_id,
        label,
        volume_uuid,
        fingerprint,
        mount_hints=None,
    ):
        row = VolumeRow(
            id=uuid7_uuid(),
            user_id=user_id,
            label=label,
            volume_uuid=volume_uuid,
            fingerprint=fingerprint,
            mount_hints=mount_hints,
            created_at=dt.datetime.now(dt.UTC),
            last_seen_at=dt.datetime.now(dt.UTC),
        )
        self.volumes.append(row)
        return row

    async def touch_volume(self, _s, *, volume_id, mount_path):
        self.touched.append((volume_id, mount_path))

    async def get_volume(self, _s, *, volume_id):
        for v in self.volumes:
            if v.id == volume_id:
                return v
        return None

    async def upsert_files(self, _s, *, user_id, volume_id, files):
        self.upserts.append(files)
        # Fake outcome: everything new on the first call, all unchanged
        # on repeats with identical (size, mtime).
        return UpsertOutcome(
            inserted=len(files), updated=0, unchanged=0
        )


@dataclass
class FakeBridge:
    probe_response: dict | None = None
    walk_pages: list[dict] = field(default_factory=list)
    walk_idx: int = 0
    walk_calls: list[dict] = field(default_factory=list)

    async def probe(self, *, mount_path, label=None):
        if self.probe_response is None:
            return {
                "label": label or mount_path.rstrip("/").split("/")[-1],
                "volume_uuid": "ABCD-1234",
                "fingerprint": "fp-1",
                "mount_path": mount_path,
                "marker_present": False,
            }
        return self.probe_response

    async def walk(
        self, *, mount_path, subpath="", cursor=None, max_entries=5000
    ):
        self.walk_calls.append(
            {
                "mount_path": mount_path,
                "subpath": subpath,
                "cursor": cursor,
                "max_entries": max_entries,
            }
        )
        if self.walk_idx >= len(self.walk_pages):
            return {"entries": [], "next_cursor": None, "total_seen": 0}
        page = self.walk_pages[self.walk_idx]
        self.walk_idx += 1
        return page


class FakeSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None


# --- kind classification ------------------------------------------------------


def test_kind_for_classifies_by_mime() -> None:
    assert _kind_for("application/pdf", "x.pdf") == "pdf"
    assert _kind_for("image/jpeg", "a.jpg") == "image"
    assert _kind_for("audio/mpeg", "a.mp3") == "audio"
    assert _kind_for("video/mp4", "a.mp4") == "video"
    assert _kind_for("text/plain", "a.txt") == "other"


def test_kind_for_falls_back_to_extension() -> None:
    assert _kind_for(None, "photo.HEIC") == "image"
    assert _kind_for(None, "song.flac") == "audio"
    assert _kind_for(None, "clip.mkv") == "video"
    assert _kind_for(None, "doc.txt") == "other"


# --- register_volume ----------------------------------------------------------


@pytest.mark.anyio
async def test_register_volume_creates_new_row() -> None:
    repo = FakeRepo()
    bridge = FakeBridge()
    svc = ArtifactsService(repo=repo, bridge=bridge)  # type: ignore[arg-type]

    user_id = uuid7_uuid()
    row = await svc.register_volume(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        mount_path="/Volumes/Photos-10TB",
        label="Photos Archive",
    )

    assert row.user_id == user_id
    assert row.label == "Photos Archive"
    assert row.volume_uuid == "ABCD-1234"
    assert row.fingerprint == "fp-1"
    assert len(repo.volumes) == 1


@pytest.mark.anyio
async def test_register_volume_dedupes_on_fingerprint() -> None:
    """Replug the same drive at a different mount path → same row,
    mount_hints get extended."""
    repo = FakeRepo()
    bridge = FakeBridge()
    svc = ArtifactsService(repo=repo, bridge=bridge)  # type: ignore[arg-type]
    user_id = uuid7_uuid()

    first = await svc.register_volume(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        mount_path="/Volumes/Photos-10TB",
        label="Photos Archive",
    )
    # Second registration at a different mount path, same fingerprint.
    bridge.probe_response = {
        "label": "Photos Archive",
        "volume_uuid": "ABCD-1234",
        "fingerprint": "fp-1",
        "mount_path": "/Volumes/Photos-10TB 1",
        "marker_present": True,
    }
    second = await svc.register_volume(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        mount_path="/Volumes/Photos-10TB 1",
    )
    assert second.id == first.id
    assert len(repo.volumes) == 1
    # touch_volume was called with the new mount path.
    assert repo.touched[-1] == (first.id, "/Volumes/Photos-10TB 1")


# --- catalog_volume -----------------------------------------------------------


@pytest.mark.anyio
async def test_catalog_volume_iterates_pages_until_cursor_empty() -> None:
    repo = FakeRepo()
    bridge = FakeBridge(
        walk_pages=[
            {
                "entries": [
                    {
                        "relative_path": "Photos/2024/IMG_1.jpg",
                        "size_bytes": 4321,
                        "mtime": "2026-05-21T12:00:00+00:00",
                        "mime": "image/jpeg",
                    }
                ],
                "next_cursor": "cur1",
                "total_seen": 1,
            },
            {
                "entries": [
                    {
                        "relative_path": "Photos/2024/IMG_2.jpg",
                        "size_bytes": 9999,
                        "mtime": "2026-05-21T12:01:00+00:00",
                        "mime": "image/jpeg",
                    }
                ],
                "next_cursor": None,
                "total_seen": 1,
            },
        ]
    )
    svc = ArtifactsService(repo=repo, bridge=bridge)  # type: ignore[arg-type]
    user_id = uuid7_uuid()
    volume = await svc.register_volume(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        mount_path="/Volumes/Photos-10TB",
    )

    result = await svc.catalog_volume(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        volume_id=volume.id,
        subpath="Photos",
        max_entries_per_page=10,
    )
    assert result["pages_fetched"] == 2
    assert result["files_seen"] == 2
    assert result["files_added"] == 2
    # The walker forwarded the cursor between pages.
    assert bridge.walk_calls[0]["cursor"] is None
    assert bridge.walk_calls[1]["cursor"] == "cur1"
    # Kind classification ran on each entry.
    flattened = [f for batch in repo.upserts for f in batch]
    assert all(f["kind"] == "image" for f in flattened)


@pytest.mark.anyio
async def test_catalog_volume_requires_known_mount_path() -> None:
    """A volume whose mount_hints are empty can't be walked — surface
    a clean unprocessable, not a stacktrace."""
    repo = FakeRepo()
    bridge = FakeBridge()
    svc = ArtifactsService(repo=repo, bridge=bridge)  # type: ignore[arg-type]
    user_id = uuid7_uuid()
    # Insert a row with no mount hints (simulating "registered once, drive
    # has been unplugged for a long time, mount_hints got cleared").
    vol = VolumeRow(
        id=uuid7_uuid(),
        user_id=user_id,
        label="Empty",
        volume_uuid="X",
        fingerprint="Y",
        mount_hints=None,
        created_at=dt.datetime.now(dt.UTC),
        last_seen_at=None,
    )
    repo.volumes.append(vol)

    with pytest.raises(ArtifactsUnprocessableException):
        await svc.catalog_volume(
            FakeSession(),  # type: ignore[arg-type]
            user_id=user_id,
            volume_id=vol.id,
        )


@pytest.mark.anyio
async def test_catalog_volume_rejects_other_users_volume() -> None:
    repo = FakeRepo()
    bridge = FakeBridge()
    svc = ArtifactsService(repo=repo, bridge=bridge)  # type: ignore[arg-type]
    owner = uuid7_uuid()
    intruder = uuid7_uuid()
    vol = VolumeRow(
        id=uuid7_uuid(),
        user_id=owner,
        label="Mine",
        volume_uuid=None,
        fingerprint="z",
        mount_hints=[{"path": "/Volumes/Mine"}],
        created_at=dt.datetime.now(dt.UTC),
        last_seen_at=None,
    )
    repo.volumes.append(vol)

    with pytest.raises(ArtifactsNotFoundException):
        await svc.catalog_volume(
            FakeSession(),  # type: ignore[arg-type]
            user_id=intruder,
            volume_id=vol.id,
        )
