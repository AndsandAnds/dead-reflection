from reflections.voice.repository import VoiceRepository


def test_voice_repository_ingest_audio_increments_bytes() -> None:
    repo = VoiceRepository()
    assert repo.bytes_received == 0
    repo.ingest_audio(b"\x00\x01\x02")
    assert repo.bytes_received == 3
