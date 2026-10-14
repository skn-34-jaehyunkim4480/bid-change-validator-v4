"""BCV4-03-001: no silent eligibility equivalence or contaminated provenance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import build, context_role_candidate, document_paths, load_seeds, phrase_pattern, relation
from discover import discover
from validate import validate


def test_seed_concepts_are_stable_and_unique():
    seeds = load_seeds()
    assert len(seeds) == 50
    assert len({s["concept_id"] for s in seeds}) == len(seeds)
    assert all(s["forms"] for s in seeds)


def test_no_false_substring_equivalence():
    assert phrase_pattern("소기업").search("중소기업 확인서") is None
    assert phrase_pattern("등록").search("사업자등록증") is None
    assert phrase_pattern("본점 소재지").search("본점 소재지에 위치")


def test_only_whitespace_form_is_orthographic():
    assert relation("본점 소재지", "본점소재지") == "ORTHOGRAPHIC_VARIANT_CANDIDATE"
    assert relation("수행실적", "용역실적") == "RELATED_CANDIDATE"
    assert relation("소기업", "소기업") == "PREFERRED_LABEL"


def test_holdout_is_never_used_for_building():
    root = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError, match="non-holdout"):
        document_paths(root / "eval/golden/qualification-real-v0.1")


def test_snapshot_evidence_references_and_review_guard():
    stats = validate()
    assert stats["unique_concepts"] == 50
    assert stats["evidence_samples_verified"] >= 50
    assert stats["auto_candidates"] > 0


def test_build_produces_deterministic_output(tmp_path):
    src = tmp_path / "synthetic"
    src.mkdir()
    # This test does not use a golden holdout and cannot change the production catalog.
    (src / "N00-000").mkdir()
    data = [{"block_index": 0, "text": "중소기업 확인서 또는 소기업 확인서를 제출"}]
    (src / "N00-000" / "test.blocks.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    a = build(src, load_seeds())
    b = build(src, load_seeds())
    assert a == b
    assert all(x["review_status"] == "UNREVIEWED" and not x["search_expansion_approved"] for x in a["expression_records"])
    rows = {(x["concept_id"], x["surface"]) for x in a["expression_records"]}
    assert ("sm-business", "중소기업") in rows
    assert ("small-business", "소기업") in rows


def test_auto_discovery_never_upgrades_to_approved(tmp_path):
    src = tmp_path / "synthetic"
    src.mkdir()
    for notice in ("N1-000", "N2-000"):
        folder = src / notice
        folder.mkdir()
        (folder / "doc.blocks.json").write_text(json.dumps([{"block_index": 1, "text": "법인인감증명서 제출"}], ensure_ascii=False), encoding="utf-8")
    auto = discover(src, min_notices=2)
    assert auto["records"][0]["surface"] == "법인인감증명서"
    assert auto["records"][0]["review_status"] == "UNREVIEWED"


def test_payment_context_does_not_turn_into_qualification():
    assert context_role_candidate("분기별 기술지도 수행실적에 따라 용역대금을 지급한다") == "PAYMENT_OR_OPERATIONS_CANDIDATE"
    assert context_role_candidate("본점 소재지에 입찰공고일 전일부터 계속 둔 업체") == "QUALIFICATION_CANDIDATE"
