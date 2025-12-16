from reflections.health import service


async def test_get_health_payload_shape(anyio_backend: str) -> None:
    payload = await service.get_health_payload()
    assert payload["status"] in ("ok", "degraded", "error")
    assert isinstance(payload["ollama_base_url"], str)
    assert "db" in payload
