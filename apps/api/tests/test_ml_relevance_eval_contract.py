"""Offline PR-A acceptance gates; synthetic fixtures exercise contracts, NOT ML accuracy."""
from __future__ import annotations
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.ml_recommendations.relevance_eval_contract import (
    SCHEMA, audit, audit_pool, company_fingerprint, make_blind_pool,
    notice_fingerprint, sha, text_sha,
)
from app.ml_recommendations.relevance_eval_inventory import import_title_snapshot


def fixture(tmp_path):
    date = datetime(2026, 9, 1, tzinfo=timezone.utc)
    companies = [{"company_id": f"c-{i}", "profile_origin": "synthetic",
                  "profile_text": f"회사 전문기술 {i}", "industry_codes": [],
                  "product_codes": []} for i in range(13)]
    notices = []
    for i in range(32):
        version = f"v-{i}"
        block = [{"block_index": 0, "text": f"사업 수행 내용 {i}: 테스트용 정보시스템 개발 및 유지보수 과업의 구체적 범위를 설명합니다."}]
        encoded = json.dumps(block, ensure_ascii=False).encode("utf-8")
        (tmp_path / f"{i}.blocks.json").write_bytes(encoded)
        excerpt = block[0]["text"]
        notices.append({
            "notice_id": f"n-{i}", "notice_version_id": version,
            "family_id": f"fam-{i}",
            "posted_at": (date + timedelta(days=(i == 1) + 2 * (i > 1))).isoformat(),
            "title": f"사업 {i}", "task_text": excerpt,
            "body_status": "VERIFIED_TASK", "business_type": "SERVICE",
            "task_evidence": [{"notice_id": f"n-{i}", "notice_version_id": version,
                               "source_file": f"{i}.blocks.json",
                               "document_sha256": hashlib.sha256(encoded).hexdigest(),
                               "excerpt": excerpt, "excerpt_sha256": text_sha(excerpt),
                               "block_refs": [0]}],
        })
    corpus = {"schema_version": SCHEMA, "collected_at": date.isoformat(),
              "family_linkage_status": "CONFIRMED_CLOSED",
              "companies": companies, "notices": notices}
    reviews = []
    for i in range(13):
        if i == 0:
            split, indexes = "train", [0]
        elif i == 1:
            split, indexes = "validation", [1]
        else:
            split, indexes = "test", range(2, 32)
        for j in indexes:
            reviews.append({"company_id": f"c-{i}", "notice_version_id": f"v-{j}",
                            "company_sha256": company_fingerprint(companies[i]),
                            "notice_sha256": notice_fingerprint(notices[j]),
                            "split": split, "grade": 3 if j == 2 else 0,
                            "annotation_basis": "FULL_TASK", "label_source": "gpt_teacher",
                            "reviewer_id": "fixture-not-real-gpt",
                            "rationale": "테스트 계약을 검증하는 더미 설명이며 실제 의미 판정이 아닙니다."})
    labels = {"schema_version": SCHEMA, "corpus_sha256": sha(corpus), "reviews": reviews}
    return corpus, labels


def test_strict_fixture_ready_but_synthetic_only(tmp_path):
    c, labels = fixture(tmp_path)
    result = audit(c, labels, source_root=tmp_path)
    assert result["status"] == "READY_FOR_OFFLINE_EVALUATION"
    assert result["independent_test_queries"] == 11
    assert result["label_count"] == 332
    assert any("Synthetic" in note for note in result["notes"])
    assert result["eligibility_accuracy"] == "NOT_EVALUATED"


def test_no_labels_cannot_claim_accuracy(tmp_path):
    c, _ = fixture(tmp_path)
    assert audit(c, source_root=tmp_path)["status"] == "DATA_ONLY_NOT_EVALUATED"


def test_source_root_is_required_for_provenance(tmp_path):
    c, labels = fixture(tmp_path)
    assert audit(c, labels)["status"] == "NOT_READY"


