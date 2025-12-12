from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException  # type: ignore[import-not-found]
from fastapi.responses import Response  # type: ignore[import-not-found]
from pydantic import BaseModel, Field  # type: ignore[import-not-found]


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice: str | None = None


app = FastAPI(title="Reflections TTS Bridge", version="0.1.0")


@app.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    """
    Host-run TTS bridge.

    Default implementation uses macOS `say` to synthesize speech, then converts
    to PCM16 WAV via `afconvert` so the browser can play it via WebAudio.

    Env vars:
    - TTS_VOICE: optional default voice name (macOS voices)
    """
    voice = req.voice or os.environ.get("TTS_VOICE")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        aiff_path = td_path / "out.aiff"
        wav_path = td_path / "out.wav"

        say_cmd = ["say", "-o", str(aiff_path)]
        if voice:
            say_cmd += ["-v", voice]
        say_cmd.append(req.text)

        proc = subprocess.run(say_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"say failed rc={proc.returncode}: {(proc.stderr or '')[:200]}",
            )

        # Convert to 16kHz mono PCM16 WAV
        conv_cmd = [
            "afconvert",
            "-f",
            "WAVE",
            "-d",
            "LEI16@16000",
            str(aiff_path),
            str(wav_path),
        ]
        proc2 = subprocess.run(conv_cmd, capture_output=True, text=True)
        if proc2.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"afconvert failed rc={proc2.returncode}: "
                    f"{(proc2.stderr or '')[:200]}"
                ),
            )

        wav_bytes = wav_path.read_bytes()
        return Response(content=wav_bytes, media_type="audio/wav")
