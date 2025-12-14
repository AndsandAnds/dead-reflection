from __future__ import annotations

from uuid import UUID

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
    OLLAMA_MODEL: str
    OLLAMA_TIMEOUT_S: float = 30.0

    # Speech-to-text (recommended: host-run whisper.cpp bridge for Metal)
    STT_BASE_URL: str | None = None
    STT_TIMEOUT_S: float = 120.0

    # Text-to-speech (recommended: host-run bridge on macOS)
    TTS_BASE_URL: str | None = None
    TTS_TIMEOUT_S: float = 30.0

    # Identity defaults (until the user/avatar system is fully implemented)
    DEFAULT_USER_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")
    DEFAULT_AVATAR_ID: UUID | None = UUID("00000000-0000-0000-0000-000000000002")

    # Memory integration
    MEMORY_AUTO_INGEST: bool = True
    MEMORY_CHUNK_TURN_WINDOW: int = 2

    # Auth (HTTP-only cookie session)
    AUTH_COOKIE_NAME: str = "reflections_session"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"  # lax|strict|none
    AUTH_SESSION_TTL_DAYS: int = 30


settings = Settings()
