from reflections.health import repository


def test_get_ollama_base_url_is_string() -> None:
    url = repository.get_ollama_base_url()
    assert isinstance(url, str)
    assert url
