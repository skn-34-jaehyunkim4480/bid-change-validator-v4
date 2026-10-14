"""Read-only inventory and safe title-only import of frozen local BidCheck data.

This tool deliberately does not infer linkage between historical Golden documents
and a separate current-notice snapshot by text/title similarity.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
from .relevance_eval_contract import SCHEMA, audit


def _master_codes(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["code"]: row["name"] for row in csv.DictReader(f)
                if row.get("code") and row.get("active", "Y") == "Y"}


def import_title_snapshot(snapshot: dict, *, master_industries: dict, snapshot_sha256: str,
                          collected_at: str):
    company_rows, notices = [], []
    matched = unmatched = 0
    for c in snapshot["companies"]:
        valid_industries = []
        names = []
        for entry in c.get("industries", []):
            code, name = str(entry.get("code", "")), entry.get("name", "")
            names.append(name)
            if code in master_industries and name == master_industries[code]:
                valid_industries.append({"code": code, "name": name, "source": "industry_codes.csv"})
                matched += 1
            else:
                unmatched += 1
        profile = "; ".join(names + c.get("performances", []) +
                            [r.get("role", "") for r in c.get("staff_roles", [])]).strip("; ")
        if not profile:
            profile = "기업 역량 정보 없음"   # Cannot imply known capability.
        company_rows.append({"company_id": c["company_id"], "profile_origin": "synthetic",
                             "profile_text": profile, "industry_codes": valid_industries,
                             "product_codes": []})
    for n in snapshot["notices"]:
        # Confirmed family edges from snapshot would be processed separately.
        # Without closure, never declare family independence across versions.
        family = str(n["bid_notice_no"]).split("-")[0]
        notices.append({"notice_id": n["notice_id"],
                        "notice_version_id": n["notice_version_id"],
                        "family_id": family, "posted_at": n["posted_at"],
                        "title": n["title"], "task_text": "", "task_evidence": [],
                        "body_status": "MISSING", "business_type": n.get("business_type")})
    return {"schema_version": SCHEMA, "collected_at": collected_at,
            "family_linkage_status": "UNVERIFIED",
            "source_snapshot_sha256": snapshot_sha256,
            "master_match_count": matched, "master_unmatched_count": unmatched,
            "companies": company_rows, "notices": notices}


def inventory(snapshot_path: Path, golden_dir: Path, master_path: Path, output_dir: Path):
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8-sig"))
    master = _master_codes(master_path)
    golden = sorted(p for p in golden_dir.iterdir() if p.is_dir())
    golden_numbers = {p.name.split("-")[0] for p in golden}
    snapshot_numbers = {str(n["bid_notice_no"]).split("-")[0] for n in snapshot["notices"]}
    golden_files = list(golden_dir.rglob("*.blocks.json"))
    corpus = import_title_snapshot(snapshot, master_industries=master,
                                   snapshot_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
                                   collected_at="2026-10-13T00:00:00+00:00")
    check = audit(corpus)
    report = {
        "scope": "offline frozen snapshot vs repository Golden extracted blocks",
        "source_snapshot": str(snapshot_path.resolve()),
        "source_snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "source_golden": str(golden_dir.resolve()),
        "snapshot_company_count": len(snapshot["companies"]),
        "snapshot_notice_count": len(snapshot["notices"]),
        "golden_notice_count": len(golden),
        "golden_extracted_files": len(golden_files),
        "linked_notice_numbers": len(snapshot_numbers & golden_numbers),
        "full_task_notice_count_in_snapshot": check["body_coverage"].get("VERIFIED_TASK", 0),
        "matched_official_industry_codes": corpus["master_match_count"],
        "unmatched_industry_codes": corpus["master_unmatched_count"],
        "assessment": "BLOCKED: title-only snapshot cannot be promoted to full-task evaluation",
        "linkage_policy": "Exact notice/version/document provenance; never fuzzy title match",
        "independent_labels": "NOT_AVAILABLE for this full-task corpus",
        "production_data_changed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "title_only_corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "corpus_audit.json").write_text(
        json.dumps(check, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "source_inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--golden-root", type=Path, required=True)
    parser.add_argument("--industry-master", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inventory(args.snapshot, args.golden_root,
                               args.industry_master, args.out),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
