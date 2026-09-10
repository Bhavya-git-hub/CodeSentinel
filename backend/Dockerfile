# API and worker image.
#
# This image runs *our* code. Target repositories are never analysed here -- that happens
# in the separate, network-less sandbox image (sandbox/Dockerfile.analysis), per C1.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# git is needed at runtime by GitPython for phase 3 cloning.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

# Dependencies are resolved from pyproject in their own layer, so a source change does
# not invalidate the dependency cache.
#
# Deliberately not installed from a committed lock file: a `pip freeze` taken on Windows
# pins pywin32 (which has no Linux distribution) and omits the Linux-only uvloop and
# httptools that uvicorn[standard] pulls, so it would both fail to build and silently
# under-install. CI publishes the resolved Linux versions as an artifact instead.
# See docs/adr/0008-dependency-pinning.md.
COPY pyproject.toml ./
RUN pip install .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-deps -e .

# Non-root: the API holds database credentials and, from phase 2, a handle on the Docker
# daemon. Neither belongs to uid 0.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
