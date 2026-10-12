import json
from pathlib import Path

import pytest

from app.ml_recommendations.gpt_teacher import build, input_fingerprint


def _fixture(tmp_path):
    companies = [
        {"company_id": f"company-{i}", "name": f"synthetic J0{i}",
         "region_name": "서울", "industries": [{"name": "IT" if i == 1 else "건설"}],
         "certifications": [], "performances": [], "staff_roles": []}
        for i in range(1, 4)
    ]
    notices = [
        {"notice_id": f"notice-{i}", "notice_version_id": f"version-{i}",
         "title": ["IT 소프트웨어 개발", "식자재 납품", "건설사업 관리",
                   "소프트웨어 유지보수"][i],
         "bid_notice_no": f"2026-00{i}", "business_type": "SERVICE",
         "posted_at": f"2026-10-{i+10:02d} 09:00:00+00",
         "previous_notice_ids": []}
        for i in range(4)
    ]
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"companies": companies, "notices": notices}), encoding="utf-8")
    pairs = [(0, 0, 3, "train"), (0, 1, 0, "train"),
             (1, 2, 2, "validation"), (2, 3, 1, "test")]
    def annotation(ci, ni, grade, split):
        c, n = companies[ci], notices[ni]
        return {"company_id": c["company_id"], "notice_id": n["notice_id"],
                "notice_version_id": n["notice_version_id"],
                "label_source": "gpt_teacher", "teacher_model": "gpt-6",
                "label_schema_version": "v1", "label_0_3": grade, "split": split,
                "input_fingerprint": input_fingerprint(c, n), "confidence": None,
                "rationale": "합성회사 업무와 제목상 과업 범위를 비교한 독립 판단입니다."}
    annotations = [annotation(*p) for p in pairs]
    file = tmp_path / "annotations.jsonl"
    def save():
        file.write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in annotations),
                        encoding="utf-8")
    save()
    return snapshot, file, annotations, save, annotation


def test_build_teacher_dataset_keeps_provenance_and_no_approval(tmp_path):
    snapshot, path, _, _, _ = _fixture(tmp_path)
    report = build(snapshot, path, tmp_path / "out")
    assert report["graded_pairs"] == 4
    assert report["label_counts"] == {"0": 1, "1": 1, "2": 1, "3": 1}
    assert report["human_reviewed_labels"] == report["reviewed_labels"] == 0
    assert report["champion_eligible"] is False
    rows = [json.loads(line) for line in (tmp_path/"out"/"pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(r["label_source"] for r in rows) == {"gpt_teacher"}
    assert report["leakage"]["passed"]


def test_reject_stale_input(tmp_path):
    snapshot, path, ann, save, _ = _fixture(tmp_path)
    ann[0]["input_fingerprint"] = "f" * 64
    save()
    with pytest.raises(ValueError, match="fingerprint"):
        build(snapshot, path, tmp_path / "out")


def test_reject_label_spoofing(tmp_path):
    snapshot, path, ann, save, _ = _fixture(tmp_path)
    ann[0]["label_source"] = "human_reviewed"
    save()
    with pytest.raises(ValueError, match="origin"):
        build(snapshot, path, tmp_path / "out")


def test_reject_duplicate_judgment(tmp_path):
    snapshot, path, ann, save, _ = _fixture(tmp_path)
    ann.append(dict(ann[0]))
    save()
    with pytest.raises(ValueError, match="Duplicate"):
        build(snapshot, path, tmp_path / "out")


def test_reject_cross_split_same_notice_family(tmp_path):
    snapshot, path, ann, save, make = _fixture(tmp_path)
    ann[3] = make(2, 0, 1, "test")
    save()
    with pytest.raises(ValueError, match="leakage"):
        build(snapshot, path, tmp_path / "out")


def test_reject_unmarked_hold_and_allow_marked_hold(tmp_path):
    snapshot, path, ann, save, _ = _fixture(tmp_path)
    ann[3]["label_0_3"] = None
    save()
    with pytest.raises(ValueError, match="grading"):
        build(snapshot, path, tmp_path / "out")
    ann[3]["annotation_status"] = "held"
    save()
    with pytest.raises(ValueError, match="train/validation/test"):
        build(snapshot, path, tmp_path / "out")
