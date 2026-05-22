from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field  # type: ignore[import-not-found]


class VoiceHello(BaseModel):
    type: Literal["hello"]
    sample_rate: int | None = None
    # Optional TTS voice identifier (engine-specific). If omitted, server uses its default.
    voice: str | None = None


class VoiceAudioFrame(BaseModel):
    type: Literal["audio_frame"]
    pcm16le_b64: str
    sample_rate: int | None = None


class VoiceCancel(BaseModel):
    type: Literal["cancel"]


class VoiceEnd(BaseModel):
    type: Literal["end"]


class VoiceTextUtterance(BaseModel):
    """Direct text input — bypasses STT entirely.

    Used when the user types instead of speaks. The server runs the same
    agent turn loop (LLM stream + TTS + persist + memory) using `text`
    as the user message, and emits the usual `final_transcript` /
    `assistant_*` / `done` events so the UI can render it identically.
    """

    type: Literal["text_utterance"]
    text: str = Field(..., min_length=1, max_length=8000)


ClientMessage = Annotated[
    VoiceHello | VoiceAudioFrame | VoiceCancel | VoiceEnd | VoiceTextUtterance,
    Field(discriminator="type"),
]


class ServerReady(BaseModel):
    type: Literal["ready"] = "ready"


class ServerCancelled(BaseModel):
    type: Literal["cancelled"] = "cancelled"


class ServerPartialTranscript(BaseModel):
    type: Literal["partial_transcript"] = "partial_transcript"
    text: str
    bytes_received: int


class ServerFinalTranscript(BaseModel):
    type: Literal["final_transcript"] = "final_transcript"
    text: str
    bytes_received: int
    duration_s: float


class ServerAssistantMessage(BaseModel):
    type: Literal["assistant_message"] = "assistant_message"
    text: str


class ServerAssistantDelta(BaseModel):
    type: Literal["assistant_delta"] = "assistant_delta"
    delta: str


class ServerTtsAudio(BaseModel):
    type: Literal["tts_audio"] = "tts_audio"
    wav_b64: str


class ServerTtsChunk(BaseModel):
    type: Literal["tts_chunk"] = "tts_chunk"
    seq: int
    wav_b64: str
    is_last: bool = False


class ServerDone(BaseModel):
    type: Literal["done"] = "done"


class ServerError(BaseModel):
    type: Literal["error"] = "error"
    message: str
    # Backwards-compatible structured error fields for UI and tooling.
    code: str | None = None
    details: dict | None = None
