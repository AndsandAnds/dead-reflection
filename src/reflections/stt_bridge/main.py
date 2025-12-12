from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel


class TranscribeResponse(BaseModel):
    text: str


app = FastAPI(title="Reflections STT Bridge", version="0.1.0")


_TS_RE = re.compile(r"^\\[[0-9:.]+\\s+-->\\s+[0-9:.]+\\]\\s*")


def _clean_whisper_stdout(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        s = _TS_RE.sub("", s).strip()
        if s:
            lines.append(s)
    return " ".join(lines).strip()


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: Annotated[UploadFile, File(...)]) -> TranscribeResponse:
    """
    Host-run whisper.cpp bridge.

    This is designed to run on macOS so whisper.cpp can use Metal acceleration.
    Expected env vars:
    - WHISPER_CPP_BIN: path to whisper.cpp binary (default: whisper-cli)
    - WHISPER_CPP_MODEL: path to ggml/gguf whisper model
    """
    whisper_bin = os.environ.get("WHISPER_CPP_BIN", "whisper-cli")
    model_path = os.environ.get("WHISPER_CPP_MODEL")
    if not model_path:
        raise HTTPException(
            status_code=400, detail="WHISPER_CPP_MODEL env var is required"
        )

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        in_wav = td_path / "audio.wav"
        out_base = td_path / "out"
        in_wav.write_bytes(data)

        # whisper.cpp writes transcription to stdout, and optionally to files.
        # We rely on stdout to avoid parsing timestamps from SRT/VTT.
        cmd = [
            whisper_bin,
            "-m",
            str(model_path),
            "-f",
            str(in_wav),
            "-nt",  # no timestamps (supported by whisper.cpp CLI)
            "-pp",  # print progress? harmless if ignored
            "-of",
            str(out_base),
        ]

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=500, detail=f"WHISPER_CPP_BIN not found: {whisper_bin}"
            ) from exc

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"whisper.cpp failed rc={proc.returncode}: {stderr[:200]}",
            )

        cleaned = _clean_whisper_stdout(stdout)
        if cleaned:
            return TranscribeResponse(text=cleaned)

        # Fallback: read generated txt file if present.
        txt_path = out_base.with_suffix(".txt")
        if txt_path.exists():
            return TranscribeResponse(text=txt_path.read_text().strip())

        raise HTTPException(status_code=500, detail="No transcription produced")
