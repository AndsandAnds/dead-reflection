from fastapi import FastAPI
from fastapi.testclient import TestClient

from reflections.api.exceptions import configure_global_exception_handlers
from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


def test_base_service_exception_maps_to_400() -> None:
    app = FastAPI()
    configure_global_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise BaseServiceException("nope", "details")

    client = TestClient(app)
    r = client.get("/boom")
    assert r.status_code == 400
    assert r.json()["exception"]["message"] == "nope"


def test_not_found_exception_maps_to_404() -> None:
    app = FastAPI()
    configure_global_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise BaseServiceNotFoundException("missing")

    client = TestClient(app)
    r = client.get("/boom")
    assert r.status_code == 404


def test_unprocessable_exception_maps_to_422_content() -> None:
    app = FastAPI()
    configure_global_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise BaseServiceUnProcessableException("bad")

    client = TestClient(app)
    r = client.get("/boom")
    assert r.status_code == 422
