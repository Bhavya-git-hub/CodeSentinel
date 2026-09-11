"""Walking a cloned repository into file records.

Reading a file's bytes is not the "analysis" constraint C1 confines to the sandbox: no
target code is executed here, and nothing a target can put in a file changes what this
module does. ADR 0011 records where that line sits and why.

The load-bearing distinction in this module is between a count of zero and no count at
all. An empty file genuinely has zero lines; a file whose bytes are not text has an
unknown number of them. Phase 4 divides by these.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import structlog

logger = structlog.get_logger(__name__)

#: Extension to language. Deliberately small: Python is what this system analyses, and a
#: language named here implies an analyser that can read it.
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".cfg": "ini",
    ".ini": "ini",
    ".txt": "text",
}

#: Never walked into. .git is the repository's own metadata, and the rest are caches that
#: would otherwise be inventoried as though a human wrote them.
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        ".eggs",
    }
)

MAX_LINE_COUNT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileRecord:
    """One file in the working tree.

    ``language`` and ``loc`` are both optional, and their absence means "not determined"
    rather than "none" or "zero".
    """

    path: str
    language: str | None
    loc: int | None
    is_test: bool


def classify_language(path: PurePosixPath) -> str | None:
    """Language by extension, or None when we do not claim to know."""
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def is_test_path(path: PurePosixPath) -> bool:
    """Whether this file is test code.

    Phase 6 intersects coverage with complexity to find high-risk untested code. Counting
    a test file as production code would let a well-tested test suite disguise an
    untested codebase.
    """
    if any(part == "tests" or part == "test" for part in path.parts[:-1]):
        return True
    name = path.name
    if name == "conftest.py":
        return True
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


def count_lines(path: Path) -> int | None:
    """Lines in a text file, or None if it is not text we can read.

    Returns None rather than 0 for undecodable bytes: 0 is a claim about the file's
    contents, and we are not in a position to make one.
    """
    try:
        if path.stat().st_size > MAX_LINE_COUNT_BYTES:
            return None
    except OSError:
        return None

    try:
        with path.open("rb") as handle:
            raw = handle.read()
    except OSError as exc:
        logger.warning("inventory.unreadable", path=str(path), error=str(exc))
        return None

    if b"\x00" in raw:
        # A NUL byte means binary. Decoding would sometimes succeed and produce a
        # meaningless count.
        return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if not text:
        return 0
    return len(text.splitlines())


def inventory_files(root: Path) -> list[FileRecord]:
    """Every file in the working tree, as records.

    Symlinks are recorded but not followed: a target can point one outside the clone, and
    following it would inventory the host.
    """
    records: list[FileRecord] = []

    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        subdirectories[:] = [name for name in subdirectories if name not in SKIP_DIRECTORIES]
        for filename in sorted(filenames):
            absolute = Path(directory) / filename
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            records.append(
                FileRecord(
                    path=str(relative),
                    language=classify_language(relative),
                    loc=None if absolute.is_symlink() else count_lines(absolute),
                    is_test=is_test_path(relative),
                )
            )

    records.sort(key=lambda record: record.path)
    return records
