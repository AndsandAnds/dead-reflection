from __future__ import annotations

from uuid import UUID


def test_voice_greet_returns_text_and_optional_wav(client):  # type: ignore[no-untyped-def]
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")
        name = "Once"
        active_avatar_id = None

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    from reflections.commons import depends as commons_depends

    async def fake_db_session():  # type: ignore[no-untyped-def]
        yield None

    client.app.dependency_overrides[commons_depends.database_session] = fake_db_session

    from reflections.voice import api as voice_api
    from reflections.voice.http_schemas import GreetResponse

    class FakeSvc:
        async def greet(self, session, *, user):  # type: ignore[no-untyped-def]
            assert user.name == "Once"
            return GreetResponse(text="Welcome back, Once.", wav_b64=None, voice=None)

    client.app.dependency_overrides[voice_api.get_voice_http_service] = lambda: FakeSvc()

    r = client.get("/voice/greet")
    assert r.status_code == 200
    data = r.json()
    assert "text" in data and "Once" in data["text"]

