"""Assembling measurements into scoring inputs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.analyzers import radon
from app.services.analyzers.analysis import build_inputs
from app.services.mining.churn import ChangeWeight

AS_OF = datetime(2026, 9, 11, tzinfo=UTC)


def test_every_inventoried_file_gets_an_entry_even_when_unmeasurable() -> None:
    """A file missing from the report is a file nobody looks at.

    Omitting what Radon could not parse would be worse than ranking it unknown: an
    unparseable file would simply vanish from the queue rather than appearing at the
    bottom of it with a reason.
    """
    complexity = radon.MetricResult(values={"ok.py": 4.0}, errors={"broken.py": "syntax"})

    inputs = build_inputs(
        ["ok.py", "broken.py"],
        complexity=complexity,
        weights={},
        as_of=AS_OF,
        half_life_days=90,
    )

    assert set(inputs) == {"ok.py", "broken.py"}
    assert inputs["broken.py"].complexity is None
    assert inputs["ok.py"].complexity == 4.0


def test_a_file_with_no_history_has_zero_churn_not_unknown_churn() -> None:
    """It was inventoried and never changed. That is a measurement, not a gap."""
    inputs = build_inputs(
        ["new.py"],
        complexity=radon.MetricResult(values={"new.py": 1.0}),
        weights={},
        as_of=AS_OF,
        half_life_days=90,
    )
    assert inputs["new.py"].churn == 0.0


def test_churn_is_taken_from_the_paths_history() -> None:
    weights = {
        "hot.py": [
            ChangeWeight(changed_at=AS_OF, lines_added=10, lines_deleted=0),
            ChangeWeight(changed_at=AS_OF - timedelta(days=90), lines_added=10, lines_deleted=0),
        ]
    }

    inputs = build_inputs(
        ["hot.py"],
        complexity=radon.MetricResult(values={"hot.py": 2.0}),
        weights=weights,
        as_of=AS_OF,
        half_life_days=90,
    )

    # 10 at full weight plus 10 at one half-life.
    assert inputs["hot.py"].churn == 15.0
