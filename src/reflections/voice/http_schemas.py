from __future__ import annotations

from pydantic import BaseModel, Field  # type: ignore[import-not-found]


class GreetResponse(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    wav_b64: str | None = None
    voice: str | None = None


