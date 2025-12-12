#
# Multi-stage Dockerfile (pattern-aligned with the reference project).
# We keep dependencies installed into the image (not inside /app) so mounting the
# repo into /app during development doesn't hide installed packages.
#

FROM python:3.12-slim AS build-stage

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry>=2.0.0,<3.0.0"

# Install deps first for better layer caching.
COPY pyproject.toml README.md /app/
COPY src /app/src

# Install base deps + ML extras (memory embeddings) inside the container.
RUN poetry install --no-ansi --extras ml


FROM python:3.12-slim AS dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy installed deps (system site-packages + scripts).
COPY --from=build-stage /usr/local /usr/local

# Copy source (will be overridden by bind-mount in docker-compose for dev).
COPY --from=build-stage /app /app

EXPOSE 8000


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY --from=build-stage /usr/local /usr/local
COPY --from=build-stage /app /app

EXPOSE 8000


