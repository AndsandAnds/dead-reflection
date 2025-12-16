from __future__ import annotations

from uuid import UUID


def test_http_service_greet_degrades_when_tts_bridge_down():  # type: ignore[no-untyped-def]
    """
    Regression: /voice/greet should not 500 just because the host TTS bridge is down.
    """
    from reflections.core.settings import settings
    from reflections.voice.http_service import VoiceHttpService

    class FakeRepo:
        async def generate_assistant_reply_chat(self, *, messages):  # type: ignore[no-untyped-def]
            return "Hello, Once!"

        async def synthesize_tts_wav(self, *, text: str, voice=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("tts_unreachable")

        def wav_bytes_to_b64(self, wav_bytes: bytes) -> str:  # type: ignore[no-untyped-def]
            return "should_not_be_called"

    class FakeAvatarsRepo:
        async def get_for_user(self, session, *, user_id, avatar_id):  # type: ignore[no-untyped-def]
            return None

    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")
        name = "Once"
        active_avatar_id = None

    # Ensure code path tries TTS, but then fails and degrades gracefully.
    old = settings.TTS_BASE_URL
    settings.TTS_BASE_URL = "http://host.docker.internal:9002"
    try:
        svc = VoiceHttpService(repo=FakeRepo(), avatars_repo=FakeAvatarsRepo())
        resp = __import__("asyncio").run(svc.greet(None, user=FakeUser()))  # type: ignore[arg-type]
        assert resp.text
        assert resp.wav_b64 is None
    finally:
        settings.TTS_BASE_URL = old


