from __future__ import annotations

from reflections.core.settings import settings


def get_ollama_base_url() -> str:
    return settings.OLLAMA_BASE_URL
