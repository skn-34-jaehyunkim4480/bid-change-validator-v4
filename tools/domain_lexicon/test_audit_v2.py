"""Regression tests for BCV4-03-002; all run entirely offline, no AWS calls."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_quality import graph_audit, run as audit
from offline_retrieval_smoke import prepare, run as offline
from snapshot_crosscheck import run as crosscheck


def test_all_existing_and_auto_evidence_is_grounded():
    stats = audit()
    assert stats["verified_lexicon_excerpts"] == 240
    assert stats["auto_candidate_source_sha_verified"] == 38
    assert stats["holdout_file_sha_overlap"] == 0
    assert stats["approved_synonyms"] == 0


def test_broader_graph_cycle_rejected():
    with pytest.raises(AssertionError, match="cycle"):
        graph_audit([
            {"from":"a","to":"b","type":"BROADER_THAN_CANDIDATE"},
            {"from":"b","to":"a","type":"BROADER_THAN_CANDIDATE"}], {"a","b"})


def test_graph_contradiction_rejected():
    with pytest.raises(AssertionError):
        graph_audit([
            {"from":"a","to":"b","type":"NOT_EQUIVALENT"},
            {"from":"a","to":"b","type":"BROADER_THAN_CANDIDATE"}], {"a","b"})


def test_graph_self_edge_rejected():
    with pytest.raises(AssertionError):
        graph_audit([{"from":"a","to":"a","type":"NOT_EQUIVALENT"}], {"a"})


def test_holdout_fixture_is_frozen_and_source_hash_verified():
    config, labels, records, sha = prepare()
    assert len(config["questions"]) == 4
    assert len(sha) == 64 and len(records)>4
    assert any(s["span_kind"]=="TRAP" for s in labels.values())


def test_bm25_offline_without_embedding_or_api():
    result = offline()
    assert result["paid_api_calls"] == 0
    assert result["live_e3_comparison"] == "NOT_COMPARABLE"
    assert result["synonym_expansion"].startswith("NOT_RUN")
    for method in result["results"].values():
        assert all(row["returned_notice_versions"] == ["C01-source-order-000"] for row in method["queries"])


def test_out_of_sample_snapshot_separated_by_sha_and_round():
    stats = crosscheck()
    assert stats["sample_rounds"] >= 10
    assert stats["training_round_overlap"] == 0
    assert stats["training_file_sha_overlap"] == 0
    assert stats["sample_rounds"] == sum(stats["business_types"].values())


def test_triage_is_not_human_approval():
    import json
    folder = Path(__file__).resolve().parents[2] / "data/domain_lexicon"
    triage = json.loads((folder / "review-triage-v0.2.json").read_text(encoding="utf8"))
    assert triage["approved_synonym_count"] == 0
    assert len(triage["records"]) == 10
    assert all(row["review_status"] == "UNREVIEWED" for row in triage["records"])
