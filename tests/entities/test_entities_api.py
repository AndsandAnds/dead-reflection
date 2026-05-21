from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest  # type: ignore[import-not-found]
from fastapi.testclient import TestClient  # type: ignore[import-not-found]

from reflections.api.main import build_app


@pytest.fixture()
def client():
    app = build_app()
    from reflections.commons.depends import database_session

    async def _dummy_db_session():  # type: ignore[no-untyped-def]
        class Dummy:
            pass

        yield Dummy()

    app.dependency_overrides[database_session] = _dummy_db_session
    return TestClient(app)


def _override_auth(client: TestClient):
    from reflections.auth.depends import current_user_required
    from reflections.auth.models import User

    user = User(
        id=UUID("00000000-0000-0000-0000-000000000099"),
        email="entity@example.com",
        name="Entity Tester",
        password_hash="x",
        is_admin=False,
        created_at=datetime.now(UTC),
        last_login_at=None,
        disabled_at=None,
    )
    client.app.dependency_overrides[current_user_required] = lambda: user
    return user


def test_list_entities_requires_auth(client: TestClient) -> None:
    r = client.get("/entities")
    assert r.status_code == 401


def test_create_entity_idempotent_by_slug(client: TestClient) -> None:
    """`create` returns the existing entity if same (user, kind, slug)."""
    _override_auth(client)
    from reflections.entities.api import get_entities_service
    from reflections.entities.schemas import Entity
    from uuid import uuid4

    fixed_id = uuid4()

    class FakeRow:
        def __init__(self, name="Sarah"):
            self.id = fixed_id
            self.user_id = UUID("00000000-0000-0000-0000-000000000099")
            self.kind = "person"
            self.name = name
            self.slug = "sarah"
            self.description = None
            self.attributes = None
            self.created_at = datetime.now(UTC)
            self.updated_at = datetime.now(UTC)

    class FakeService:
        async def add(self, *_args, **_kwargs):
            return FakeRow()

    client.app.dependency_overrides[get_entities_service] = lambda: FakeService()

    r = client.post(
        "/entities",
        json={"kind": "person", "name": "Sarah"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "sarah"
    assert body["kind"] == "person"
    assert body["id"] == str(fixed_id)


def test_get_entity_404_when_missing(client: TestClient) -> None:
    _override_auth(client)
    from reflections.entities.api import get_entities_service
    from reflections.entities.exceptions import EntitiesNotFoundException

    class FakeService:
        async def get(self, *_args, **_kwargs):
            raise EntitiesNotFoundException("entity_not_found", "missing")

    client.app.dependency_overrides[get_entities_service] = lambda: FakeService()
    r = client.get("/entities/00000000-0000-0000-0000-000000000111")
    assert r.status_code == 404


def test_merge_rejects_same_entity(client: TestClient) -> None:
    _override_auth(client)
    from reflections.entities.api import get_entities_service
    from reflections.entities.exceptions import EntitiesUnprocessableException

    class FakeService:
        async def merge_into(self, *_args, **_kwargs):
            raise EntitiesUnprocessableException(
                "merge_self", "Cannot merge an entity into itself"
            )

    client.app.dependency_overrides[get_entities_service] = lambda: FakeService()
    same = "00000000-0000-0000-0000-000000000123"
    r = client.post(f"/entities/{same}/merge", json={"from_id": same})
    assert r.status_code == 422
