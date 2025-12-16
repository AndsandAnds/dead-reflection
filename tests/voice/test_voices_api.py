from __future__ import annotations

from uuid import UUID


def test_voice_voices_returns_list(client):  # type: ignore[no-untyped-def]
    from reflections.auth.depends import current_user_required

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")

    client.app.dependency_overrides[current_user_required] = lambda: FakeUser()

    from reflections.voice import api as voice_api
    from reflections.voice.http_schemas import ListVoicesResponse

    class FakeSvc:
        async def list_voices(self):  # type: ignore[no-untyped-def]
            return ListVoicesResponse(engine="piper", configured=True, voices=["a", "b"])

    client.app.dependency_overrides[voice_api.get_voice_http_service] = lambda: FakeSvc()

    r = client.get("/voice/voices")
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is True
    assert data["engine"] == "piper"
    assert data["voices"] == ["a", "b"]


