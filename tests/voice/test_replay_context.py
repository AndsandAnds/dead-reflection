from __future__ import annotations

from uuid import UUID


def test_voice_ws_replays_recent_context_into_llm_messages(client, monkeypatch):  # type: ignore[no-untyped-def]
    """
    Regression: on authenticated connect, voice WS should seed state.messages with
    a small replay window so the LLM sees prior context.
    """
    from reflections.voice import service as voice_service

    # Avoid real DB init.
    async def _init():  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(voice_service.database_manager, "initialize", _init)

    # Stub DB session context manager.
    class DummySession:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return object()

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(voice_service.database_manager, "session", lambda: DummySession())

    # Stub auth.
    class FakeUser:
        id = UUID("11111111-1111-1111-1111-111111111111")
        active_avatar_id = None

    class FakeAuthSvc:
        async def get_user_for_session_token(self, session, *, token):  # type: ignore[no-untyped-def]
            return FakeUser()

    monkeypatch.setattr(voice_service.AuthService, "create", lambda: FakeAuthSvc())

    # Stub conversation replay.
    class FakeConvSvc:
        async def load_recent_context(  # type: ignore[no-untyped-def]
            self, session, *, user_id, avatar_id, limit_turns=40
        ):
            assert str(user_id) == str(FakeUser.id)
            return (
                UUID("22222222-2222-2222-2222-222222222222"),
                [{"role": "assistant", "content": "previous context"}],
            )

    monkeypatch.setattr(voice_service, "get_conversations_service", lambda: FakeConvSvc())

    # Stub repo: assert replay is included in messages passed to LLM.
    class FastRepo(voice_service.VoiceRepository):
        async def transcribe_audio(self, *, sample_rate: int, pcm16le=None):  # type: ignore[override]
            return "hello"

        async def stream_assistant_reply_chat(self, *, messages):  # type: ignore[override]
            joined = " ".join(m.get("content", "") for m in messages)
            assert "previous context" in joined
            yield "ok"

    monkeypatch.setattr(voice_service, "VoiceRepository", FastRepo)

    # Exercise a minimal voice turn.
    with client.websocket_connect(
        "/ws/voice", headers={"cookie": "reflections_session=tok"}
    ) as ws:
        _ = ws.receive_json()  # ready
        ws.send_json({"type": "hello", "sample_rate": 16000})
        ws.send_bytes(b"\x00\x01" * 1600)
        ws.send_json({"type": "end"})
        for _ in range(50):
            msg = ws.receive_json()
            if msg.get("type") == "done":
                break


