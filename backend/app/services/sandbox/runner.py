"""Docker-backed sandbox for analysing untrusted repositories.

Constraint C1: every analysis of a target repository runs inside a container created here.
Cloning arbitrary repositories from the internet and executing their test suites means
running untrusted code -- a target's ``conftest.py`` executes at pytest collection time,
and ``setup.py`` executes on install. Nothing in this module may grow a code path that
runs a target command on the host.

The isolation is applied as a set, not a menu. Every container gets: no network, a
read-only bind mount of the source, a writable tmpfs scratch dir, a non-root user, a
read-only root filesystem, memory/CPU/PID limits, all capabilities dropped, and
no-new-privileges. There is no argument to turn any of these off, because a caller that
could would eventually be a caller that did.
"""

from __future__ import annotations

import json
import os
import stat
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

import docker
import structlog
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.types import LogConfig, Mount
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from app.config import Settings
from app.services.sandbox.errors import (
    SandboxConfigurationError,
    SandboxImageMissingError,
    SandboxUnavailableError,
)
from app.services.sandbox.result import SandboxOutcome, SandboxResult

logger = structlog.get_logger(__name__)

#: Where the target's source is mounted, read-only, inside the container.
WORKSPACE_PATH = "/workspace"
#: Writable scratch space. The root filesystem is read-only, so this is the only place
#: the analysis tools can write, and it is discarded with the container.
SCRATCH_PATH = "/tmp"

#: The unprivileged uid/gid the analysis container runs as. Mounted source must be
#: readable by it, which in practice means world-readable: this id will never match the
#: host user that made the clone.
SANDBOX_UID = 10001
SANDBOX_GID = 10001

#: Every container is labelled so orphans left by a crashed worker can be found and
#: reaped, rather than accumulating invisibly on the host.
OWNER_LABEL = "codesentinel.owner"
OWNER_LABEL_VALUE = "codesentinel"
RUN_ID_LABEL = "codesentinel.run_id"


