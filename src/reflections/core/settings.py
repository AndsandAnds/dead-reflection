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

    # Automatic1111 (Stable Diffusion Web UI) - optional local image generation
    A1111_BASE_URL: str | None = None
    A1111_TIMEOUT_S: float = 120.0

    # Avatar image generation engine
    # - a1111: Automatic1111 Web UI API
    # - diffusers_sdxl: Diffusers SDXL base (+ optional refiner) running in-process
    AVATAR_IMAGE_ENGINE: str = "a1111"

    # Diffusers SDXL (quality-first, local-only). Point these at local directories
    # or model IDs that are already present in the local HF cache.
    DIFFUSERS_SDXL_BASE_MODEL: str | None = None
    DIFFUSERS_SDXL_REFINER_MODEL: str | None = None
    DIFFUSERS_LOCAL_FILES_ONLY: bool = True
    # NOTE: Docker on macOS cannot use Metal/MPS. If running the API in Docker,
    # set device=cpu (or run a host bridge for MPS).
    DIFFUSERS_DEVICE: str = "cpu"  # apple silicon (host): mps; linux/nvidia: cuda; cpu: cpu
    DIFFUSERS_DTYPE: str = "float32"  # float16|float32
    DIFFUSERS_HIGH_NOISE_FRAC: float = 0.8
    DIFFUSERS_ENABLE_COMPILE: bool = False

    # Identity defaults (until the user/avatar system is fully implemented)
    DEFAULT_USER_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")
    DEFAULT_AVATAR_ID: UUID | None = UUID("00000000-0000-0000-0000-000000000002")

    # Memory integration
    MEMORY_AUTO_INGEST: bool = True
    MEMORY_CHUNK_TURN_WINDOW: int = 2

    # Auth (HTTP-only cookie session)
    AUTH_COOKIE_NAME: str
    AUTH_COOKIE_SECURE: bool
    AUTH_COOKIE_SAMESITE: str  # lax|strict|none
    AUTH_SESSION_TTL_DAYS: int

    # CORS (needed for browser UI on :3000 to call API on :8000 with cookies)
    # Include both hostnames since people often use either in the browser.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"


settings = Settings()
