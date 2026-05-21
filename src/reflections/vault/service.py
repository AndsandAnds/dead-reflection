"""
Vault service — export the user's memories + entities to a markdown tree,
and import a tree back to update content. The DB is canonical; the vault is
an interop layer (Obsidian, grep, backup, sync to git, etc.).

Layout written on export:

    <vault>/
      daily/YYYY-MM-DD.md     — every memory created that day, in time order
      people/<slug>.md        — one note per person entity
      places/<slug>.md
      events/<slug>.md
      topics/<slug>.md

Each note carries enough machine-readable metadata (YAML frontmatter +
HTML-comment markers for memory blocks) that the importer can find rows
by id and update them. The importer NEVER creates new memories or entities
in v1 — it's an update-only sync; pure-additions stay in your head until
they're recorded through the regular ingest paths.
"""

from __future__ import annotations

import io
import re
import tarfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

import sqlalchemy as sa  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.commons.logging import logger
from reflections.entities.repository import (
    EntitiesRepository,
    entities_table,
    slugify,
)
from reflections.memory.repository import MemoryRepository, memory_items
from reflections.memory.service import MemoryService
from reflections.vault.exceptions import VaultUnprocessableException
from reflections.vault.schemas import ExportStats, ImportStats


# ---- renderers ---------------------------------------------------------------


_KIND_DIRS = {
    "person": "people",
    "place": "places",
    "event": "events",
    "topic": "topics",
}


