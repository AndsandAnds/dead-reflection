from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class VoiceHello(BaseModel):
    type: Literal["hello"]
    sample_rate: int | None = None


class VoiceAudioFrame(BaseModel):
    type: Literal["audio_frame"]
    pcm16le_b64: str
    sample_rate: int | None = None


class VoiceCancel(BaseModel):
    type: Literal["cancel"]


ClientMessage = Annotated[
    VoiceHello | VoiceAudioFrame | VoiceCancel,
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


class ServerError(BaseModel):
    type: Literal["error"] = "error"
    message: str
