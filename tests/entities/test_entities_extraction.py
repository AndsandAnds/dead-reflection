from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest  # type: ignore[import-not-found]

from reflections.commons.ids import uuid7_uuid
from reflections.entities.repository import slugify
from reflections.entities.schemas import EntityKind, ExtractedEntities
from reflections.entities.service import EntitiesService


@dataclass
class FakeRepo:
    """In-memory entities repository for service-level tests."""

    inserted: list[dict[str, Any]] = field(default_factory=list)
    links: list[tuple[UUID, UUID, str]] = field(default_factory=list)

    async def get_by_slug(
        self, _session, *, user_id: UUID, kind: EntityKind, slug: str
    ):
        for row in self.inserted:
            if (
                row["user_id"] == user_id
                and row["kind"] == kind
                and row["slug"] == slug
            ):

                class R:
                    pass

                r = R()
                for k, v in row.items():
                    setattr(r, k, v)
                return r
        return None

    async def insert(
        self,
        _session,
        *,
        user_id: UUID,
        kind: EntityKind,
        name: str,
        slug: str,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> UUID:
        new_id = uuid7_uuid()
        self.inserted.append(
            {
                "id": new_id,
                "user_id": user_id,
                "kind": kind,
                "name": name,
                "slug": slug,
                "description": description,
                "attributes": attributes,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
        return new_id

    async def insert_link(
        self,
        _session,
        *,
        memory_item_id: UUID,
        entity_id: UUID,
        relation: str = "",
        weight: float | None = None,
    ) -> None:
        self.links.append((memory_item_id, entity_id, relation))


class FakeExtractor:
    def __init__(self, result: ExtractedEntities):
        self.result = result
        self.calls = 0

    async def extract(self, text: str) -> ExtractedEntities:
        self.calls += 1
        return self.result


class FakeSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None


def _make_service(extractor: FakeExtractor) -> tuple[EntitiesService, FakeRepo]:
    repo = FakeRepo()
    svc = EntitiesService(repo=repo, extractor_factory=lambda: extractor)  # type: ignore[arg-type]
    return svc, repo


@pytest.mark.anyio
async def test_upsert_and_link_inserts_new_entities_and_links() -> None:
    extracted = ExtractedEntities(
        people=["Sarah"], places=["Home"], events=["Birthday"], topics=["plans"]
    )
    extractor = FakeExtractor(extracted)
    svc, repo = _make_service(extractor)
    user_id = uuid7_uuid()
    mem_id = uuid7_uuid()

    edges = await svc.upsert_and_link(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        memory_item_ids=[mem_id],
        chunk_text="Sarah came to my house for my birthday and we made plans.",
    )

    assert edges == 4  # 4 entities * 1 memory
    assert {r["slug"] for r in repo.inserted} == {"sarah", "home", "birthday", "plans"}
    assert all(l[0] == mem_id for l in repo.links)


@pytest.mark.anyio
async def test_upsert_and_link_reuses_existing_entity() -> None:
    extracted = ExtractedEntities(people=["Sarah"])
    extractor = FakeExtractor(extracted)
    svc, repo = _make_service(extractor)
    user_id = uuid7_uuid()

    mem1 = uuid7_uuid()
    mem2 = uuid7_uuid()

    await svc.upsert_and_link(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        memory_item_ids=[mem1],
        chunk_text="Saw Sarah at the park.",
    )
    await svc.upsert_and_link(
        FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        memory_item_ids=[mem2],
        chunk_text="Sarah told a great joke today.",
    )

    # Only one Sarah row, two links to it.
    sarah_rows = [r for r in repo.inserted if r["slug"] == "sarah"]
    assert len(sarah_rows) == 1
    sarah_id = sarah_rows[0]["id"]
    sarah_links = [l for l in repo.links if l[1] == sarah_id]
    assert {l[0] for l in sarah_links} == {mem1, mem2}


@pytest.mark.anyio
async def test_upsert_and_link_extraction_failure_returns_zero() -> None:
    class BrokenExtractor:
        async def extract(self, text: str) -> ExtractedEntities:
            raise RuntimeError("ollama down")

    repo = FakeRepo()
    svc = EntitiesService(repo=repo, extractor_factory=lambda: BrokenExtractor())  # type: ignore[arg-type]

    edges = await svc.upsert_and_link(
        FakeSession(),  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        memory_item_ids=[uuid7_uuid()],
        chunk_text="anything",
    )
    assert edges == 0
    assert repo.inserted == []


@pytest.mark.anyio
async def test_upsert_and_link_noop_on_empty_inputs() -> None:
    svc, repo = _make_service(FakeExtractor(ExtractedEntities()))
    edges_empty_text = await svc.upsert_and_link(
        FakeSession(),  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        memory_item_ids=[uuid7_uuid()],
        chunk_text="   ",
    )
    edges_no_mems = await svc.upsert_and_link(
        FakeSession(),  # type: ignore[arg-type]
        user_id=uuid7_uuid(),
        memory_item_ids=[],
        chunk_text="real text",
    )
    assert edges_empty_text == 0
    assert edges_no_mems == 0
    assert repo.inserted == []


def test_slugify_basics() -> None:
    assert slugify("Sarah") == "sarah"
    assert slugify("New York City") == "new-york-city"
    assert slugify("  Café-Bar  ") == "caf-bar"
    assert slugify("!!!") == "unnamed"
