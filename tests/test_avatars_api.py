from __future__ import annotations

from uuid import UUID


def test_avatars_generate_image_updates_avatar(client, monkeypatch):  # type: ignore[no-untyped-def]
    # Arrange: authenticated user
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("00000000-0000-0000-0000-000000000001")
        active_avatar_id = None

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    # Arrange: stub DB session dependency
    from reflections.commons import depends as commons_depends

    async def fake_db_session():  # type: ignore[no-untyped-def]
        yield None

    client.app.dependency_overrides[commons_depends.database_session] = fake_db_session

    # Arrange: stub avatars service methods
    from reflections.avatars import api as avatars_api

    avatar_id = UUID("00000000-0000-0000-0000-000000000002")

    aid = avatar_id

    class FakeSvc:
        async def generate_image_a1111(  # type: ignore[no-untyped-def]
            self, session, *, user, avatar_id, **kwargs
        ):
            assert str(avatar_id) == str(aid)
            return "data:image/png;base64,AAA"

    client.app.dependency_overrides[avatars_api.get_avatars_service] = lambda: FakeSvc()

    # Act
    r = client.post(
        f"/avatars/{avatar_id}/generate-image",
        json={
            "prompt": "portrait of lumina",
            "negative_prompt": "blurry",
            "width": 512,
            "height": 512,
            "steps": 10,
            "cfg_scale": 7.0,
            "seed": -1,
        },
    )

    # Assert
    assert r.status_code == 200
    assert r.json()["image_url"].startswith("data:image/png;base64,")


