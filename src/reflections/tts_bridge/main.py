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
    - TTS_ENGINE: "say" (default) or "piper"
    - PIPER_BIN: path to piper binary (when TTS_ENGINE=piper)
    - PIPER_MODEL: path to piper .onnx model (when TTS_ENGINE=piper)
    - PIPER_SPEAKER: optional integer speaker id (when TTS_ENGINE=piper)
    """
    engine = (os.environ.get("TTS_ENGINE") or "say").strip().lower()
    voice = req.voice or os.environ.get("TTS_VOICE")
    piper_bin = os.environ.get("PIPER_BIN") or "piper"
    piper_model = os.environ.get("PIPER_MODEL")
    piper_speaker = os.environ.get("PIPER_SPEAKER")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        aiff_path = td_path / "out.aiff"
        piper_wav_path = td_path / "piper.wav"
        wav_path = td_path / "out.wav"

        if engine == "piper":
            if not piper_model:
                raise HTTPException(
                    status_code=400,
                    detail="PIPER_MODEL is required when TTS_ENGINE=piper",
                )
            cmd = [
                piper_bin,
                "--model",
                str(piper_model),
                "--output_file",
                str(piper_wav_path),
            ]
            # If voice is a number, treat it as speaker id override.
            speaker = None
            if voice and voice.strip().isdigit():
                speaker = voice.strip()
            elif piper_speaker and str(piper_speaker).strip().isdigit():
                speaker = str(piper_speaker).strip()
            if speaker:
                cmd += ["--speaker", speaker]

            proc = subprocess.run(
                cmd,
                input=req.text,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"piper failed rc={proc.returncode}: "
                        f"{(proc.stderr or '')[:200]}"
                    ),
                )
        else:
            say_cmd = ["say", "-o", str(aiff_path)]
            if voice:
                say_cmd += ["-v", voice]
            say_cmd.append(req.text)

            proc = subprocess.run(say_cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"say failed rc={proc.returncode}: {(proc.stderr or '')[:200]}"
                    ),
                )

        # Convert to 16kHz mono PCM16 WAV
        src_path = piper_wav_path if engine == "piper" else aiff_path
        conv_cmd = [
            "afconvert",
            "-f",
            "WAVE",
            "-d",
            "LEI16@16000",
            str(src_path),
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
