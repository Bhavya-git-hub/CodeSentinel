"""Application configuration.

All tunable values live here rather than at their point of use, because constraint C5
requires every scan result to be reproducible: the configuration that produced a result is
persisted alongside it (see ``Settings.reproducibility_snapshot``). A limit hardcoded at a
call site cannot be recorded, so it cannot be reproduced.

Sandbox and ingestion settings are defined before the phases that consume them (2 and 3)
for the same reason -- they are part of the reproducibility record, not incidental knobs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "ci", "production"]


class Settings(BaseSettings):
    """Runtime configuration, populated from ``CODESENTINEL_``-prefixed env vars."""

    model_config = SettingsConfigDict(
        env_prefix="CODESENTINEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # -- Application ----------------------------------------------------------------
    environment: Environment = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_v1_prefix: str = "/api/v1"
    # NoDecode: pydantic-settings otherwise JSON-decodes list fields inside the env
    # source, before any validator runs, so a plain comma-separated value would raise
    # rather than reach _split_comma_separated.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # -- Persistence ----------------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+asyncpg://codesentinel:codesentinel@localhost:5432/codesentinel"
        ),
    )
    test_database_url: PostgresDsn | None = None
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    # -- Broker ---------------------------------------------------------------------
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))
    celery_broker_url: RedisDsn | None = None
    celery_result_backend: RedisDsn | None = None

    # -- Sandbox (phase 2) ----------------------------------------------------------
    # Every target repository is analysed inside a throwaway container with no network
    # access. These are the resource bounds for that container; see constraint C1.
    sandbox_image: str = "codesentinel/analysis:0.1.0"
    sandbox_mem_limit: str = "2g"
    sandbox_cpu_quota: int = Field(default=100_000, ge=1000)
    sandbox_cpu_period: int = Field(default=100_000, ge=1000)
    sandbox_pids_limit: int = Field(default=256, ge=1)
    sandbox_timeout_seconds: int = Field(default=600, ge=1)
    sandbox_max_output_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    sandbox_tmpfs_size_bytes: int = Field(default=512 * 1024 * 1024, ge=1024)

    # -- Ingestion (phase 3) --------------------------------------------------------
    # Clones are full, never shallow: phase 4 history mining and phase 8 SZZ both need
    # the complete commit graph. A size guard replaces the depth guard a shallow clone
    # would have given us.
    clone_root: str = "/var/lib/codesentinel/clones"
    max_repo_size_mb: int = Field(default=1024, ge=1)
    clone_timeout_seconds: int = Field(default=900, ge=1)
    # The transport allowlist. Default https only: an ext:: URL is arbitrary command
    # execution on the host, and the exotic transports have no legitimate use here.
    # This is a setting rather than a constant so tests can clone from a local path
    # without the cloner growing a "just for testing" branch (anti-pattern #1) -- and
    # because it lands in the reproducibility snapshot, a scan that ran under a relaxed
    # allowlist says so in its own record.
    clone_allowed_protocols: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["https"]
    )
    # How often the size guard samples the growing clone. The guard is a ceiling with
    # overshoot, not a hard cap: the bound is limit + (interval x transfer rate), so this
    # value is part of what a scan actually enforced.
    clone_size_check_interval_seconds: float = Field(default=0.5, gt=0)

    @field_validator("cors_origins", "clone_allowed_protocols", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: Any) -> Any:
        """Accept a comma-separated string so the value can come from a .env file."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def broker_url(self) -> str:
        """Celery broker, defaulting to the shared Redis instance."""
        return str(self.celery_broker_url or self.redis_url)

    @property
    def result_backend(self) -> str:
        """Celery result backend, defaulting to the shared Redis instance."""
        return str(self.celery_result_backend or self.redis_url)

    def reproducibility_snapshot(self) -> dict[str, Any]:
        """Configuration subset persisted with every scan to satisfy constraint C5.

        Deliberately excludes connection URLs: they carry credentials and say nothing
        about how a result was computed.
        """
        return {
            "sandbox_image": self.sandbox_image,
            "sandbox_mem_limit": self.sandbox_mem_limit,
            "sandbox_cpu_quota": self.sandbox_cpu_quota,
            "sandbox_cpu_period": self.sandbox_cpu_period,
            "sandbox_pids_limit": self.sandbox_pids_limit,
            "sandbox_timeout_seconds": self.sandbox_timeout_seconds,
            "max_repo_size_mb": self.max_repo_size_mb,
            "clone_timeout_seconds": self.clone_timeout_seconds,
            "clone_allowed_protocols": list(self.clone_allowed_protocols),
            "clone_size_check_interval_seconds": self.clone_size_check_interval_seconds,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, cached so env parsing happens once.

    Tests override by calling ``get_settings.cache_clear()`` after patching the
    environment.
    """
    return Settings()
