"""Encoder training must use relevance grades, not qualification verdicts."""

import pytest

from apps.api.app.ml_recommendations.trainer import pairwise_training_examples


def _row(query_id, label, *, split="train"):
    return {"query_id": query_id, "label": label, "split": split}


def test_pairwise_training_uses_grade_two_or_three_against_grade_zero():
    pairs = pairwise_training_examples([
        _row("company-a", 1),
        _row("company-a", 2),
        _row("company-a", 0),
        _row("company-b", 3),
        _row("company-b", 0),
        _row("company-c", 3, split="test"),
        _row("company-c", 0, split="test"),
    ])
    assert [(positive["label"], negative["label"]) for positive, negative in pairs] == [
        (2, 0), (3, 0)
    ]


@pytest.mark.parametrize("labels", [[0, 1], [2, 3], []])
def test_pairwise_training_rejects_missing_positive_or_negative(labels):
    with pytest.raises(ValueError, match="No positive/negative reviewed training pairs"):
        pairwise_training_examples([_row("company-a", label) for label in labels])
