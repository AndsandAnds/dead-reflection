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


