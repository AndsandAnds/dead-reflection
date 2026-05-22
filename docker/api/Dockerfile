#
# Multi-stage Dockerfile (pattern-aligned with the reference project).
# We keep dependencies installed into the image (not inside /app) so mounting the
# repo into /app during development doesn't hide installed packages.
#

# Base image pinned by digest to immobilize against tag mutation. To refresh,
# `docker pull python:3.12-slim` and copy the printed Digest below (and the
# two other stages, which must match for layer reuse).
FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 AS build-stage

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry>=2.0.0,<3.0.0"

# Install deps first for better layer caching.
COPY pyproject.toml README.md /app/
COPY src /app/src

# Install base deps + ML extras (memory embeddings) inside the container.
RUN poetry install --no-ansi --extras ml


FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 AS dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime needs ffmpeg too (used by the video extractor).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy installed deps (system site-packages + scripts).
COPY --from=build-stage /usr/local /usr/local

# Copy source (will be overridden by bind-mount in docker-compose for dev).
COPY --from=build-stage /app /app

EXPOSE 8000


FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build-stage /usr/local /usr/local
COPY --from=build-stage /app /app

EXPOSE 8000


