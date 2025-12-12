import base64

from fastapi.testclient import TestClient


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
