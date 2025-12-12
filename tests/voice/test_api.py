import base64

from fastapi.testclient import TestClient  # type: ignore[import-not-found]


def test_voice_ws_ready_and_cancel(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "ready"

        ws.send_json({"type": "cancel"})
        msg = ws.receive_json()
        assert msg["type"] == "cancelled"


def test_voice_ws_audio_frame_emits_partial(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        _ = ws.receive_json()  # ready

        audio = b"\x00\x01" * 160  # small fake PCM16 frame
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

        ws.send_json({"type": "end"})
        # Depending on local env (.env), STT or Ollama may emit 'error' messages.
        # We assert the required messages arrive in-order relative to each other.
        final_msg = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg["type"] == "final_transcript":
                final_msg = msg
                break
        assert final_msg is not None
        assert final_msg["bytes_received"] >= len(audio)

        assistant_msg = None
        for _ in range(5):
            msg = ws.receive_json()
            if msg["type"] == "assistant_message":
                assistant_msg = msg
                break
        assert assistant_msg is not None
        assert isinstance(assistant_msg.get("text"), str)

        # Optional: TTS audio may be emitted if configured.
        # Always: a final "done" message should close out the turn.
        done = None
        for _ in range(10):
            msg = ws.receive_json()
            if msg["type"] == "done":
                done = msg
                break
        assert done is not None
