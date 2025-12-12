from __future__ import annotations

from pydantic_settings import (  # type: ignore[import-not-found]
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """
    App settings.

    Loads from environment variables and an optional local `.env` file.
    `.env` is gitignored.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    API_TITLE: str = "Reflections API"
    API_VERSION: str = "0.1.0"

    # Database (Docker Compose)
    REFLECTIONS_DB_HOST: str
    REFLECTIONS_DB_PORT: int
    REFLECTIONS_DB_NAME: str
    REFLECTIONS_DB_USER: str
    REFLECTIONS_DB_PASSWORD: str

    # Local model runtime (host-installed Ollama on Apple Silicon recommended)
    OLLAMA_BASE_URL: str


settings = Settings()
