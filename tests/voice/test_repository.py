from reflections.voice.repository import VoiceRepository


def test_voice_repository_ingest_audio_increments_bytes() -> None:
    repo = VoiceRepository()
    assert repo.bytes_received == 0
    repo.ingest_audio(b"\x00\x01\x02")
    assert repo.bytes_received == 3


def test_voice_repository_resample_noop_when_already_16k() -> None:
    repo = VoiceRepository()
    pcm = b"\x00\x00" * 160
    out = repo._resample_to_target(pcm16le=pcm, sample_rate=16000)
    assert out == pcm


def test_voice_repository_resample_48k_to_16k_shortens_audio() -> None:
    # 48000 -> 16000 should reduce sample count by ~3x.
    repo = VoiceRepository()
    pcm = b"\x01\x00" * 4800  # 4800 samples (9600 bytes) ~= 0.1s at 48kHz
    out = repo._resample_to_target(pcm16le=pcm, sample_rate=48000)
    assert len(out) < len(pcm)
    # Rough tolerance: linear resampler rounding may vary by a few samples.
    assert abs(len(out) - len(pcm) // 3) < 32


def test_voice_repository_to_wav_bytes_always_uses_16k_header() -> None:
    import io
    import wave

    repo = VoiceRepository()
    pcm_48k = b"\x01\x00" * 4800
    wav_bytes = repo._to_wav_bytes(pcm16le=pcm_48k, sample_rate=48000)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
