"""Blame parsing and the defect-risk model.

The model's most important behaviour is declining. A probability is exactly the kind of
number that gets believed, so one computed over four labelled commits is worse than none.
"""

from __future__ import annotations

from app.services.prediction.blame import parse_blame_shas, parse_deleted_ranges
from app.services.prediction.model import (
    MIN_LABELLED_COMMITS,
    LabelledCommit,
    bucket_for,
    predict,
)

DIFF = """diff --git a/pkg/module.py b/pkg/module.py
index 1111111..2222222 100644
--- a/pkg/module.py
+++ b/pkg/module.py
@@ -12,3 +12,4 @@
-    return x / 0
+    if x:
+        return 1
+    return 0
@@ -40 +41,2 @@
-    pass
+    raise ValueError
"""


def test_deleted_ranges_come_from_the_parent_side() -> None:
    """The `-` side is what existed before the fix and is where the defect lived."""
    assert parse_deleted_ranges(DIFF) == {"pkg/module.py": [(12, 14), (40, 40)]}


def test_a_pure_addition_contributes_no_range() -> None:
    """The lines a fix adds are the repair; blaming them would name the fix's own parent.

    A hunk with a zero-length `-` side touched nothing that existed, so there is nothing
    there to attribute a defect to.
    """
    diff = "+++ b/new.py\n@@ -0,0 +1,5 @@\n+added\n"
    assert parse_deleted_ranges(diff) == {}


def test_a_deleted_file_contributes_no_range() -> None:
    """Its lines are gone at HEAD and there is nothing left to blame."""
    assert parse_deleted_ranges("+++ /dev/null\n@@ -1,9 +0,0 @@\n-gone\n") == {}


def test_blame_shas_are_read_from_the_porcelain_header_lines() -> None:
    porcelain = (
        "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f00 12 12 1\n"
        "author Someone\n"
        "\tsome source line\n"
        "0011223344556677889900aabbccddeeff001122 13 13 1\n"
        "author Someone Else\n"
    )
    assert parse_blame_shas(porcelain) == {
        "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f00",
        "0011223344556677889900aabbccddeeff001122",
    }


def test_source_lines_are_not_mistaken_for_shas() -> None:
    """A tab-indented source line can start with anything."""
    assert parse_blame_shas("\tnot_a_sha_but_forty_characters_long_xxx 1\n") == set()


# -- the model ---------------------------------------------------------------


def test_a_thin_history_produces_no_predictions_and_says_why() -> None:
    """A rate over a handful of commits is noise wearing the costume of a probability."""
    commits = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=False)
        for i in range(5)
    ]

    predictions, reason = predict(commits)

    assert predictions == []
    assert reason is not None
    assert "at least" in reason
    # The reason must not let a reader conclude the repository is clean.
    assert "not that its commits are safe" in reason


def test_an_adequate_history_produces_probabilities() -> None:
    commits = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=(i % 4 == 0))
        for i in range(MIN_LABELLED_COMMITS + 10)
    ]

    predictions, reason = predict(commits)

    assert reason is None
    assert len(predictions) == len(commits)
    assert 0.0 <= predictions[0].probability <= 1.0
    assert predictions[0].sample_size == len(commits)


def test_bigger_commits_score_higher_when_the_history_says_so() -> None:
    """The model must reflect the repository rather than a prior we imposed."""
    small = [
        LabelledCommit(sha=f"a{i:039x}", lines_changed=5, is_defect_inducing=False)
        for i in range(20)
    ]
    large = [
        LabelledCommit(sha=f"b{i:039x}", lines_changed=500, is_defect_inducing=True)
        for i in range(20)
    ]

    predictions, reason = predict(small + large)
    assert reason is None

    by_sha = {p.sha: p for p in predictions}
    assert by_sha[small[0].sha].probability < by_sha[large[0].sha].probability


def test_a_commit_of_unknown_size_gets_no_prediction() -> None:
    """An all-binary diff is not a tiny commit; it is a commit we could not measure."""
    commits = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=(i % 3 == 0))
        for i in range(MIN_LABELLED_COMMITS + 5)
    ]
    commits.append(LabelledCommit(sha="f" * 40, lines_changed=None, is_defect_inducing=None))

    predictions, _ = predict(commits)

    assert "f" * 40 not in {p.sha for p in predictions}


def test_unlabelled_commits_do_not_count_as_clean_history() -> None:
    """They are excluded from the denominator, not counted as non-defect-inducing."""
    unlabelled = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=None)
        for i in range(100)
    ]
    predictions, reason = predict(unlabelled)

    assert predictions == []
    assert reason is not None


def test_unknown_size_has_no_bucket() -> None:
    assert bucket_for(None) is None
    assert bucket_for(5) == "tiny"
    assert bucket_for(10_000) == "huge"


def test_an_all_positive_labelled_set_produces_no_predictions() -> None:
    """Found by the first real scan, not by any test written before it.

    When the blame pass truncates, nothing can be ruled out, so every label is True.
    A frequency over an all-positive set is 1.0 for every commit -- 2,160 commits scored
    at certainty, which is a confident number meaning nothing. MIN_LABELLED_COMMITS did
    not catch it: there were 166 labels, all of one class.
    """
    commits = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=True)
        for i in range(200)
    ]

    predictions, reason = predict(commits)

    assert predictions == []
    assert reason is not None
    assert "not that every commit is risky" in reason


def test_an_all_negative_labelled_set_also_produces_none() -> None:
    """The mirror failure: every commit at 0.0 reads as a clean repository."""
    commits = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=False)
        for i in range(200)
    ]
    predictions, reason = predict(commits)
    assert predictions == []
    assert reason is not None


def test_a_lopsided_but_two_class_history_still_models() -> None:
    """Refusing must not become refusing everything; imbalance is normal and fine."""
    commits = [
        LabelledCommit(sha=f"{i:040x}", lines_changed=20, is_defect_inducing=(i < 6))
        for i in range(200)
    ]
    predictions, reason = predict(commits)
    assert reason is None
    assert len(predictions) == 200
