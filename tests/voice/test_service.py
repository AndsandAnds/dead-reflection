from reflections.voice import service


def test_build_ready_message() -> None:
    assert service.build_ready_message().model_dump() == {"type": "ready"}


def test_build_cancelled_message() -> None:
    assert service.build_cancelled_message().model_dump() == {"type": "cancelled"}


def test_build_partial_transcript_message() -> None:
    msg = service.build_partial_transcript_message(bytes_received=123, duration_s=0.5)
    payload = msg.model_dump()
    assert payload["type"] == "partial_transcript"
    assert payload["bytes_received"] == 123
    assert "0.50" in payload["text"]
