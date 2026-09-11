"""Settings additions for phase 3 ingestion."""

from __future__ import annotations

from app.config import Settings


def test_clone_allowed_protocols_defaults_to_https_only(settings_defaults: Settings) -> None:
    """Production must not reach a weaker transport without someone setting it."""
    assert settings_defaults.clone_allowed_protocols == ["https"]


def test_clone_allowed_protocols_accepts_a_comma_separated_value() -> None:
    """The value has to survive a .env file, which carries strings."""
    assert Settings(clone_allowed_protocols="https,file").clone_allowed_protocols == [
        "https",
        "file",
    ]


def test_size_check_interval_is_in_the_reproducibility_snapshot(
    settings_defaults: Settings,
) -> None:
    """It changes the effective size ceiling, so it changes what a scan accepted (C5)."""
    assert "clone_size_check_interval_seconds" in settings_defaults.reproducibility_snapshot()
    assert "clone_allowed_protocols" in settings_defaults.reproducibility_snapshot()
