"""
Tests for the Phase 2 additions to the memory API:
  - search filters (entity_ids, date_from, date_to) accepted + forwarded
  - search/inspect responses now include `linked_entities`
  - PATCH /memory/{id} for inline edit
  - GET /memory/graph returns nodes + edges in the prefixed shape
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID

import pytest  # type: ignore[import-not-found]
from httpx import AsyncClient  # type: ignore[import-not-found]
from uuid6 import uuid7  # type: ignore[import-not-found]

from reflections.memory import api as memory_api
from reflections.memory.repository import LinkedEntityRow, MemoryRow

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_row(content: str, kind: str = "card") -> MemoryRow:
    return MemoryRow(
        id=uuid7(),
        user_id=USER_ID,
        avatar_id=None,
        scope="user",
        kind=kind,  # type: ignore[arg-type]
        content=content,
        created_at=dt.datetime(2026, 5, 21, tzinfo=dt.UTC),
    )


class _CapturingSvc:
    """Records kwargs to `search` so we can assert the API forwarded them."""

    def __init__(self) -> None:
        self.search_kwargs: dict | None = None
        self.linked_lookups: list[list[UUID]] = []
        self.update_calls: list[tuple[UUID, str]] = []
        self.update_result_row: MemoryRow | None = None
        self.graph_returns: tuple[
            list[MemoryRow], list[LinkedEntityRow], list[tuple]
        ] = ([], [], [])

    async def search(self, _session, **kwargs):
        self.search_kwargs = kwargs
        return []

    async def get_linked_entities(self, _session, *, user_id, memory_ids):
        self.linked_lookups.append(list(memory_ids))
        return {mid: [] for mid in memory_ids}

    async def update_content(
        self, _session, *, user_id, memory_id, content
    ) -> MemoryRow:
        self.update_calls.append((memory_id, content))
        if self.update_result_row is None:
            raise AssertionError("test forgot to set update_result_row")
        return self.update_result_row

    async def get_graph(self, _session, **_kwargs):
        return self.graph_returns


@pytest.mark.anyio
async def test_search_accepts_and_forwards_new_filters(
    memory_app, memory_async_client: AsyncClient
) -> None:
    svc = _CapturingSvc()
    memory_app.dependency_overrides[memory_api.get_memory_service] = lambda: svc

    entity_id = str(uuid7())
    payload = {
        "user_id": str(USER_ID),
        "query": "coffee",
        "top_k": 5,
        "entity_ids": [entity_id],
        "date_from": "2026-01-01T00:00:00+00:00",
        "date_to": "2026-12-31T00:00:00+00:00",
    }
    resp = await memory_async_client.post("/memory/search", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}
    kw = svc.search_kwargs
    assert kw is not None
    assert kw["entity_ids"] == [UUID(entity_id)]
    assert kw["date_from"].year == 2026 and kw["date_from"].month == 1
    assert kw["date_to"].year == 2026 and kw["date_to"].month == 12


@pytest.mark.anyio
async def test_search_response_includes_linked_entities(
    memory_app, memory_async_client: AsyncClient
) -> None:
    svc = _CapturingSvc()
    row = _make_row("I love Yirgacheffe")
    sarah_id = uuid7()

    async def search(_session, **_kwargs):
        return [row]

    async def get_linked(_session, *, user_id, memory_ids):
        return {
            row.id: [
                LinkedEntityRow(
                    id=sarah_id, kind="person", name="Sarah", slug="sarah"
                )
            ]
        }

    svc.search = search  # type: ignore[assignment]
    svc.get_linked_entities = get_linked  # type: ignore[assignment]
    memory_app.dependency_overrides[memory_api.get_memory_service] = lambda: svc

    resp = await memory_async_client.post(
        "/memory/search",
        json={"user_id": str(USER_ID), "query": "coffee"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["linked_entities"] == [
        {
            "id": str(sarah_id),
            "kind": "person",
            "name": "Sarah",
            "slug": "sarah",
        }
    ]


@pytest.mark.anyio
async def test_patch_memory_returns_updated_item(
    memory_app, memory_async_client: AsyncClient
) -> None:
    svc = _CapturingSvc()
    new_row = _make_row("Updated content goes here")
    svc.update_result_row = new_row
    memory_app.dependency_overrides[memory_api.get_memory_service] = lambda: svc

    resp = await memory_async_client.patch(
        f"/memory/{new_row.id}",
        json={"content": "Updated content goes here"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(new_row.id)
    assert body["content"] == "Updated content goes here"
    assert body["linked_entities"] == []
    assert svc.update_calls == [(new_row.id, "Updated content goes here")]


@pytest.mark.anyio
async def test_patch_memory_rejects_empty_content(
    memory_app, memory_async_client: AsyncClient
) -> None:
    # Pydantic constraint min_length=1 should 422 before service is hit.
    resp = await memory_async_client.patch(
        f"/memory/{uuid7()}", json={"content": ""}
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_graph_shapes_prefixed_node_ids(
    memory_app, memory_async_client: AsyncClient
) -> None:
    svc = _CapturingSvc()
    m1 = _make_row("Sarah's birthday party", kind="chunk")
    sarah_id = uuid7()
    place_id = uuid7()
    svc.graph_returns = (
        [m1],
        [
            LinkedEntityRow(id=sarah_id, kind="person", name="Sarah", slug="sarah"),
            LinkedEntityRow(id=place_id, kind="place", name="Verve", slug="verve"),
        ],
        [(m1.id, sarah_id, ""), (m1.id, place_id, "")],
    )
    memory_app.dependency_overrides[memory_api.get_memory_service] = lambda: svc

    resp = await memory_async_client.get("/memory/graph")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["nodes"]) == 3  # 1 memory + 2 entities
    kinds = {n["kind"] for n in data["nodes"]}
    assert kinds == {"memory_chunk", "entity_person", "entity_place"}
    # All node ids are prefixed.
    assert all(n["id"].startswith(("memory:", "entity:")) for n in data["nodes"])

    assert len(data["edges"]) == 2
    for e in data["edges"]:
        assert e["source"].startswith("memory:")
        assert e["target"].startswith("entity:")