def test_wrong_source_sha_fails(tmp_path):
    c, labels = fixture(tmp_path)
    c["notices"][0]["task_evidence"][0]["document_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="SHA mismatch"):
        audit(c, source_root=tmp_path)


def test_foreign_notice_source_fails_closed(tmp_path):
    c, _ = fixture(tmp_path)
    c["notices"][0]["task_evidence"][0]["notice_version_id"] = "v-1"
    with pytest.raises(ValueError, match="Cross-notice"):
        audit(c, source_root=tmp_path)


def test_missing_body_is_not_full_task_evaluation(tmp_path):
    c, labels = fixture(tmp_path)
    c["notices"][2]["body_status"] = "MISSING"
    c["notices"][2]["task_text"] = ""
    c["notices"][2]["task_evidence"] = []
    labels["corpus_sha256"] = sha(c)
    with pytest.raises(ValueError, match="fingerprint|Full-task"):
        audit(c, labels, source_root=tmp_path)


def test_cross_split_company_fails(tmp_path):
    c, labels = fixture(tmp_path)
    row = deepcopy(labels["reviews"][0])
    row["notice_version_id"] = "v-3"
    row["notice_sha256"] = notice_fingerprint(c["notices"][3])
    row["split"] = "test"
    labels["reviews"].append(row)
    assert any("Company leakage" in err for err in audit(c, labels, source_root=tmp_path)["errors"])


def test_notice_family_leakage_fails(tmp_path):
    c, labels = fixture(tmp_path)
    c["notices"][2]["family_id"] = c["notices"][0]["family_id"]
    labels["corpus_sha256"] = sha(c)
    for row in labels["reviews"]:
        if row["notice_version_id"] == "v-2":
            row["notice_sha256"] = notice_fingerprint(c["notices"][2])
    result = audit(c, labels, source_root=tmp_path)
    assert any("Notice family leakage" in err for err in result["errors"])


def test_wrong_chronology_fails(tmp_path):
    c, labels = fixture(tmp_path)
    c["notices"][0]["posted_at"] = (datetime(2026, 11, 1, tzinfo=timezone.utc)).isoformat()
    labels["corpus_sha256"] = sha(c)
    assert any("chronological" in err for err in audit(c, labels, source_root=tmp_path)["errors"])


def test_pseudolabel_prohibited(tmp_path):
    c, labels = fixture(tmp_path)
    labels["reviews"][0]["label_source"] = "pseudo_capability_overlap"
    with pytest.raises(ValueError, match="Pseudo-label"):
        audit(c, labels, source_root=tmp_path)


def test_unreviewed_and_title_only_rejected(tmp_path):
    c, labels = fixture(tmp_path)
    labels["reviews"][0]["annotation_basis"] = "TITLE_ONLY"
    with pytest.raises(ValueError, match="Title-only"):
        audit(c, labels, source_root=tmp_path)


def test_minimum_test_company_count(tmp_path):
    c, labels = fixture(tmp_path)
    labels["reviews"] = [x for x in labels["reviews"] if x["company_id"] != "c-12"]
    result = audit(c, labels, source_root=tmp_path)
    assert "READY_FOR_OFFLINE_EVALUATION" == result["status"]  # still 10 test firms
    labels["reviews"] = [x for x in labels["reviews"] if x["company_id"] != "c-11"]
    result = audit(c, labels, source_root=tmp_path)
    assert any("10+" in err for err in result["errors"])


def test_blind_pool_combines_independent_results(tmp_path):
    c, _ = fixture(tmp_path)
    pool = {"corpus_sha256": sha(c), "runs": [
        {"model": "bm25", "universe_sha256": sha(sorted(n["notice_version_id"] for n in c["notices"])),
         "retrieval_mode": "INDEPENDENT_FULL_CORPUS", "rankings": {"c-2": ["v-2", "v-3"]}},
        {"model": "embedding", "universe_sha256": sha(sorted(n["notice_version_id"] for n in c["notices"])),
         "retrieval_mode": "INDEPENDENT_FULL_CORPUS", "rankings": {"c-2": ["v-3", "v-4"]}},
    ]}
    blind = make_blind_pool(pool, c)
    assert [x["notice_version_id"] for x in blind["candidates"]["c-2"]] == ["v-2", "v-3", "v-4"]
    assert "bm25" not in json.dumps(blind)
    pool["runs"][1]["retrieval_mode"] = "BM25_PREFILTERED"
    assert audit_pool(pool, c)["errors"]


def test_official_code_only_exact_match():
    snapshot = {"companies": [{"company_id": "c1", "industries": [
        {"code": "0001", "name": "토목공사업"},
        {"code": "9999", "name": "비슷한 토목"}], "performances": [], "staff_roles": []}],
        "notices": [{"notice_id": "n1", "notice_version_id": "v1", "bid_notice_no": "R26BK01",
                     "title": "토목공사", "posted_at": "2026-10-13T00:00:00Z", "business_type": "CONSTRUCTION"}]}
    corpus = import_title_snapshot(snapshot, master_industries={"0001": "토목공사업"},
                                   snapshot_sha256="source", collected_at="2026-10-13T00:00:00Z")
    assert corpus["master_match_count"] == 1
    assert corpus["master_unmatched_count"] == 1
    assert audit(corpus)["status"] == "NOT_READY"
