"""Validation of submitted repository URLs.

Runs at the API boundary so an unusable URL is refused synchronously, with a reason,
rather than becoming a FAILED scan the caller has to poll for.

The transport check is the security-critical part. ``ext::`` is not an exotic edge case:
git hands the remainder of the string to a shell, so accepting it is accepting arbitrary
command execution as whatever user the worker runs as.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import Settings
from app.services.ingestion.errors import UnsafeRepositoryUrlError

#: Refused regardless of configuration. Nothing legitimate needs them, and each hands
#: git a string it will execute or read outside the intended transport.
ALWAYS_REFUSED_SCHEMES = frozenset({"ext", "ssh", "git+ssh", "scp"})

MAX_URL_LENGTH = 2048


def validate_repository_url(url: str, *, settings: Settings) -> str:
    """Return the URL if it is safe to hand to git, else raise.

    Refuses rather than rewrites: silently turning one URL into another hides what the
    caller actually asked for.
    """
    candidate = url.strip()

    if not candidate:
        raise UnsafeRepositoryUrlError("The repository URL is empty.")

    if len(candidate) > MAX_URL_LENGTH:
        raise UnsafeRepositoryUrlError(
            f"The repository URL is {len(candidate)} characters, "
            f"which exceeds the {MAX_URL_LENGTH} character limit."
        )

    if candidate.startswith("-"):
        # git would read this as a flag rather than a URL -- --upload-pack= is the
        # classic argument-injection vector.
        raise UnsafeRepositoryUrlError(
            "The repository URL may not begin with '-': git would read it as an option."
        )

    scheme = urlparse(candidate).scheme.lower()

    if not scheme:
        # A bare "host:path" is scp-like syntax, which git accepts and which carries no
        # explicit transport for the allowlist to check.
        raise UnsafeRepositoryUrlError(
            f"The repository URL {candidate!r} has no transport. "
            f"Give a full URL, for example https://github.com/owner/name."
        )

    allowed = [protocol.lower() for protocol in settings.clone_allowed_protocols]

    if scheme in ALWAYS_REFUSED_SCHEMES or scheme not in allowed:
        raise UnsafeRepositoryUrlError(
            f"The transport {scheme!r} is not permitted. "
            f"Allowed transports: {', '.join(allowed) or 'none'}."
        )

    return candidate


def repository_name_from_url(url: str) -> str:
    """Derive a display name like ``owner/project`` from the URL path."""
    path = urlparse(url).path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return url
    return "/".join(segments[-2:])
