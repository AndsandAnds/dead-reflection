from fastapi.testclient import TestClient

from reflections.api.main import build_app


def test_build_app_includes_health_route() -> None:
    app = build_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
