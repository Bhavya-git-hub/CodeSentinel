"""Parsing Radon's JSON.

Radon reports per-file failures inline rather than by exiting non-zero, so a naive parse
silently drops exactly the files worth looking at.
"""

from __future__ import annotations

import json

from app.services.analyzers.radon import parse_complexity, parse_maintainability


def test_per_file_complexity_is_the_sum_of_its_blocks() -> None:
    """A file with many simple functions has more places to be wrong than one with few."""
    payload = json.dumps(
        {
            "./pkg/module.py": [
                {"type": "function", "name": "f", "complexity": 3},
                {"type": "function", "name": "g", "complexity": 5},
            ]
        }
    )
    assert parse_complexity(payload).values == {"pkg/module.py": 8.0}


def test_a_file_radon_could_not_parse_is_unknown_not_zero() -> None:
    """Complexity 0 would rank an unparseable file as the simplest in the repository."""
    payload = json.dumps({"./broken.py": {"error": "invalid syntax (broken.py, line 3)"}})

    result = parse_complexity(payload)

    assert result.values == {}
    assert "broken.py" in result.errors
    assert "invalid syntax" in result.errors["broken.py"]


def test_good_and_broken_files_in_one_payload_are_both_reported() -> None:
    payload = json.dumps(
        {
            "./ok.py": [{"type": "function", "name": "f", "complexity": 2}],
            "./bad.py": {"error": "invalid syntax"},
        }
    )

    result = parse_complexity(payload)

    assert result.values == {"ok.py": 2.0}
    assert set(result.errors) == {"bad.py"}


def test_an_empty_file_has_zero_complexity() -> None:
    """No blocks is a real measurement: there is genuinely nothing to branch on."""
    assert parse_complexity(json.dumps({"./empty.py": []})).values == {"empty.py": 0.0}


def test_maintainability_is_read_per_file() -> None:
    payload = json.dumps({"./pkg/module.py": {"mi": 65.25, "rank": "A"}})
    assert parse_maintainability(payload).values == {"pkg/module.py": 65.25}


def test_maintainability_is_clamped_to_the_zero_hundred_range() -> None:
    """Radon's underlying formula can go negative; the column is documented as 0-100."""
    payload = json.dumps({"./a.py": {"mi": -12.0}, "./b.py": {"mi": 140.0}})
    values = parse_maintainability(payload).values
    assert values == {"a.py": 0.0, "b.py": 100.0}


def test_a_maintainability_error_is_recorded_not_dropped() -> None:
    payload = json.dumps({"./broken.py": {"error": "cannot parse"}})
    result = parse_maintainability(payload)
    assert result.values == {}
    assert "broken.py" in result.errors


def test_unparseable_output_is_an_error_rather_than_an_empty_result() -> None:
    """An empty result and a failed tool must never look the same (C3)."""
    result = parse_complexity("not json at all")
    assert result.values == {}
    assert result.tool_error is not None
    assert "json" in result.tool_error.lower()
