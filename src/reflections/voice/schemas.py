from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field  # type: ignore[import-not-found]


class VoiceHello(BaseModel):
    type: Literal["hello"]
    sample_rate: int | None = None


class VoiceAudioFrame(BaseModel):
    type: Literal["audio_frame"]
    pcm16le_b64: str
    sample_rate: int | None = None


class VoiceCancel(BaseModel):
    type: Literal["cancel"]


class VoiceEnd(BaseModel):
    type: Literal["end"]


ClientMessage = Annotated[
    VoiceHello | VoiceAudioFrame | VoiceCancel | VoiceEnd,
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


class ServerTtsAudio(BaseModel):
    type: Literal["tts_audio"] = "tts_audio"
    wav_b64: str


class ServerDone(BaseModel):
    type: Literal["done"] = "done"


class ServerError(BaseModel):
    type: Literal["error"] = "error"
    message: str
