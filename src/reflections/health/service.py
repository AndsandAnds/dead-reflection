from __future__ import annotations

from reflections.health import repository


async def get_health_payload() -> dict:
    db_ok, db_detail = await repository.check_db()
    ollama_ok, ollama_detail = await repository.check_ollama()
    stt_ok, stt_detail = await repository.check_stt()
    tts_ok, tts_detail = await repository.check_tts()
    avatar_ok, avatar_detail = repository.check_avatar_image_engine()
    a1111_ok, a1111_detail = await repository.check_a1111()

    # Overall status: only DB is mandatory for the API to function.
    # Optional services can be down; we reflect that in the per-service checks.
    status = "ok" if db_ok else "error"

    return {
        "status": status,
        "ollama_base_url": repository.get_ollama_base_url(),
        "db": {
            "ok": db_ok,
            "configured": True,
            "detail": db_detail,
        },
        "ollama": {
            "ok": ollama_ok,
            "configured": True,
            "base_url": repository.settings.OLLAMA_BASE_URL,
            "detail": ollama_detail,
        },
        "stt": (
            {
                "ok": False,
                "configured": False,
                "base_url": None,
                "detail": "not_configured",
            }
            if not repository.settings.STT_BASE_URL
            else {
            "ok": stt_ok,
            "configured": True,
            "base_url": repository.settings.STT_BASE_URL,
            "detail": stt_detail,
            }
        ),
        "tts": (
            {
                "ok": False,
                "configured": False,
                "base_url": None,
                "detail": "not_configured",
            }
            if not repository.settings.TTS_BASE_URL
            else {
            "ok": tts_ok,
            "configured": True,
            "base_url": repository.settings.TTS_BASE_URL,
            "detail": tts_detail,
            }
        ),
        "avatar_image": (
            {
                "ok": a1111_ok,
                "configured": True,
                "base_url": repository.settings.A1111_BASE_URL,
                "detail": a1111_detail,
            }
            if (repository.settings.AVATAR_IMAGE_ENGINE or "").strip().lower() == "a1111"
            else {
                "ok": avatar_ok,
                "configured": True,
                "detail": avatar_detail,
            }
        ),
    }
