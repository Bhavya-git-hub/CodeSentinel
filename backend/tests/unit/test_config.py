"""Configuration behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_defaults_are_local() -> None:
    settings = Settings()
    assert settings.environment == "local"
    assert settings.api_v1_prefix == "/api/v1"


def test_env_prefix_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODESENTINEL_LOG_LEVEL", "DEBUG")
    assert Settings().log_level == "DEBUG"


def test_unprefixed_env_var_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare LOG_LEVEL must not leak in from an unrelated tool on the same host."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert Settings().log_level == "INFO"


def test_cors_origins_accept_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODESENTINEL_CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_settings_are_frozen() -> None:
    """Configuration must not drift at runtime, or the C5 snapshot would be a lie."""
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_broker_defaults_to_redis_url() -> None:
    settings = Settings()
    assert settings.broker_url == str(settings.redis_url)
    assert settings.result_backend == str(settings.redis_url)


def test_broker_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODESENTINEL_CELERY_BROKER_URL", "redis://broker.test:6379/2")
    assert Settings().broker_url == "redis://broker.test:6379/2"


def test_reproducibility_snapshot_excludes_credentials() -> None:
    """The C5 snapshot is persisted with every scan; it must carry no connection secrets."""
    snapshot = Settings().reproducibility_snapshot()
    serialised = str(snapshot)
    assert "postgresql" not in serialised
    assert "redis://" not in serialised
    assert snapshot["sandbox_timeout_seconds"] > 0


def test_snapshot_records_every_sandbox_limit() -> None:
    """Every enforced sandbox bound must be reproducible, or a rerun is not comparable."""
    snapshot = Settings().reproducibility_snapshot()
    for key in (
        "sandbox_image",
        "sandbox_mem_limit",
        "sandbox_cpu_quota",
        "sandbox_pids_limit",
        "sandbox_timeout_seconds",
    ):
        assert key in snapshot


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODESENTINEL_LOG_LEVEL", "CHATTY")
    with pytest.raises(ValidationError):
        Settings()
