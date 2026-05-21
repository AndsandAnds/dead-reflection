"""
Extractor unit tests. Each pipeline runs with mocked I/O — no real
catalog bridge, no real Ollama, no real STT bridge. We exercise the
data shapes the extraction service depends on.
"""

from __future__ import annotations

import io
from uuid import uuid4

import pytest  # type: ignore[import-not-found]

from reflections.extractors import audio as audio_extractor
from reflections.extractors import image as image_extractor
from reflections.extractors import pdf as pdf_extractor
from reflections.extractors.base import ArtifactMeta, ExtractionError
from reflections.extractors.dispatcher import dispatch, supported_kinds


# --- PDF ---------------------------------------------------------------------


def _make_pdf(pages_text: list[str]) -> bytes:
    """Build a tiny PDF from text using pypdf's writer."""
    from pypdf import PdfWriter  # type: ignore[import-not-found]
    from pypdf.generic import RectangleObject  # type: ignore[import-not-found]

    writer = PdfWriter()
    for text in pages_text:
        writer.add_blank_page(width=200, height=200)
    # pypdf's blank pages have no content stream → extract_text returns "".
    # That's fine for a "covers the empty-page skip path" test. For non-
    # empty pages we use reportlab if available, else fall back to a
    # pre-baked tiny PDF stored as a fixture in the test.
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_pdf_with_text(pages_text: list[str]) -> bytes:
    """Use reportlab if installed; otherwise fall back to the canonical
    one-page hello-world PDF byte fixture below."""
    try:
        from reportlab.pdfgen import canvas  # type: ignore[import-not-found]
    except ImportError:
        return _MINIMAL_HELLO_PDF
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in pages_text:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return buf.getvalue()


# A minimal valid PDF whose page 1 contains the literal text "hello
# world". Used as a fallback when reportlab isn't installed.
_MINIMAL_HELLO_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    b"5 0 obj\n<< /Length 44 >>\nstream\n"
    b"BT /F1 24 Tf 72 720 Td (hello world) Tj ET\nendstream\nendobj\n"
    b"xref\n"
    b"0 6\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000055 00000 n \n"
    b"0000000104 00000 n \n"
    b"0000000206 00000 n \n"
    b"0000000266 00000 n \n"
    b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n362\n%%EOF\n"
)


def _meta(kind: str, *, relative_path: str = "doc.bin", mime: str | None = None) -> ArtifactMeta:
    return ArtifactMeta(
        id=uuid4(),
        user_id=uuid4(),
        mount_path="/Volumes/Test",
        relative_path=relative_path,
        mime=mime,
        size_bytes=10,
        kind=kind,
    )


@pytest.mark.anyio
async def test_pdf_extracts_one_chunk_per_nonempty_page() -> None:
    blob = _make_pdf_with_text(["hello world"])

    async def read():
        return blob

    chunks = await pdf_extractor.extract(read, _meta("pdf", relative_path="doc.pdf"))
    assert len(chunks) == 1
    assert "hello world" in chunks[0].content
    assert chunks[0].locator["page"] == 1
    assert chunks[0].locator["total_pages"] == 1
    assert chunks[0].metadata["source_kind"] == "pdf"


@pytest.mark.anyio
async def test_pdf_skips_empty_pages() -> None:
    blob = _make_pdf(["", ""])  # blank pages, no text

    async def read():
        return blob

    chunks = await pdf_extractor.extract(read, _meta("pdf", relative_path="blank.pdf"))
    assert chunks == []


@pytest.mark.anyio
async def test_pdf_empty_bytes_raises() -> None:
    async def read():
        return b""

    with pytest.raises(ExtractionError):
        await pdf_extractor.extract(read, _meta("pdf"))


# --- Image -------------------------------------------------------------------


@pytest.mark.anyio
async def test_image_caption_via_mocked_ollama(monkeypatch) -> None:
    # Minimal valid 1x1 PNG.
    from base64 import b64decode

    blob = b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
    )

    class _MockResp:
        status_code = 200

        def json(self):
            return {"response": "A blank pixel."}

        text = ""

    class _MockClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_a, **_kw):
            return _MockResp()

    import reflections.extractors.image as img_mod

    monkeypatch.setattr(img_mod, "httpx", type("X", (), {
        "AsyncClient": _MockClient,
        "Timeout": lambda *a, **kw: None,
    }))

    async def read():
        return blob

    chunks = await image_extractor.extract(
        read, _meta("image", relative_path="x.png", mime="image/png"), ollama_url="http://x"
    )
    assert len(chunks) == 1
    assert chunks[0].content == "A blank pixel."
    assert chunks[0].metadata["source_kind"] == "image"
    # EXIF dict was at least populated with dimensions even for a 1x1.
    assert chunks[0].metadata["exif"]["width"] == 1


# --- Audio -------------------------------------------------------------------


@pytest.mark.anyio
async def test_audio_chunks_transcript_at_sentence_boundaries(monkeypatch) -> None:
    long = (
        "First sentence here. Second sentence here. Third sentence here. "
        "Fourth sentence here. Fifth sentence here. Sixth sentence here."
    )

    class _MockResp:
        status_code = 200

        def json(self):
            return {"text": long}

        text = ""

    class _MockClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_a, **_kw):
            return _MockResp()

    monkeypatch.setattr(audio_extractor, "httpx", type("X", (), {
        "AsyncClient": _MockClient,
        "Timeout": lambda *a, **kw: None,
    }))

    async def read():
        return b"fake-wav"

    chunks = await audio_extractor.extract(
        read,
        _meta("audio", relative_path="a.wav", mime="audio/wav"),
        stt_url="http://stt",
        chunk_char_target=80,
    )
    # Should split into multiple chunks (target was 80 chars).
    assert len(chunks) >= 2
    assert all(c.metadata["source_kind"] == "audio" for c in chunks)
    # All chunks together reconstruct the original (whitespace-collapsed).
    joined = " ".join(c.content for c in chunks)
    assert "First sentence" in joined
    assert "Sixth sentence" in joined


@pytest.mark.anyio
async def test_audio_errors_when_bridge_not_configured(monkeypatch) -> None:
    # Force STT_BASE_URL to None.
    from reflections.core.settings import settings

    monkeypatch.setattr(settings, "STT_BASE_URL", None)

    async def read():
        return b"x"

    with pytest.raises(ExtractionError):
        await audio_extractor.extract(read, _meta("audio"))


# --- Dispatcher --------------------------------------------------------------


@pytest.mark.anyio
async def test_dispatcher_rejects_unknown_kind() -> None:
    from reflections.extractors.base import UnsupportedArtifactError

    async def read():
        return b""

    with pytest.raises(UnsupportedArtifactError):
        await dispatch(meta=_meta("other"), read_bytes=read)


def test_dispatcher_reports_supported_kinds() -> None:
    kinds = supported_kinds()
    assert set(kinds) == {"pdf", "image", "audio", "video"}
