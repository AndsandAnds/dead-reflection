from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID


def test_conversations_list_smoke(client):  # type: ignore[no-untyped-def]
    # Arrange: authenticated user
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    # Arrange: stub DB session dependency
    from reflections.commons import depends as commons_depends

    async def fake_db_session():  # type: ignore[no-untyped-def]
        yield None

    client.app.dependency_overrides[commons_depends.database_session] = fake_db_session

    # Arrange: stub conversations service
    from reflections.conversations import api as conversations_api

    class FakeConv:
        id = UUID("22222222-2222-2222-2222-222222222222")
        user_id = FakeUser.id
        avatar_id = None
        created_at = datetime.now(timezone.utc)
        updated_at = created_at

    class FakeSvc:
        async def list_conversations(self, session, *, user, limit, offset):  # type: ignore[no-untyped-def]
            assert str(user.id) == str(FakeUser.id)
            assert limit == 50
            assert offset == 0
            return [FakeConv()]

    client.app.dependency_overrides[conversations_api.get_conversations_service] = (
        lambda: FakeSvc()
    )

    # Act
    r = client.get("/conversations")

    # Assert
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("items"), list)
    assert data["items"][0]["id"] == str(FakeConv.id)


def test_conversations_get_not_found(client):  # type: ignore[no-untyped-def]
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    from reflections.commons import depends as commons_depends

    async def fake_db_session():  # type: ignore[no-untyped-def]
        yield None

    client.app.dependency_overrides[commons_depends.database_session] = fake_db_session

    from reflections.conversations import api as conversations_api
    from reflections.conversations.exceptions import (
        CONVERSATION_NOT_FOUND,
        ConversationsServiceException,
    )

    class FakeSvc:
        async def get_conversation(self, session, *, user, conversation_id):  # type: ignore[no-untyped-def]
            raise ConversationsServiceException("nope", CONVERSATION_NOT_FOUND)

    client.app.dependency_overrides[conversations_api.get_conversations_service] = (
        lambda: FakeSvc()
    )

    r = client.get("/conversations/33333333-3333-3333-3333-333333333333")
    assert r.status_code == 404


def test_conversations_recent_returns_turns(client):  # type: ignore[no-untyped-def]
    """GET /conversations/recent surfaces the same tail that the WS
    server uses for replay, so /voice can hydrate on mount."""
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")
        active_avatar_id = None

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    from reflections.commons import depends as commons_depends

    async def fake_db_session():  # type: ignore[no-untyped-def]
        yield None

    client.app.dependency_overrides[commons_depends.database_session] = fake_db_session

    from reflections.conversations import api as conversations_api

    captured_kwargs: dict = {}

    class FakeSvc:
        async def load_recent_context(  # type: ignore[no-untyped-def]
            self, session, *, user_id, avatar_id, limit_turns
        ):
            captured_kwargs["user_id"] = user_id
            captured_kwargs["avatar_id"] = avatar_id
            captured_kwargs["limit_turns"] = limit_turns
            return (
                UUID("22222222-2222-2222-2222-222222222222"),
                [
                    {"role": "user", "content": "what's my haircut appointment?"},
                    {"role": "assistant", "content": "Tuesday at 3pm with Levin."},
                ],
            )

    client.app.dependency_overrides[conversations_api.get_conversations_service] = (
        lambda: FakeSvc()
    )

    r = client.get("/conversations/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == "22222222-2222-2222-2222-222222222222"
    assert [t["role"] for t in body["turns"]] == ["user", "assistant"]
    assert body["turns"][1]["content"] == "Tuesday at 3pm with Levin."
    # The endpoint must forward the active avatar so per-avatar history
    # isn't cross-contaminated.
    assert captured_kwargs["user_id"] == FakeUser.id
    assert captured_kwargs["avatar_id"] is None
    assert captured_kwargs["limit_turns"] == 40


def test_conversations_recent_empty_when_no_history(client):  # type: ignore[no-untyped-def]
    """Fresh accounts return an empty payload, not a 404."""
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")
        active_avatar_id = None

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    from reflections.commons import depends as commons_depends

    async def fake_db_session():  # type: ignore[no-untyped-def]
        yield None

    client.app.dependency_overrides[commons_depends.database_session] = fake_db_session

    from reflections.conversations import api as conversations_api

    class FakeSvc:
        async def load_recent_context(  # type: ignore[no-untyped-def]
            self, session, *, user_id, avatar_id, limit_turns
        ):
            return (None, [])

    client.app.dependency_overrides[conversations_api.get_conversations_service] = (
        lambda: FakeSvc()
    )

    r = client.get("/conversations/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] is None
    assert body["turns"] == []


