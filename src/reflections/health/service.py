from __future__ import annotations

from reflections.health import repository


def get_health_payload() -> dict[str, str]:
    return {"status": "ok", "ollama_base_url": repository.get_ollama_base_url()}
