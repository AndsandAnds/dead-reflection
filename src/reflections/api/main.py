from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI
from pydantic import BaseModel


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("REFLECTIONS_DB_HOST", "localhost")
    db_port: int = int(os.getenv("REFLECTIONS_DB_PORT", "5432"))
    db_name: str = os.getenv("REFLECTIONS_DB_NAME", "reflections")
    db_user: str = os.getenv("REFLECTIONS_DB_USER", "reflections")
    db_password: str = os.getenv("REFLECTIONS_DB_PASSWORD", "reflections")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


settings = Settings()

app = FastAPI(title="Reflections API", version="0.1.0")


class HealthResponse(BaseModel):
    status: str
    ollama_base_url: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", ollama_base_url=settings.ollama_base_url)
