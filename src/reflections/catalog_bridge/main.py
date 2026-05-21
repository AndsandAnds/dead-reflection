"""
Catalog bridge — host-side filesystem walker.

Runs on macOS (or any host with the user's drives mounted), separate from
the dockerized api. The api proxies through it for:

  - volume identification (UUID + .reflections-volume.json marker)
  - directory walks (stat-only; cheap; pagination)
  - lazy sha256
  - byte reads (Range-aware) for extraction

The bridge stores nothing — Postgres in the api container is the catalog
of record. We just walk, stat, hash on demand, and stream bytes.

Why a separate process: external drives mount and unmount whenever the
user plugs them in. A Dockerized walker would need bind-mounts at compose
time and a restart for every replug; this is the only way to support
"plug in a drive any time, the catalog comes online" UX.

Same deployment pattern as the calendar bridge — for stable TCC and
Full Disk Access, run via the .app bundle built by
`scripts/build-catalog-bridge-app.sh`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import os
import subprocess
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import (  # type: ignore[import-not-found]
    FastAPI,
    Header,
    HTTPException,
    Query,
    Response,
)
from fastapi.responses import StreamingResponse  # type: ignore[import-not-found]
from pydantic import BaseModel, Field

MARKER_FILENAME = ".reflections-volume.json"


# --- Models -------------------------------------------------------------------


class VolumeIdentity(BaseModel):
    label: str
    volume_uuid: str | None = None
    fingerprint: str
    mount_path: str
    marker_present: bool


class FileEntry(BaseModel):
    relative_path: str
    size_bytes: int
    mtime: dt.datetime
    mime: str | None = None
    is_dir: bool = False


class WalkPage(BaseModel):
    entries: list[FileEntry]
    next_cursor: str | None = None
    total_seen: int


class FingerprintResponse(BaseModel):
    sha256: str
    size_bytes: int


class HealthResponse(BaseModel):
    status: str
    mounted_volumes: list[str]


class ProbeRequest(BaseModel):
    path: str = Field(min_length=1)
    label: str | None = None  # used only when creating a new marker


# --- App + auth ---------------------------------------------------------------


app = FastAPI(title="Reflections Catalog Bridge", version="0.1.0")


def _check_secret(supplied: str | None) -> None:
    expected = os.environ.get("CATALOG_BRIDGE_SECRET")
    if not expected:
        return
    if supplied != expected:
        raise HTTPException(
            status_code=401, detail="invalid_catalog_bridge_secret"
        )


# --- Helpers ------------------------------------------------------------------


def _macos_volume_uuid(mount_path: str) -> str | None:
    """Read the OS-level volume UUID via `diskutil info -plist`. Returns
    None if diskutil isn't available (non-macOS) or the path isn't a
    mounted volume."""
    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", mount_path],
            capture_output=True,
            timeout=4,
        )
        if proc.returncode != 0:
            return None
        # Parse plist via stdlib so we don't drag in another dep.
        import plistlib

        data = plistlib.loads(proc.stdout)
        uid = data.get("VolumeUUID")
        return str(uid) if uid else None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None


def _read_or_create_marker(
    mount_path: Path, label: str | None
) -> tuple[str, bool]:
    """Returns (fingerprint, marker_was_already_present).

    On first call for a volume we write a small JSON file at the volume
    root with a generated UUID. Subsequent calls read it back. The marker
    is what lets us re-identify the volume across remounts even when
    the OS UUID isn't available.
    """
    marker = mount_path / MARKER_FILENAME
    if marker.exists():
        try:
            data = json.loads(marker.read_text())
            fp = str(data.get("fingerprint") or "").strip()
            if fp:
                return fp, True
        except Exception:
            pass
    fp = str(uuid.uuid4())
    payload = {
        "fingerprint": fp,
        "label": label or mount_path.name,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "note": (
            "This file lets Reflections recognize this volume across "
            "remounts. Safe to commit/version. Delete only if you also "
            "delete the matching `volumes` row in Reflections."
        ),
    }
    try:
        marker.write_text(json.dumps(payload, indent=2))
    except OSError:
        # Read-only mount? Surface a clear error so the caller can fall
        # back to volume_uuid-only identity.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "volume_not_writable",
                "hint": (
                    "Can't write the .reflections-volume.json marker. "
                    "If the disk is read-only, we'll have to rely on the "
                    "OS volume UUID alone — register the volume with "
                    "force_uuid=true."
                ),
            },
        )
    return fp, False


def _safe_resolve(volume_root: Path, relative_path: str) -> Path:
    """Resolve <volume>/<relative_path> while refusing to escape the
    volume root (path traversal). Symlinks are followed but the result
    must still be inside `volume_root`."""
    rel = relative_path.strip().lstrip("/")
    target = (volume_root / rel).resolve()
    root_resolved = volume_root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "path_escape", "relative_path": relative_path},
        ) from exc
    return target


def _file_entry(
    full_path: Path, volume_root: Path, st: os.stat_result
) -> FileEntry:
    rel = full_path.relative_to(volume_root).as_posix()
    is_dir = (st.st_mode & 0o170000) == 0o040000
    mime = None
    if not is_dir:
        guess, _ = mimetypes.guess_type(full_path.name)
        mime = guess
    return FileEntry(
        relative_path=rel,
        size_bytes=st.st_size,
        mtime=dt.datetime.fromtimestamp(st.st_mtime, tz=dt.UTC),
        mime=mime,
        is_dir=is_dir,
    )


# --- Routes -------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
def health(
    x_catalog_bridge_secret: Annotated[str | None, Header()] = None,
) -> HealthResponse:
    _check_secret(x_catalog_bridge_secret)
    mounted: list[str] = []
    try:
        for entry in os.scandir("/Volumes"):
            if entry.is_dir():
                mounted.append(entry.path)
    except FileNotFoundError:
        pass  # Linux test host
    return HealthResponse(status="ok", mounted_volumes=mounted)


@app.post("/probe", response_model=VolumeIdentity)
def probe(
    req: ProbeRequest,
    x_catalog_bridge_secret: Annotated[str | None, Header()] = None,
) -> VolumeIdentity:
    """Identify a mounted volume. Reads/creates the marker file and
    returns the (label, volume_uuid, fingerprint). Idempotent."""
    _check_secret(x_catalog_bridge_secret)
    mount_path = Path(req.path).resolve()
    if not mount_path.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"error": "path_not_a_directory", "path": str(mount_path)},
        )
    fp, marker_present = _read_or_create_marker(mount_path, req.label)
    return VolumeIdentity(
        label=req.label or mount_path.name,
        volume_uuid=_macos_volume_uuid(str(mount_path)),
        fingerprint=fp,
        mount_path=str(mount_path),
        marker_present=marker_present,
    )


@app.get("/walk", response_model=WalkPage)
def walk(
    mount_path: Annotated[str, Query()],
    subpath: Annotated[str, Query()] = "",
    cursor: Annotated[str | None, Query()] = None,
    max_entries: Annotated[int, Query(ge=1, le=20000)] = 5000,
    x_catalog_bridge_secret: Annotated[str | None, Header()] = None,
) -> WalkPage:
    """
    Single-page directory walk under <mount_path>/<subpath>. Stat-only —
    we never read file bytes here. Returns up to `max_entries` files;
    if there's more, `next_cursor` is the resume token (currently the
    last-seen relative path).

    For huge volumes (10TB photo archive), the api iterates per-subtree
    rather than asking for the whole world at once. This endpoint serves
    one chunk per request.
    """
    _check_secret(x_catalog_bridge_secret)
    root = Path(mount_path).resolve()
    if not root.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"error": "mount_path_not_a_directory"},
        )
    start = _safe_resolve(root, subpath) if subpath else root
    if not start.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"error": "subpath_not_a_directory"},
        )

    out: list[FileEntry] = []
    total = 0
    next_cursor: str | None = None
    skipping = cursor is not None

    # os.scandir is the fast path on macOS APFS; falls back fine on Linux
    # and Windows. We do a recursive walk with an explicit stack so we
    # can resume from `cursor` without recursion blowing the budget.
    stack: list[Path] = [start]
    while stack and total < max_entries:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name)
        except (FileNotFoundError, PermissionError):
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except (FileNotFoundError, PermissionError):
                continue
            entry_path = Path(entry.path)
            # Don't catalog our own marker — it's an implementation detail.
            if entry_path.name == MARKER_FILENAME and entry_path.parent == root:
                continue
            try:
                rel = entry_path.relative_to(root).as_posix()
            except ValueError:
                continue

            if skipping:
                if rel == cursor:
                    skipping = False
                continue

            if entry.is_dir(follow_symlinks=False):
                # Recurse but record nothing for the directory itself.
                stack.append(entry_path)
                continue

            out.append(_file_entry(entry_path, root, st))
            total += 1
            if total >= max_entries:
                next_cursor = rel
                break

    return WalkPage(entries=out, next_cursor=next_cursor, total_seen=total)


@app.get("/fingerprint", response_model=FingerprintResponse)
def fingerprint(
    mount_path: Annotated[str, Query()],
    relative_path: Annotated[str, Query()],
    x_catalog_bridge_secret: Annotated[str | None, Header()] = None,
) -> FingerprintResponse:
    """Compute the sha256 of a single file. Streams in 1 MiB chunks so
    we don't load 5 GB videos into RAM."""
    _check_secret(x_catalog_bridge_secret)
    root = Path(mount_path).resolve()
    target = _safe_resolve(root, relative_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail={"error": "not_a_file"})
    h = hashlib.sha256()
    size = 0
    with open(target, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return FingerprintResponse(sha256=h.hexdigest(), size_bytes=size)


@app.get("/file")
def file(
    mount_path: Annotated[str, Query()],
    relative_path: Annotated[str, Query()],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    x_catalog_bridge_secret: Annotated[str | None, Header()] = None,
) -> Any:
    """Stream the bytes of a file. Supports a single Range request so
    large media can be partial-fetched by extractors that don't need the
    whole thing (e.g. ID3, EXIF, PDF trailer)."""
    _check_secret(x_catalog_bridge_secret)
    root = Path(mount_path).resolve()
    target = _safe_resolve(root, relative_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail={"error": "not_a_file"})
    size = target.stat().st_size
    mime, _ = mimetypes.guess_type(target.name)
    media_type = mime or "application/octet-stream"

    start = 0
    end = size - 1
    status = 200
    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header[len("bytes="):]
            s, _, e = spec.partition("-")
            start = int(s) if s else 0
            end = int(e) if e else size - 1
            if start < 0 or end >= size or start > end:
                raise ValueError("bad range")
            status = 206
        except ValueError as exc:
            raise HTTPException(
                status_code=416, detail={"error": "invalid_range"}
            ) from exc

    length = end - start + 1

    def _iter():
        with open(target, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _iter(), status_code=status, media_type=media_type, headers=headers
    )
