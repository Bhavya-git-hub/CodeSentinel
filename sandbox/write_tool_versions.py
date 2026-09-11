"""Emit the analysis tool versions baked into this image.

Run once at image build time; the output is frozen into the image at
/opt/codesentinel/tool-versions.json and read back by the backend for each scan.

The versions come from the installed distributions rather than from the build arguments
that requested them, so a resolver substitution cannot make the manifest disagree with
what is actually in the image. Constraint C5 requires a scan to be reproducible, and that
is only true if the recorded versions are the ones that ran.
"""

from __future__ import annotations

import json
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

TOOLS = ("pylint", "bandit", "semgrep", "radon", "coverage", "pytest")


def main() -> int:
    manifest: dict[str, str] = {"python": platform.python_version()}
    missing: list[str] = []

    for tool in TOOLS:
        try:
            manifest[tool] = version(tool)
        except PackageNotFoundError:
            # Fail the build rather than emit a manifest with a hole in it: a scan that
            # records "unknown" for a tool version is not reproducible.
            missing.append(tool)

    if missing:
        # stdout is the manifest itself, so diagnostics go to stderr.
        print(f"missing analysis tools in image: {', '.join(missing)}", file=sys.stderr)  # noqa: T201
        return 1

    # Printing is the interface: the build redirects stdout into the manifest file.
    print(json.dumps(manifest, indent=2, sort_keys=True))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
