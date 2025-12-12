from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VoiceRepository:
    """Data layer for voice session (MVP stub).

    In the real implementation this will call a host STT service (whisper.cpp+Metal).
    """

    bytes_received: int = 0

    def ingest_audio(self, audio_bytes: bytes) -> int:
        self.bytes_received += len(audio_bytes)
        # "flush" concept for DB doesn't apply here; we still keep this layer dumb.
        return self.bytes_received
