"""Radon against the real analysis image, in the real sandbox.

The unit tests prove the parser handles Radon's shapes. Only this proves Radon is
actually in the image, runs under the isolation set, and emits the shape the parser
expects -- a parser can be perfectly correct about output no tool produces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.analyzers import radon
from app.services.sandbox.runner import Sandbox

pytestmark = pytest.mark.requires_docker


@pytest.fixture
def analysis_tree(tmp_path: Path) -> Path:
    """A tree with one measurable file and one Radon cannot parse."""
    tmp_path.chmod(0o755)
    (tmp_path / "simple.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "branchy.py").write_text(
        "def g(x):\n"
        "    if x > 0:\n"
        "        return 1\n"
        "    elif x < 0:\n"
        "        return -1\n"
        "    for i in range(3):\n"
        "        x += i\n"
        "    return x\n",
        encoding="utf-8",
    )
    # Deliberately invalid: this is the file the report must not rank as simple.
    (tmp_path / "broken.py").write_text("def h(:\n", encoding="utf-8")
    for child in tmp_path.iterdir():
        child.chmod(0o644)
    return tmp_path


def test_radon_measures_complexity_inside_the_sandbox(
    analysis_tree: Path, analysis_image: str, docker_client: object
) -> None:
    settings = Settings(sandbox_image=analysis_image)

    with Sandbox(settings, source_dir=analysis_tree) as sandbox:
        complexity, maintainability = radon.measure(sandbox, settings)

    assert complexity.tool_error is None
    assert complexity.values["simple.py"] == 1.0
    assert complexity.values["branchy.py"] > complexity.values["simple.py"], (
        "a branching function must measure more complex than a straight-line one"
    )
    assert maintainability.values["simple.py"] > 0


def test_an_unparseable_file_is_reported_as_unknown_not_as_simple(
    analysis_tree: Path, analysis_image: str, docker_client: object
) -> None:
    """The defect this guards is a syntactically broken file ranking as the safest."""
    settings = Settings(sandbox_image=analysis_image)

    with Sandbox(settings, source_dir=analysis_tree) as sandbox:
        complexity, _ = radon.measure(sandbox, settings)

    assert "broken.py" not in complexity.values
    assert "broken.py" in complexity.errors
    assert complexity.errors["broken.py"]
