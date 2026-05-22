"""
Wiring test: the artifact extraction service materializes direct
(artifact_id, entity_id) rows into artifact_entity_links alongside the
chunk-mediated path, so the /memory/graph viz can render file↔entity
edges directly (rather than as a two-hop path through a chunk node).

Tests focus on `_run_entity_extraction` so we exercise the seam without
needing to wire up a full extract_one pipeline (bridge bytes, dispatcher,
memory item insert, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest  # type: ignore[import-not-found]

from reflections.artifacts.extraction_service import ArtifactExtractionService
from reflections.commons.ids import uuid7_uuid
from reflections.extractors.base import ExtractedChunk


@dataclass
class FakeArtifactsRepo:
    link_calls: list[tuple[UUID, list[UUID]]] = field(default_factory=list)
    raise_on_link: bool = False

    async def link_entities_via_chunks(
        self,
        _session: Any,
        *,
        artifact_id: UUID,
        memory_item_ids: list[UUID],
    ) -> int:
        if self.raise_on_link:
            raise RuntimeError("simulated DB failure")
        self.link_calls.append((artifact_id, list(memory_item_ids)))
        return len(memory_item_ids)


@dataclass
class FakeEntities:
    """Stand-in for EntitiesService — records each per-chunk call."""

    calls: list[tuple[UUID, list[UUID], str]] = field(default_factory=list)
    raise_on_extract: bool = False

    async def upsert_and_link(
        self,
        _session: Any,
        *,
        user_id: UUID,
        memory_item_ids: list[UUID],
        chunk_text: str,
    ) -> int:
        if self.raise_on_extract:
            raise RuntimeError("simulated extractor failure")
        self.calls.append((user_id, list(memory_item_ids), chunk_text))
        return len(memory_item_ids)


@dataclass
class FakeMemoryService:
    entities: FakeEntities | None


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _service(
    *,
    raise_on_link: bool = False,
    raise_on_extract: bool = False,
    entities: bool = True,
) -> tuple[ArtifactExtractionService, FakeArtifactsRepo, FakeEntities | None]:
    repo = FakeArtifactsRepo(raise_on_link=raise_on_link)
    ents: FakeEntities | None = (
        FakeEntities(raise_on_extract=raise_on_extract) if entities else None
    )
    memory = FakeMemoryService(entities=ents)
    svc = ArtifactExtractionService(
        repo=repo,  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )
    return svc, repo, ents


@pytest.mark.anyio
async def test_extraction_materializes_direct_artifact_entity_link() -> None:
    """Happy path: after per-chunk entity extraction, one batched link
    call goes to the repo with (artifact_id, written_chunk_ids)."""
    svc, repo, ents = _service()
    session = FakeSession()
    user_id = uuid7_uuid()
    artifact_id = uuid7_uuid()
    chunk_ids = [uuid7_uuid(), uuid7_uuid()]
    chunks = [
        ExtractedChunk(content="Sarah came over for cabin trip in Tahoe."),
        ExtractedChunk(content="Brooklyn loft, second page of the PDF."),
    ]

    await svc._run_entity_extraction(
        session,  # type: ignore[arg-type]
        user_id=user_id,
        artifact_id=artifact_id,
        chunks=chunks,
        written_ids=chunk_ids,
    )

    # Per-chunk entity extraction still runs (chunk-mediated path is
    # preserved — graph viz keeps the "what did the file actually say"
    # node).
    assert ents is not None
    assert len(ents.calls) == 2
    assert [c[1][0] for c in ents.calls] == chunk_ids

    # And exactly one direct link call, batched over all written chunks.
    assert repo.link_calls == [(artifact_id, chunk_ids)]


@pytest.mark.anyio
async def test_no_link_call_when_no_chunks_written() -> None:
    """If no chunk text survived (all blank), there's nothing to link."""
    svc, repo, _ = _service()
    session = FakeSession()

    await svc._run_entity_extraction(
        session,  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        artifact_id=uuid7_uuid(),
        chunks=[],
        written_ids=[],
    )

    assert repo.link_calls == []


@pytest.mark.anyio
async def test_link_failure_is_swallowed_and_rolls_back() -> None:
    """A DB blip on the direct-link insert must not blow up the extract;
    the chunk-mediated path is already committed and authoritative."""
    svc, repo, _ = _service(raise_on_link=True)
    session = FakeSession()

    await svc._run_entity_extraction(
        session,  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        artifact_id=uuid7_uuid(),
        chunks=[ExtractedChunk(content="x")],
        written_ids=[uuid7_uuid()],
    )

    # No row recorded (repo raised) but the per-chunk entity extraction
    # commits did happen, and the failure path issued a rollback.
    assert repo.link_calls == []
    assert session.rollbacks >= 1


@pytest.mark.anyio
async def test_no_link_call_when_entities_service_disabled() -> None:
    """Some deployments wire MemoryService without entities (e.g.
    extractor unavailable). The direct-link step is part of the entity
    path — skip cleanly."""
    svc, repo, _ = _service(entities=False)
    session = FakeSession()

    await svc._run_entity_extraction(
        session,  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        artifact_id=uuid7_uuid(),
        chunks=[ExtractedChunk(content="x")],
        written_ids=[uuid7_uuid()],
    )

    assert repo.link_calls == []