def _fm(d: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in d.items():
        if v is None:
            continue
        s = str(v).replace("\n", " ").strip()
        # Escape if the value contains anything YAML-ambiguous.
        if any(c in s for c in ':#&*!?[]{},'):
            s = '"' + s.replace('"', '\\"') + '"'
        lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def render_daily_note(
    note_date: date,
    memories: list[dict[str, Any]],
) -> str:
    """memories: list of {id, kind, scope, content, created_at_iso, entities: [(slug, kind)]}."""
    parts = [_fm({"date": note_date.isoformat()})]
    parts.append(f"\n# {note_date.isoformat()}\n")
    for m in memories:
        entity_links = " ".join(
            f"[[{_KIND_DIRS[k]}/{s}]]" for (s, k) in m.get("entities", [])
        )
        time_label = _time_label(m["created_at_iso"])
        parts.append(
            f'\n<!-- memory id={m["id"]} kind={m["kind"]} scope={m["scope"]} -->'
        )
        parts.append(f'\n## {m["kind"].title()} · {time_label}\n')
        if entity_links:
            parts.append(f"**Entities:** {entity_links}\n")
        parts.append("\n" + m["content"].rstrip() + "\n")
        parts.append("\n<!-- /memory -->\n")
    return "".join(parts)


def render_entity_note(
    entity: dict[str, Any],
    linked_memory_dates: list[str],  # ISO dates of linked memories
) -> str:
    parts = [
        _fm(
            {
                "id": entity["id"],
                "kind": entity["kind"],
                "name": entity["name"],
                "slug": entity["slug"],
                "updated_at": entity["updated_at_iso"],
            }
        )
    ]
    parts.append(f'\n# {entity["name"]}\n')
    if entity.get("description"):
        parts.append("\n" + entity["description"].rstrip() + "\n")
    if linked_memory_dates:
        parts.append("\n## Linked memories\n")
        for d in linked_memory_dates:
            parts.append(f"- [[daily/{d}]]\n")
    return "".join(parts)


def _time_label(iso_ts: str) -> str:
    try:
        return datetime.fromisoformat(iso_ts).strftime("%H:%M")
    except Exception:
        return iso_ts


# ---- parsers -----------------------------------------------------------------


_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_MEMORY_BLOCK_RE = re.compile(
    r"<!--\s*memory\s+id=(?P<id>[0-9a-fA-F-]{36})"
    r"(?:\s+kind=(?P<kind>\w+))?"
    r"(?:\s+scope=(?P<scope>\w+))?"
    r"\s*-->\n(?P<body>.*?)\n<!--\s*/memory\s*-->",
    re.DOTALL,
)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"')
        elif v.startswith("'") and v.endswith("'"):
            v = v[1:-1]
        fm[k.strip()] = v
    body = text[m.end():]
    return fm, body


@dataclass(frozen=True)
class ParsedMemoryBlock:
    id: UUID
    content: str


def parse_memory_blocks(daily_md: str) -> list[ParsedMemoryBlock]:
    """
    Extract memory blocks from a daily note. Content is everything between
    the open marker and close marker, with the auto-generated `## Card · …`
    or `## Chunk · …` heading + `**Entities:**` line stripped so we don't
    round-trip those into the DB.
    """
    out: list[ParsedMemoryBlock] = []
    for m in _MEMORY_BLOCK_RE.finditer(daily_md):
        body = m.group("body").strip()
        body = _strip_block_chrome(body)
        try:
            out.append(ParsedMemoryBlock(id=UUID(m.group("id")), content=body))
        except ValueError:
            continue
    return out


_HEADING_RE = re.compile(r"^##\s+(?:Card|Chunk)\s+·\s+\S+\s*\n", re.MULTILINE)
_ENTITIES_LINE_RE = re.compile(r"^\*\*Entities:\*\*[^\n]*\n", re.MULTILINE)


def _strip_block_chrome(body: str) -> str:
    body = _HEADING_RE.sub("", body, count=1)
    body = _ENTITIES_LINE_RE.sub("", body, count=1)
    return body.strip()


_DESCRIPTION_STOP_RE = re.compile(r"^##\s+Linked memories\s*$", re.MULTILINE)


def parse_entity_description(entity_body: str) -> str:
    """Strip the `# Name` heading + `## Linked memories` tail and return what's left."""
    # parse_frontmatter leaves a leading newline; drop whitespace first so
    # the `^#` anchor lands on the heading line.
    body = entity_body.lstrip()
    body = re.sub(r"^#\s+[^\n]*\n", "", body, count=1).strip()
    stop = _DESCRIPTION_STOP_RE.search(body)
    if stop:
        body = body[: stop.start()].rstrip()
    return body.strip()


# ---- vault service -----------------------------------------------------------


@dataclass
class VaultService:
    memory_service: MemoryService
    memory_repo: MemoryRepository
    entities_repo: EntitiesRepository

    @classmethod
    def default(cls) -> "VaultService":
        ms = MemoryService.create()
        return cls(
            memory_service=ms,
            memory_repo=ms.repository,
            entities_repo=EntitiesRepository(),
        )

    # --- export ---

    async def export_user_vault(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
    ) -> tuple[bytes, ExportStats]:
        """Render the entire user vault as a tar.gz bytes blob + stats."""
        # Load every memory for this user (cap defensively).
        mem_rows = await self._load_all_memories(session, user_id=user_id)
        ent_rows = await self.entities_repo.list_entities(
            session, user_id=user_id, kind=None, limit=10_000, offset=0
        )
        links_by_memory = await self.memory_repo.get_linked_entities(
            session,
            user_id=user_id,
            memory_ids=[m["id"] for m in mem_rows],
        )

        # Daily groups: date string → list of memory dicts in time order.
        daily: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # entity_id → set of ISO dates (for back-links on entity notes)
        entity_dates: dict[UUID, set[str]] = defaultdict(set)

        for m in mem_rows:
            iso = m["created_at"].isoformat()
            d_str = m["created_at"].date().isoformat()
            entries = links_by_memory.get(m["id"], [])
            m_entities = [(e.slug, e.kind) for e in entries]
            for e in entries:
                entity_dates[e.id].add(d_str)
            daily[d_str].append(
                {
                    "id": str(m["id"]),
                    "kind": m["kind"],
                    "scope": m["scope"],
                    "content": m["content"],
                    "created_at_iso": iso,
                    "entities": m_entities,
                }
            )

        # Render to in-memory tar.gz.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            self._add(tar, "vault/.reflections-version", "1\n")
            for d_str in sorted(daily.keys()):
                # Render in chronological order within the day.
                memories = sorted(
                    daily[d_str], key=lambda x: x["created_at_iso"]
                )
                content = render_daily_note(date.fromisoformat(d_str), memories)
                self._add(tar, f"vault/daily/{d_str}.md", content)
            entity_note_count = 0
            for e in ent_rows:
                dir_ = _KIND_DIRS.get(e.kind)
                if dir_ is None:
                    continue
                # Use existing slug if set; fall back to slugify(name).
                slug = e.slug or slugify(e.name)
                dates = sorted(entity_dates.get(e.id, set()))
                content = render_entity_note(
                    {
                        "id": str(e.id),
                        "kind": e.kind,
                        "name": e.name,
                        "slug": slug,
                        "description": e.description,
                        "updated_at_iso": e.updated_at.isoformat(),
                    },
                    dates,
                )
                self._add(tar, f"vault/{dir_}/{slug}.md", content)
                entity_note_count += 1
        return buf.getvalue(), ExportStats(
            daily_notes=len(daily),
            entity_notes=entity_note_count,
            memories=len(mem_rows),
            entities=len(ent_rows),
        )

    async def _load_all_memories(
        self, session: AsyncSession, *, user_id: UUID
    ) -> list[dict[str, Any]]:
        stmt = (
            sa.select(
                memory_items.c.id,
                memory_items.c.kind,
                memory_items.c.scope,
                memory_items.c.content,
                memory_items.c.created_at,
            )
            .where(memory_items.c.user_id == user_id)
            .order_by(memory_items.c.created_at.asc())
            .limit(50_000)
        )
        rows = (await session.execute(stmt)).all()
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "scope": r.scope,
                "content": r.content,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    def _add(tar: tarfile.TarFile, path: str, content: str) -> None:
        data = content.encode("utf-8")
        info = tarfile.TarInfo(name=path)
        info.size = len(data)
        info.mtime = int(datetime.now().timestamp())
        tar.addfile(info, io.BytesIO(data))

    # --- import ---

    async def import_user_vault(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        tarball: bytes,
        dry_run: bool = False,
    ) -> ImportStats:
        """
        Update existing memories' content (re-embed) and entities' descriptions
        from an exported vault. NEW rows (memories/entities not already in the
        DB) are skipped in v1.
        """
        if not tarball:
            raise VaultUnprocessableException("empty_upload")

        try:
            tar = tarfile.open(fileobj=io.BytesIO(tarball), mode="r:*")
        except tarfile.TarError as exc:
            raise VaultUnprocessableException(
                "bad_tarball", str(exc)
            ) from exc

        memories_updated = 0
        memories_reembedded = 0
        entities_updated = 0
        skipped = 0
        errors: list[str] = []

        try:
            for member in tar.getmembers():
                if not member.isfile() or not member.name.endswith(".md"):
                    continue
                if "vault/.reflections-version" in member.name:
                    continue
                # Filter macOS AppleDouble metadata (._foo.md) — bsdtar on
                # macOS happily packs these when the source dir has extended
                # attributes. They aren't markdown.
                if Path(member.name).name.startswith("._"):
                    continue
                try:
                    fh = tar.extractfile(member)
                    if fh is None:
                        continue
                    text = fh.read().decode("utf-8", errors="replace")
                except Exception as exc:
                    errors.append(f"{member.name}: {exc}")
                    continue

                parts = Path(member.name).parts
                # Expect "vault/<bucket>/<file>.md"
                if len(parts) < 3:
                    skipped += 1
                    continue
                bucket = parts[-2]

                if bucket == "daily":
                    updated, reembedded = await self._import_daily(
                        session,
                        user_id=user_id,
                        text=text,
                        dry_run=dry_run,
                    )
                    memories_updated += updated
                    memories_reembedded += reembedded
                elif bucket in {"people", "places", "events", "topics"}:
                    if await self._import_entity(
                        session,
                        user_id=user_id,
                        text=text,
                        dry_run=dry_run,
                    ):
                        entities_updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        finally:
            tar.close()

        return ImportStats(
            memories_updated=memories_updated,
            memories_reembedded=memories_reembedded,
            entities_updated=entities_updated,
            skipped=skipped,
            errors=errors,
        )

    async def _import_daily(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        text: str,
        dry_run: bool,
    ) -> tuple[int, int]:
        blocks = parse_memory_blocks(text)
        updated = 0
        reembedded = 0
        for blk in blocks:
            existing = await self.memory_repo.get_by_id(
                session, user_id=user_id, memory_id=blk.id
            )
            if existing is None:
                continue
            if existing.content == blk.content:
                continue
            if dry_run:
                updated += 1
                continue
            try:
                await self.memory_service.update_content(
                    session,
                    user_id=user_id,
                    memory_id=blk.id,
                    content=blk.content,
                )
                updated += 1
                reembedded += 1
            except Exception as exc:
                logger.warning(
                    "vault_import_memory_update_failed id=%s err=%s",
                    blk.id,
                    exc,
                )
        return updated, reembedded

    async def _import_entity(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        text: str,
        dry_run: bool,
    ) -> bool:
        fm, body = parse_frontmatter(text)
        eid_raw = fm.get("id")
        if not eid_raw:
            return False
        try:
            eid = UUID(eid_raw)
        except ValueError:
            return False
        existing = await self.entities_repo.get_by_id(
            session, user_id=user_id, entity_id=eid
        )
        if existing is None:
            return False
        description = parse_entity_description(body)
        if not description:
            # v1 doesn't support clearing a description via vault import
            # (entities_repo.update treats description=None as "don't touch").
            # Edit through the UI / MCP if you want to wipe one.
            return False
        if (existing.description or "") == description:
            return False
        if dry_run:
            return True
        n = await self.entities_repo.update(
            session,
            entity_id=eid,
            user_id=user_id,
            description=description,
        )
        if n > 0:
            await session.commit()
            return True
        return False


def stream_all(items: Iterable[Any]) -> Iterable[Any]:  # pragma: no cover
    yield from items
