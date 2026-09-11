"""Normalisation and the risk score."""

from __future__ import annotations

import pytest

from app.services.scoring.risk import RiskInputs, normalize, score_files


def test_values_are_normalized_against_the_maximum() -> None:
    assert normalize({"a": 10.0, "b": 5.0, "c": 0.0}) == {"a": 1.0, "b": 0.5, "c": 0.0}


def test_a_zero_maximum_does_not_divide_by_zero() -> None:
    """Every file measuring zero is a real state, not an error."""
    assert normalize({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}


def test_a_single_file_normalizes_to_one() -> None:
    """Min-max would make this 0 and zero out its risk however much it churns."""
    assert normalize({"only.py": 7.0}) == {"only.py": 1.0}


def test_unknown_values_are_not_normalized_into_existence() -> None:
    result = normalize({"a": 10.0, "b": None})
    assert result["a"] == 1.0
    assert result["b"] is None


def test_risk_is_the_product_of_the_two_normalized_components() -> None:
    scored = score_files(
        {
            "hot.py": RiskInputs(complexity=10.0, churn=100.0, maintainability=40.0),
            "cold.py": RiskInputs(complexity=5.0, churn=0.0, maintainability=90.0),
        }
    )
    assert scored["hot.py"].risk_score == pytest.approx(1.0)
    assert scored["cold.py"].risk_score == pytest.approx(0.0)


def test_a_complex_but_static_file_outranks_nothing() -> None:
    """Complexity alone is not risk -- code nobody touches is not where defects land."""
    scored = score_files(
        {
            "complex_static.py": RiskInputs(complexity=100.0, churn=0.0, maintainability=None),
            "simple_churning.py": RiskInputs(complexity=5.0, churn=500.0, maintainability=None),
        }
    )
    assert scored["simple_churning.py"].risk_score > scored["complex_static.py"].risk_score


def test_an_unmeasured_complexity_yields_an_unknown_risk_not_a_zero_one() -> None:
    """A file Radon could not parse must not be presented as the safest in the repo."""
    scored = score_files(
        {
            "broken.py": RiskInputs(complexity=None, churn=500.0, maintainability=None),
            "fine.py": RiskInputs(complexity=10.0, churn=10.0, maintainability=None),
        }
    )
    assert scored["broken.py"].risk_score is None
    assert scored["broken.py"].normalized_churn is not None
    assert scored["fine.py"].risk_score is not None


def test_an_unknown_churn_also_yields_an_unknown_risk() -> None:
    scored = score_files({"binary.py": RiskInputs(complexity=10.0, churn=None)})
    assert scored["binary.py"].risk_score is None


def test_the_components_are_kept_so_a_rank_can_be_explained() -> None:
    """A rank nobody can explain is a rank nobody acts on."""
    scored = score_files(
        {
            "a.py": RiskInputs(complexity=10.0, churn=50.0),
            "b.py": RiskInputs(complexity=5.0, churn=100.0),
        }
    )
    a = scored["a.py"]
    assert a.normalized_complexity == pytest.approx(1.0)
    assert a.normalized_churn == pytest.approx(0.5)
    assert a.risk_score == pytest.approx(a.normalized_complexity * a.normalized_churn)


def test_unmeasured_files_do_not_shift_the_normalization_scale() -> None:
    """A None must not be treated as a 0 that happens to be the minimum."""
    with_unknown = score_files(
        {
            "a.py": RiskInputs(complexity=10.0, churn=10.0),
            "b.py": RiskInputs(complexity=None, churn=10.0),
        }
    )
    without = score_files({"a.py": RiskInputs(complexity=10.0, churn=10.0)})
    assert with_unknown["a.py"].risk_score == without["a.py"].risk_score
