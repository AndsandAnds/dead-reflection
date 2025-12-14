import pytest  # type: ignore[import-not-found]
from httpx import AsyncClient  # type: ignore[import-not-found]
from uuid6 import uuid7  # type: ignore[import-not-found]


@pytest.mark.anyio
async def test_memory_ingest_smoke(memory_async_client: AsyncClient) -> None:
    # Must match FakeUser injected by tests/memory/conftest.py
    user_id = "00000000-0000-0000-0000-000000000001"
    avatar_id = str(uuid7())
    resp = await memory_async_client.post(
        "/memory/ingest",
        json={
            "user_id": user_id,
            "avatar_id": avatar_id,
            "turns": [{"role": "user", "content": "Hello"}],
            "chunk_turn_window": 6,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stored_cards"] >= 0
    assert data["stored_chunks"] >= 0


@pytest.mark.anyio
async def test_memory_delete_smoke(memory_async_client: AsyncClient) -> None:
    # Must match FakeUser injected by tests/memory/conftest.py
    user_id = "00000000-0000-0000-0000-000000000001"
    resp = await memory_async_client.post(
        "/memory/delete",
        json={"user_id": user_id, "ids": [str(uuid7()), str(uuid7())]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 2
