from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest  # type: ignore[import-not-found]
from fastapi.testclient import TestClient  # type: ignore[import-not-found]

from reflections.api.main import build_app


@pytest.fixture()
def client():
    app = build_app()
    # Prevent tests from touching a real Postgres instance.
    from reflections.commons.depends import database_session

    async def _dummy_db_session():  # type: ignore[no-untyped-def]
        class Dummy:
            pass

        yield Dummy()

    app.dependency_overrides[database_session] = _dummy_db_session
    return TestClient(app)


def test_auth_me_unauthorized(client: TestClient) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_auth_login_sets_cookie_and_me_works(monkeypatch, client: TestClient) -> None:
    # Patch auth dependency to return a fake user when cookie is present.
    from reflections.auth.depends import get_auth_service
    from reflections.auth.models import User

    fake_user = User(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="test@example.com",
        name="Test User",
        password_hash="x",
        is_admin=False,
        created_at=datetime.now(UTC),
        last_login_at=None,
        disabled_at=None,
    )

    class FakeAuthService:
        async def login(self, session, *, email: str, password: str):  # type: ignore[no-untyped-def]
            return fake_user, "tok123"

        async def get_user_for_session_token(self, session, *, token: str):  # type: ignore[no-untyped-def]
            if token == "tok123":
                return fake_user
            return None

        async def logout(self, session, *, token: str):  # type: ignore[no-untyped-def]
            return None

    # Override the FastAPI dependency used by routes.
    client.app.dependency_overrides[get_auth_service] = lambda: FakeAuthService()

    r = client.post("/auth/login", json={"email": "test@example.com", "password": "pw"})
    assert r.status_code == 200
    assert "set-cookie" in {k.lower() for k in r.headers.keys()}

    r2 = client.get("/auth/me")
    assert r2.status_code == 200
    data = r2.json()
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["is_admin"] is False


def test_auth_me_surfaces_is_admin_true(client: TestClient) -> None:
    from reflections.auth.depends import current_user_required
    from reflections.auth.models import User

    admin = User(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        email="admin@example.com",
        name="Admin",
        password_hash="x",
        is_admin=True,
        created_at=datetime.now(UTC),
        last_login_at=None,
        disabled_at=None,
    )
    client.app.dependency_overrides[current_user_required] = lambda: admin
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["is_admin"] is True


def test_admin_required_403_for_non_admin(client: TestClient) -> None:
    from fastapi import Depends  # type: ignore[import-not-found]

    from reflections.auth.depends import current_admin_required, current_user_required
    from reflections.auth.models import User

    non_admin = User(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        email="user@example.com",
        name="User",
        password_hash="x",
        is_admin=False,
        created_at=datetime.now(UTC),
        last_login_at=None,
        disabled_at=None,
    )
    client.app.dependency_overrides[current_user_required] = lambda: non_admin

    @client.app.get("/_test/admin-only")
    async def _admin_only(user=Depends(current_admin_required)):  # type: ignore[no-untyped-def]
        return {"ok": True}

    try:
        r = client.get("/_test/admin-only")
        assert r.status_code == 403
    finally:
        # Best-effort cleanup so the test route doesn't leak across tests.
        client.app.dependency_overrides.pop(current_user_required, None)


def test_admin_required_200_for_admin(client: TestClient) -> None:
    from fastapi import Depends  # type: ignore[import-not-found]

    from reflections.auth.depends import current_admin_required, current_user_required
    from reflections.auth.models import User

    admin = User(
        id=UUID("00000000-0000-0000-0000-000000000004"),
        email="admin2@example.com",
        name="Admin2",
        password_hash="x",
        is_admin=True,
        created_at=datetime.now(UTC),
        last_login_at=None,
        disabled_at=None,
    )
    client.app.dependency_overrides[current_user_required] = lambda: admin

    @client.app.get("/_test/admin-only-2")
    async def _admin_only_2(user=Depends(current_admin_required)):  # type: ignore[no-untyped-def]
        return {"ok": True}

    try:
        r = client.get("/_test/admin-only-2")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
    finally:
        client.app.dependency_overrides.pop(current_user_required, None)
