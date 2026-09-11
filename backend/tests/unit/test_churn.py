"""Recency-weighted churn.

The decay maths and, more importantly, the difference between a file that did not change
and a file whose changes could not be counted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.mining.churn import ChangeWeight, churn_score

NOW = datetime(2026, 9, 11, tzinfo=UTC)


def _change(days_ago: float, added: int | None, deleted: int | None) -> ChangeWeight:
    return ChangeWeight(
        changed_at=NOW - timedelta(days=days_ago), lines_added=added, lines_deleted=deleted
    )


def test_a_file_that_never_changed_scores_zero() -> None:
    """Zero is a real measurement here: the mined history contains no change to it."""
    assert churn_score([], as_of=NOW, half_life_days=90) == 0.0


def test_a_change_today_counts_in_full() -> None:
    assert churn_score([_change(0, 10, 5)], as_of=NOW, half_life_days=90) == pytest.approx(15.0)


def test_a_change_one_half_life_old_counts_half() -> None:
    """The whole point of the weighting: old churn must not outrank active churn."""
    score = churn_score([_change(90, 10, 5)], as_of=NOW, half_life_days=90)
    assert score == pytest.approx(7.5)


def test_a_change_two_half_lives_old_counts_a_quarter() -> None:
    score = churn_score([_change(180, 100, 0)], as_of=NOW, half_life_days=90)
    assert score == pytest.approx(25.0)


def test_recent_churn_outranks_larger_old_churn() -> None:
    """A file rewritten five years ago is not what a reviewer should read first."""
    recent = churn_score([_change(7, 50, 50)], as_of=NOW, half_life_days=90)
    ancient = churn_score([_change(1825, 500, 500)], as_of=NOW, half_life_days=90)
    assert recent > ancient


def test_an_all_binary_history_is_unknown_not_zero() -> None:
    """It demonstrably changed; how much is unknown. 0 would rank it as never-touched."""
    changes = [_change(1, None, None), _change(10, None, None)]
    assert churn_score(changes, as_of=NOW, half_life_days=90) is None


def test_a_mixed_history_counts_what_it_can() -> None:
    """Partial knowledge beats discarding the countable changes."""
    changes = [_change(0, 10, 0), _change(0, None, None)]
    assert churn_score(changes, as_of=NOW, half_life_days=90) == pytest.approx(10.0)


def test_a_half_missing_count_still_contributes_its_known_half() -> None:
    changes = [_change(0, 8, None)]
    assert churn_score(changes, as_of=NOW, half_life_days=90) == pytest.approx(8.0)


def test_a_future_timestamp_does_not_amplify_a_change() -> None:
    """Committer clocks lie. A future date must not weight above a present one."""
    future = churn_score([_change(-400, 10, 0)], as_of=NOW, half_life_days=90)
    today = churn_score([_change(0, 10, 0)], as_of=NOW, half_life_days=90)
    assert future == pytest.approx(today)
