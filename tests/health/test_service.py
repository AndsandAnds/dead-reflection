from reflections.health import service


def test_get_health_payload_shape() -> None:
    payload = service.get_health_payload()
    assert payload["status"] == "ok"
    assert isinstance(payload["ollama_base_url"], str)
