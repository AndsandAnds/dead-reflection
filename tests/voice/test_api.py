import base64

from fastapi.testclient import TestClient  # type: ignore[import-not-found]


def test_voice_ws_ready_and_cancel(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "ready"

        ws.send_json({"type": "cancel"})
        # Cancel emits cancelled (and may also emit done to ensure the UI can
        # exit "finalizing" state safely).
        msg = ws.receive_json()
        assert msg["type"] in {"cancelled", "done"}
        if msg["type"] == "done":
            msg = ws.receive_json()
        assert msg["type"] == "cancelled"
        # Drain any trailing "done" from cancel.
        msg2 = ws.receive_json()
        assert msg2["type"] in {"done", "error"}

        ws.send_text("not-json")
        # Next message should be an error (ignore any straggler done).
        msg = ws.receive_json()
        if msg["type"] == "done":
            msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["message"] in {"invalid_json", "invalid_message"}


def test_voice_ws_binary_audio_emits_partial(client: TestClient, monkeypatch) -> None:
    # Make this test deterministic and fast: no real STT/Ollama/TTS calls.
    from reflections.voice import service as voice_service

    monkeypatch.setattr(voice_service.settings, "TTS_BASE_URL", None)

    class FastRepo(voice_service.VoiceRepository):
        async def transcribe_audio(self, *, sample_rate: int, pcm16le=None):  # type: ignore[override]
            return "hello world"

        async def stream_assistant_reply_chat(self, *, messages):  # type: ignore[override]
            yield "hi"
            yield "!"

        async def synthesize_tts_wav(self, *, text: str, voice=None):  # type: ignore[override]
            raise RuntimeError("tts disabled in unit test")

    monkeypatch.setattr(voice_service, "VoiceRepository", FastRepo)

    with client.websocket_connect("/ws/voice") as ws:
        _ = ws.receive_json()  # ready

        audio = b"\x00\x01" * 160  # small fake PCM16 frame
        ws.send_json({"type": "hello", "sample_rate": 16000})
        ws.send_bytes(audio)

        # We should get at least one partial transcript while recording.
        msg = ws.receive_json()
        assert msg["type"] == "partial_transcript"
        assert msg["bytes_received"] >= len(audio)

        ws.send_json({"type": "end"})
        seen: list[str] = []
        final_msg = None
        assistant_msg = None
        done = None

        # Drain up to N messages to account for optional extra messages.
        for _ in range(20):
            msg = ws.receive_json()
            mtype = str(msg.get("type"))
            seen.append(mtype)
            if mtype == "final_transcript":
                final_msg = msg
            elif mtype == "assistant_message":
                assistant_msg = msg
            elif mtype == "done":
                done = msg
                break

        assert final_msg is not None
        assert final_msg["text"] == "hello world"
        assert final_msg["bytes_received"] >= len(audio)

        assert assistant_msg is not None
        assert assistant_msg["text"] == "hi!"

        assert done is not None


def test_voice_ws_cancel_cancels_inflight_turn(client: TestClient, monkeypatch) -> None:
    import asyncio

    from reflections.voice import service as voice_service

    class SlowRepo(voice_service.VoiceRepository):
        async def stream_assistant_reply_chat(self, *, messages):  # type: ignore[override]
            await asyncio.sleep(2.0)
            yield "hello"

    monkeypatch.setattr(voice_service, "VoiceRepository", SlowRepo)

    with client.websocket_connect("/ws/voice") as ws:
        _ = ws.receive_json()  # ready
        ws.send_json({"type": "hello", "sample_rate": 16000})
        ws.send_bytes(b"\x00\x01" * 1600)

        ws.send_json({"type": "end"})
        ws.send_json({"type": "cancel"})

        seen: list[str] = []
        for _ in range(20):
            msg = ws.receive_json()
            seen.append(str(msg.get("type")))
            if msg.get("type") == "done" and "cancelled" in seen:
                break

        assert "cancelled" in seen
        assert "assistant_message" not in seen


def test_voice_ws_emits_tts_chunks_when_tts_configured(
    client: TestClient, monkeypatch
) -> None:
    # Deterministic test: enable TTS in settings and stub synthesize.
    from reflections.voice import service as voice_service

    monkeypatch.setattr(voice_service.settings, "TTS_BASE_URL", "http://example")

    class TtsRepo(voice_service.VoiceRepository):
        async def transcribe_audio(self, *, sample_rate: int, pcm16le=None):  # type: ignore[override]
            return "hello"

        async def stream_assistant_reply_chat(self, *, messages):  # type: ignore[override]
            yield "hello "
            yield "there."

        async def synthesize_tts_wav(self, *, text: str, voice=None):  # type: ignore[override]
            # Dummy bytes; backend just base64-encodes.
            return b"RIFF....WAVE"

    monkeypatch.setattr(voice_service, "VoiceRepository", TtsRepo)

    with client.websocket_connect("/ws/voice") as ws:
        _ = ws.receive_json()  # ready
        ws.send_json({"type": "hello", "sample_rate": 16000})
        ws.send_bytes(b"\x00\x01" * 1600)
        ws.send_json({"type": "end"})

        seen_types: set[str] = set()
        for _ in range(50):
            msg = ws.receive_json()
            seen_types.add(str(msg.get("type")))
            if msg.get("type") == "done":
                break

        assert "tts_chunk" in seen_types


def test_voice_ws_legacy_base64_audio_frame_still_works(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        _ = ws.receive_json()  # ready

        audio = b"\x00\x01" * 160
        ws.send_json(
            {
                "type": "audio_frame",
                "sample_rate": 16000,
                "pcm16le_b64": base64.b64encode(audio).decode("ascii"),
            }
        )

        msg = ws.receive_json()
        assert msg["type"] == "partial_transcript"
        assert msg["bytes_received"] >= len(audio)
