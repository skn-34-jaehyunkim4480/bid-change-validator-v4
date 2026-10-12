"""BCV4-02-002: real-source DRAFT audit is not a model quality evaluation."""
import copy
from pathlib import Path

import pytest
from bideval.draft_source_audit import audit_dataset, inspect_draft_label
from bideval.real_adapter import load_real_cases
import json

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "eval/golden/qualification-real-v0.1"
DRAFT = ROOT / "eval/golden/qualification-label-drafts-v0.1/cases/C01.json"


def test_actual_c01_draft_and_g2_change_are_grounded_but_unapproved():
    report = audit_dataset(DATA, DRAFT)
    assert report["evaluation_status"] == "DRAFT_ONLY_NOT_APPROVED"
    assert report["draft_source_labels"] == 8
    assert report["draft_source_grounded"] == 8
    assert report["draft_selected"] == 8
    assert report["draft_in_32k_context"] == 8
    assert report["model_requirement_precision"] is None
    assert report["model_requirement_recall"] is None
    assert report["evidence_match_rate"] is None
    assert report["wrong_final_verdicts"] is None
    assert report["extractor_calls"] == 0
    assert report["g2_draft_change"] == {
        "notice_no": "R26BK01686455",
        "baseline_quote_present": True,
        "baseline_quote_selected": True,
        "current_exact_quote_absent": True,
        "semantic_removal_approved": False,
        "reuse_retire_eligibility_verified": False,
    }
    c04 = next(x for x in report["versions"] if x["case_id"] == "C04")
    assert c04["context_truncated_chars"] == 3716


def test_false_draft_quote_or_coordinates_are_rejected():
    c01 = load_real_cases(DATA, ["C01"])[0]
    source_by_key = {d.document_key: d for d in c01.spec.documents}
    docs = {d["document_key"]: {**d, "name": source_by_key[d["document_key"]].name}
            for d in c01.documents}
    original = json.loads(DRAFT.read_text(encoding="utf-8"))["source_requirements"][0]
    bad = copy.deepcopy(original)
    bad["raw"] = "원문에 존재하지 않는 참가요건을 만들어냅니다"
    with pytest.raises(ValueError, match="not grounded"):
        inspect_draft_label(bad, docs, [])
    bad = copy.deepcopy(original)
    bad["location"]["block_start"] = -1
    with pytest.raises(ValueError, match="range invalid"):
        inspect_draft_label(bad, docs, [])
    bad = copy.deepcopy(original)
    bad["location"]["paragraph_start"] = 999
    with pytest.raises(ValueError, match="coordinates mismatch"):
        inspect_draft_label(bad, docs, [])


def test_approved_claim_cannot_be_smuggled_into_draft_report(tmp_path):
    data = json.loads(DRAFT.read_text(encoding="utf-8"))
    data["evaluation_eligible"] = True
    p = tmp_path / "misleading.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="evaluation-ineligible"):
        audit_dataset(DATA, p)
