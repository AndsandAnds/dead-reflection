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


def _piper_models_dir() -> Path | None:
    """
    Best-effort directory containing Piper .onnx models.

    Priority:
    - PIPER_MODELS_DIR (explicit)
    - parent directory of PIPER_MODEL (if set)
    """
    d = os.environ.get("PIPER_MODELS_DIR")
    if d:
        p = Path(d).expanduser()
        if p.exists() and p.is_dir():
            return p
    m = os.environ.get("PIPER_MODEL")
    if m:
        mp = Path(m).expanduser()
        parent = mp.parent
        if parent.exists() and parent.is_dir():
            return parent
    return None


def _discover_piper_voices() -> list[str]:
    """
    Return model identifiers (filenames without extension) for all .onnx files
    in the models directory.
    """
    d = _piper_models_dir()
    if not d:
        return []
    return [p.stem for p in sorted(d.glob("*.onnx"))]


def _resolve_piper_model_path(voice: str | None, default_model: str | None) -> str | None:
    """
    Resolve the Piper model path to use.

    - If voice looks like a path (contains "/" or endswith ".onnx"), use it if it exists.
    - Otherwise, treat voice as a model id and look it up in the models dir.
    - Fall back to default_model.
    """
    if voice:
        v = voice.strip()
        if v and not v.isdigit():
            vp = Path(v).expanduser()
            if "/" in v or v.endswith(".onnx"):
                if vp.exists() and vp.is_file():
                    return str(vp)
            d = _piper_models_dir()
            if d:
                cand = (d / f"{v}.onnx").expanduser()
                if cand.exists() and cand.is_file():
                    return str(cand)
                cand2 = (d / v).expanduser()
                if cand2.exists() and cand2.is_file() and cand2.suffix == ".onnx":
                    return str(cand2)
    if default_model:
        dp = Path(default_model).expanduser()
        return str(dp)
    return None


@app.get("/voices")
async def voices() -> dict:
    """
    List available voice options for the configured engine.
    """
    engine = (os.environ.get("TTS_ENGINE") or "say").strip().lower()
    if engine == "piper":
        return {"engine": "piper", "voices": _discover_piper_voices()}
    return {"engine": engine, "voices": []}


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
            model_path = _resolve_piper_model_path(voice, piper_model)
            if not model_path:
                raise HTTPException(
                    status_code=400,
                    detail="PIPER_MODEL (or resolvable voice model) is required when TTS_ENGINE=piper",
                )
            cmd = [
                piper_bin,
                "--model",
                str(model_path),
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
