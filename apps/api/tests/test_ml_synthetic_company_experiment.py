"""Offline guards for the synthetic-company/public-notice smoke experiment."""
import json

import pytest

from apps.api.app.ml_recommendations.aws_synthetic_snapshot import _remote_command, export
from apps.api.app.ml_recommendations.synthetic_company_experiment import pseudo_grade
from apps.api.app.ml_recommendations.synthetic_offline_eval import evaluate


def _company(industries=()):
    return {"industries": [{"name": name} for name in industries],
            "certifications": [], "performances": [], "staff_roles": []}


def test_pseudo_grade_distinguishes_exact_and_unobserved_capability():
    assert pseudo_grade(_company(["폐기물수집운반업"]),
                        {"title": "생활폐기물수집운반업 용역"}) == (3, "exact_capability_phrase")
    assert pseudo_grade(_company(), {"title": "생활폐기물 처리 용역"}) == (
        0, "no_capability_evidence")


def test_aws_snapshot_is_bounded_before_any_remote_call(tmp_path):
    class NoRemote:
        def send_command(self, **kwargs):
            raise AssertionError("A rejected export must not access AWS")

    with pytest.raises(ValueError, match="bounded"):
        export(NoRemote(), tmp_path / "oversized", instance_id="i-080c0feecbcfb9826",
               container="api", per_type=126)
    with pytest.raises(ValueError, match="instance ID"):
        export(NoRemote(), tmp_path / "bad-id", instance_id="not-an-id",
               container="api")
    with pytest.raises(ValueError, match="container name"):
        _remote_command({"kind": "companies"}, "api; echo unsafe")


def test_pseudo_evaluator_rejects_unrelated_or_unmarked_dataset(tmp_path):
    dataset = tmp_path / "pairs.jsonl"
    dataset.write_text("", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"evaluation_scope": "HUMAN_REVIEWED"}),
                                            encoding="utf-8")
    with pytest.raises(ValueError, match="pseudo-label"):
        evaluate(dataset, tmp_path / "models")