class Sandbox:
    """Runs commands against a target repository under container isolation.

    One container per command, always removed. The instance holds the Docker client and
    the source directory; it does not hold a container between calls, so a leaked
    container cannot outlive the call that created it.

    Use as a context manager so the Docker client is closed::

        with Sandbox(settings, source_dir=clone_path) as sandbox:
            result = sandbox.run(["radon", "cc", "-j", "."])
    """

    def __init__(
        self,
        settings: Settings,
        *,
        source_dir: Path,
        client: docker.DockerClient | None = None,
        run_id: str | None = None,
    ) -> None:
        self._settings = settings
        self._source_dir = source_dir.resolve()
        self._run_id = run_id or uuid.uuid4().hex
        self._owns_client = client is None
        self._client = client or self._connect(settings)

        if not self._source_dir.is_dir():
            raise SandboxConfigurationError(
                f"source directory {self._source_dir} does not exist or is not a directory"
            )
        self._assert_source_readable()

    def _assert_source_readable(self) -> None:
        """Refuse a source tree the sandbox user could not read.

        The container runs as an unprivileged uid that will never match the host user
        which made the clone, so the mount has to be world-readable. When it is not,
        every analyser sees an empty or unreadable workspace and reports no findings --
        a silent false-clean result, which is the worst possible failure for a tool whose
        entire output is "what is wrong with this code".

        Checked rather than repaired: silently chmod-ing a host directory is a surprising
        side effect, and the fix belongs to whatever created the clone.
        """
        if os.name != "posix":
            # Windows mode bits do not describe container access; Docker Desktop mediates
            # the mount itself. Nothing useful to assert here.
            return

        mode = self._source_dir.stat().st_mode
        if not (mode & stat.S_IROTH and mode & stat.S_IXOTH):
            raise SandboxConfigurationError(
                f"source directory {self._source_dir} is not readable by the sandbox user "
                f"(uid {SANDBOX_UID}); its mode is {stat.filemode(mode)}. Analysis would "
                "silently see an empty workspace and report no findings. Make the clone "
                "world-readable (chmod o+rX) before analysing it."
            )

    # -- lifecycle ------------------------------------------------------------------

    @staticmethod
    def _connect(settings: Settings) -> docker.DockerClient:
        """Connect to the Docker daemon, or fail loudly.

        There is deliberately no host-execution fallback: if the sandbox cannot be
        established, the analysis does not run.
        """
        try:
            client = docker.from_env(timeout=settings.sandbox_timeout_seconds + 30)
            client.ping()
        except (DockerException, RequestsConnectionError) as exc:
            raise SandboxUnavailableError(f"cannot reach the Docker daemon: {exc}") from exc
        return client

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release the Docker client if this instance created it."""
        if self._owns_client:
            self._client.close()

    # -- public API -----------------------------------------------------------------

    @property
    def run_id(self) -> str:
        """Identifier stamped on every container this sandbox creates."""
        return self._run_id

    def tool_versions(self) -> dict[str, str]:
        """Read the analysis tool versions baked into the image.

        Taken from the image rather than the host, because the host does not have these
        tools installed at all (ADR 0003) and because the image is what actually produced
        the result being recorded (constraint C5).
        """
        result = self.run(["cat", "/opt/codesentinel/tool-versions.json"], timeout=30)
        if result.outcome is not SandboxOutcome.COMPLETED or result.exit_code != 0:
            raise SandboxImageMissingError(
                f"analysis image {self._settings.sandbox_image} has no readable version "
                f"manifest (exit={result.exit_code}, stderr={result.stderr[:200]!r})"
            )
        parsed: dict[str, str] = json.loads(result.stdout)
        return parsed

    def run(self, command: Sequence[str], *, timeout: int | None = None) -> SandboxResult:
        """Run one command in a throwaway container and return what it produced.

        A non-zero exit code is a normal result, not an exception: Pylint exits non-zero
        precisely when it finds issues. Only a failure to *establish* isolation raises.
        """
        timeout = timeout or self._settings.sandbox_timeout_seconds
        started = time.monotonic()

        with self._container(command) as container:
            container.start()
            outcome, exit_code = self._await_exit(container, timeout)
            stdout, stdout_truncated = self._capture(container, stdout=True)
            stderr, stderr_truncated = self._capture(container, stdout=False)
            if outcome is SandboxOutcome.COMPLETED and self._was_oom_killed(container):
                outcome = SandboxOutcome.OUT_OF_MEMORY

        duration = time.monotonic() - started
        result = SandboxResult(
            outcome=outcome,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
        logger.info(
            "sandbox.run_finished",
            run_id=self._run_id,
            command=list(command)[:4],
            outcome=result.outcome.value,
            exit_code=result.exit_code,
            duration_seconds=round(duration, 3),
            truncated=result.truncated,
        )
        return result

    def reap_orphans(self) -> int:
        """Remove any leftover CodeSentinel containers and report how many.

        A container is normally removed by :meth:`run`'s ``finally``. That cannot cover a
        worker killed by SIGKILL or a host reboot mid-run, so this exists to be called at
        worker start-up. Returning the count means an accumulating leak is visible rather
        than silently cleaned up forever.
        """
        reaped = 0
        for container in self._client.containers.list(
            all=True, filters={"label": f"{OWNER_LABEL}={OWNER_LABEL_VALUE}"}
        ):
            try:
                container.remove(force=True)
            except (APIError, NotFound) as exc:
                logger.warning("sandbox.reap_failed", container_id=container.id, error=str(exc))
                continue
            reaped += 1
            logger.info("sandbox.reaped_orphan", container_id=container.id)
        return reaped

    # -- internals ------------------------------------------------------------------

    @contextmanager
    def _container(self, command: Sequence[str]) -> Iterator[Container]:
        """Create a locked-down container and guarantee its removal.

        The removal lives in a ``finally`` rather than relying on ``auto_remove``:
        auto-remove races with reading the container's logs and its exit state, and a
        container that vanishes before we read its output produces a silently empty
        result.
        """
        try:
            container = self._client.containers.create(**self._container_config(command))
        except ImageNotFound as exc:
            raise SandboxImageMissingError(
                f"analysis image {self._settings.sandbox_image} is not present on the host; "
                "the sandbox has no network, so it must be built or pulled beforehand"
            ) from exc
        except (APIError, DockerException) as exc:
            raise SandboxUnavailableError(
                f"could not create the analysis container: {exc}"
            ) from exc

        try:
            yield container
        finally:
            try:
                container.remove(force=True)
            except NotFound:
                pass
            except APIError as exc:
                # Reported, never swallowed: a container that could not be removed is a
                # resource leak on the host and reap_orphans needs to know it exists.
                logger.error(
                    "sandbox.container_removal_failed",
                    run_id=self._run_id,
                    container_id=container.id,
                    error=str(exc),
                )

    def _container_config(self, command: Sequence[str]) -> dict[str, Any]:
        """Build the container configuration.

        Every restriction here is load-bearing; the comments say what each one stops.
        """
        settings = self._settings
        return {
            "image": settings.sandbox_image,
            "command": list(command),
            "detach": True,
            "name": f"codesentinel-{self._run_id}-{uuid.uuid4().hex[:8]}",
            "labels": {OWNER_LABEL: OWNER_LABEL_VALUE, RUN_ID_LABEL: self._run_id},
            # No network at all. Stops exfiltration of anything the container can read and
            # stops a malicious target pulling a second stage.
            "network_mode": "none",
            "network_disabled": True,
            # The source is mounted read-only, so analysis cannot modify the clone that
            # later phases mine for history.
            "mounts": [
                Mount(
                    target=WORKSPACE_PATH,
                    source=str(self._source_dir),
                    type="bind",
                    read_only=True,
                )
            ],
            "working_dir": WORKSPACE_PATH,
            # Read-only root filesystem plus a writable tmpfs. Anything written is
            # discarded with the container and never touches the host.
            "read_only": True,
            "tmpfs": {
                SCRATCH_PATH: (
                    f"rw,noexec,nosuid,size={settings.sandbox_tmpfs_size_bytes},mode=1777"
                )
            },
            # Non-root, even though the image already declares this user: relying on the
            # image alone means a rebuilt or substituted image could silently run as root.
            "user": f"{SANDBOX_UID}:{SANDBOX_GID}",
            "mem_limit": settings.sandbox_mem_limit,
            # Denying swap makes mem_limit an actual ceiling instead of a soft one.
            "memswap_limit": settings.sandbox_mem_limit,
            "cpu_quota": settings.sandbox_cpu_quota,
            "cpu_period": settings.sandbox_cpu_period,
            # A fork bomb in a target's test suite exhausts this, not the host.
            "pids_limit": settings.sandbox_pids_limit,
            "cap_drop": ["ALL"],
            # Blocks setuid binaries from regaining privileges dropped above.
            "security_opt": ["no-new-privileges"],
            # Bounds what the daemon writes to host disk. The in-process capture below
            # bounds what we hold in memory; this bounds the other copy.
            "log_config": LogConfig(type="json-file", config={"max-size": "16m", "max-file": "1"}),
            # PID 1 that reaps zombies, so a target spawning children cannot exhaust the
            # PID limit with defunct processes.
            "init": True,
            "environment": {
                "HOME": SCRATCH_PATH,
                "PYTHONDONTWRITEBYTECODE": "1",
                # Target code must never see anything about the host or the scan.
                "CODESENTINEL_SANDBOX": "1",
            },
        }

    def _await_exit(self, container: Container, timeout: int) -> tuple[SandboxOutcome, int | None]:
        """Wait for the container, killing it if it outlives the timeout.

        The kill is the point. ``wait(timeout=...)`` only times out the HTTP request; the
        container keeps running and consuming CPU and memory unless it is explicitly
        killed. Abandoning the request instead of killing is how an infinite loop in a
        target's test suite becomes a permanently pegged host core.
        """
        try:
            status = container.wait(timeout=timeout)
        except (ReadTimeout, RequestsConnectionError):
            logger.warning(
                "sandbox.timeout_killing_container",
                run_id=self._run_id,
                container_id=container.id,
                timeout_seconds=timeout,
            )
            self._kill(container)
            return SandboxOutcome.TIMED_OUT, None

        exit_code = status.get("StatusCode") if isinstance(status, dict) else None
        return SandboxOutcome.COMPLETED, exit_code

    def _kill(self, container: Container) -> None:
        """SIGKILL the container, tolerating it having already exited."""
        try:
            container.kill()
        except (APIError, NotFound) as exc:
            # Already dead is fine; anything else is worth knowing about, because it
            # means a container may still be running.
            logger.warning(
                "sandbox.kill_failed",
                run_id=self._run_id,
                container_id=container.id,
                error=str(exc),
            )

    def _capture(self, container: Container, *, stdout: bool) -> tuple[str, bool]:
        """Drain one output stream, stopping at the configured byte cap.

        Streamed and capped rather than read whole: a target that prints in a loop would
        otherwise be handed straight into the worker's memory. The cap is reported so a
        truncated result is never mistaken for a complete one.
        """
        limit = self._settings.sandbox_max_output_bytes
        collected = bytearray()
        truncated = False

        try:
            stream = container.logs(stdout=stdout, stderr=not stdout, stream=True, follow=False)
        except (APIError, NotFound) as exc:
            logger.warning(
                "sandbox.log_capture_failed",
                run_id=self._run_id,
                container_id=container.id,
                stream="stdout" if stdout else "stderr",
                error=str(exc),
            )
            return "", False

        for chunk in stream:
            remaining = limit - len(collected)
            if remaining <= 0:
                truncated = True
                break
            if len(chunk) > remaining:
                collected.extend(chunk[:remaining])
                truncated = True
                break
            collected.extend(chunk)

        if truncated:
            logger.warning(
                "sandbox.output_truncated",
                run_id=self._run_id,
                stream="stdout" if stdout else "stderr",
                limit_bytes=limit,
            )
        return collected.decode("utf-8", errors="replace"), truncated

    def _was_oom_killed(self, container: Container) -> bool:
        """Whether the kernel OOM killer stopped the container.

        Worth distinguishing: an OOM-killed analyser looks like a crash, and reporting it
        as a plain non-zero exit would send someone hunting a bug in the target instead of
        raising the memory limit.
        """
        try:
            container.reload()
        except (APIError, NotFound):
            return False
        state = container.attrs.get("State", {})
        return bool(state.get("OOMKilled", False))
