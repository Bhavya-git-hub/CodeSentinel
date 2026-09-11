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
# The clone root has to exist in the IMAGE, owned by the user that will write to it.
#
# Docker seeds an empty named volume from whatever the image has at the mount point,
# ownership included. Without this the `clones` volume is created root:root 755, the
# worker runs as uid 10001, and the first scan dies with EACCES on mkdtemp -- which is
# exactly what the first real `docker compose up` did.
#
# Rejected: running the worker as root, which hands uid 0 to the process holding a Docker
# handle; and chowning from an entrypoint, which needs root at start-up for the same
# reason. Creating it here costs one empty directory and keeps the container unprivileged.
#
# This covers a named volume or a plain `docker run` with no mount at all. It does NOT
# cover the compose stack, which bind-mounts a host directory here: a bind mount takes the
# host's ownership and masks whatever the image has. That host directory must be chowned
# to 10001 before first start, and docs/DEPLOYMENT.md makes it a step rather than a note.
# The bind mount is not optional -- see the worker service in docker-compose.yml for why
# the clone root cannot be a named volume.
#
# The path is duplicated from Settings.clone_root. If that default changes, this must
# change with it -- a mismatch is silent until a scan actually runs.
RUN mkdir -p /var/lib/codesentinel/clones && chown -R appuser:appuser /var/lib/codesentinel

USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
