"""Validate explicit GPT Teacher judgments and create an isolated offline ranker dataset.

This module does NOT generate labels: model-written annotations are provided as
private input, and no API/LLM inference, AWS writes, or Champion promotion occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .dataset import audit
from .real_dataset import family_map


SPLITS = ("train", "validation", "test")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def input_fingerprint(company: dict, notice: dict) -> str:
    """SHA-256 of the complete frozen snapshot records used for a judgment."""
    return canonical_hash({"company": company, "notice": notice, "schema": "gpt-teacher-v1"})


def query_text(company: dict) -> str:
    fields = [company["name"], company.get("region_name") or ""]
    fields += [item.get("name", "") for item in company.get("industries", [])]
    fields += list(company.get("certifications", []))
    fields += list(company.get("performances", []))
    fields += [item.get("role", "") for item in company.get("staff_roles", [])]
    return " ".join(str(field) for field in fields if field)


def build(snapshot_path: Path, annotations_path: Path, out: Path) -> dict:
    snapshot_path, annotations_path, out = map(Path, (snapshot_path, annotations_path, out))
    snap_bytes = snapshot_path.read_bytes()
    snap = json.loads(snap_bytes)
    companies = {c["company_id"]: c for c in snap["companies"]}
    notices = {n["notice_version_id"]: n for n in snap["notices"]}
    ids = {n["notice_id"] for n in snap["notices"]}
    edges = [(n["notice_id"], prev) for n in snap["notices"]
             for prev in n.get("previous_notice_ids", []) if prev in ids]
    families = family_map(snap["notices"], edges)
    rows, held, labels, seen, company_splits = [], [], [], set(), {}
    for line_no, line in enumerate(annotations_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            a = json.loads(line)
            company, notice = companies[a["company_id"]], notices[a["notice_version_id"]]
        except (KeyError, ValueError, TypeError) as err:
            raise ValueError(f"Unknown/malformed frozen input on line {line_no}: {err}") from err
        key = (a["company_id"], a["notice_version_id"])
        if key in seen:
            raise ValueError(f"Duplicate Teacher judgment on line {line_no}")
        seen.add(key)
        if a.get("notice_id") != notice["notice_id"] or a.get("label_source") != "gpt_teacher":
            raise ValueError(f"Incorrect notice identity/label origin on line {line_no}")
        if a.get("input_fingerprint") != input_fingerprint(company, notice):
            raise ValueError(f"Stale input fingerprint on line {line_no}")
        if a.get("label_schema_version") != "v1" or not str(a.get("teacher_model") or "").strip():
            raise ValueError(f"Missing Teacher model/schema provenance on line {line_no}")
        if not isinstance(a.get("rationale"), str) or len(a["rationale"].strip()) < 12:
            raise ValueError(f"Missing substantive rationale on line {line_no}")
        if a.get("split") not in SPLITS:
            raise ValueError(f"Invalid fixed split on line {line_no}")
        prior = company_splits.setdefault(a["company_id"], a["split"])
        if prior != a["split"]:
            raise ValueError(f"Company crosses splits on line {line_no}")
        if a.get("confidence") is not None and (
            isinstance(a["confidence"], bool) or not isinstance(a["confidence"], (float, int))
            or not 0 <= a["confidence"] <= 1
        ):
            raise ValueError(f"Invalid confidence on line {line_no}")
        label = a.get("label_0_3")
        if label is None and a.get("annotation_status") == "held":
            held.append(a)
            continue
        if type(label) is not int or label not in (0, 1, 2, 3):
            raise ValueError(f"Invalid grading (or undeclared HOLD) on line {line_no}")
        if a.get("annotation_status") not in (None, "graded"):
            raise ValueError(f"Invalid status on line {line_no}")
        labels.append(a)
        rows.append({
            "pair_id": canonical_hash(key)[:20],
            "company_id": a["company_id"], "query_id": "company:" + a["company_id"],
            "query_family_id": "company:" + a["company_id"],
            "query_text": query_text(company),
            "candidate_family_id": families[notice["notice_id"]],
            "notice_id": notice["notice_id"],
            "notice_version_id": notice["notice_version_id"],
            "notice_no": notice["bid_notice_no"], "notice_text": notice["title"],
            "business_type": notice["business_type"], "posted_at": notice.get("posted_at"),
            "split": a["split"], "label": label, "label_source": "gpt_teacher",
            "input_fingerprint": a["input_fingerprint"],
            "teacher_model": a["teacher_model"],
        })
    leak = audit(rows)
    if not leak["passed"]:
        raise ValueError(f"Cross-company/notice-family split leakage: {leak}")
    if len(rows) == 0 or len(set(r["split"] for r in rows)) != 3:
        raise ValueError("Need labeled rows in train/validation/test")
    if not any(r["label"] >= 2 for r in rows if r["split"] == "train"):
        raise ValueError("Training split needs judged positive relevance")
    if not any(r["label"] == 0 for r in rows if r["split"] == "train"):
        raise ValueError("Training split needs judged negative relevance")

    date_ranges = {}
    for split in SPLITS:
        dates = sorted(str(r["posted_at"]) for r in rows
                       if r["split"] == split and r.get("posted_at"))
        date_ranges[split] = [dates[0], dates[-1]] if dates else None
    chronological = all(date_ranges[s] for s in SPLITS) and (
        date_ranges["train"][-1] <= date_ranges["validation"][0]
        and date_ranges["validation"][-1] <= date_ranges["test"][0]
    )
    out.mkdir(parents=True, exist_ok=True)
    def write_jsonl(path, objects):
        path.write_text("".join(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n"
                                for obj in objects), encoding="utf-8")
    write_jsonl(out / "pairs.jsonl", rows)
    write_jsonl(out / "teacher_labels.jsonl", labels + held)
    counts = Counter(str(r["label"]) for r in rows)
    manifest = {
        "dataset_version": "gpt-teacher-v1",
        "evaluation_scope": "GPT_TEACHER_IMITATION_ONLY",
        "source_company_count": len(companies), "source_notice_count": len(notices),
        "graded_pairs": len(rows), "held_pairs": len(held),
        "label_counts": {str(i): counts[str(i)] for i in range(4)},
        "split_counts": dict(Counter(r["split"] for r in rows)),
        "company_split_counts": {s: len({r["company_id"] for r in rows if r["split"] == s})
                                 for s in SPLITS},
        "candidate_family_counts": {s: len({r["candidate_family_id"] for r in rows
                                           if r["split"] == s}) for s in SPLITS},
        "temporal_ranges": date_ranges,
        "strict_temporal_holdout": bool(chronological),
        "leakage": leak, "human_reviewed_labels": 0, "reviewed_labels": 0, "champion_eligible": False,
        "precision_10_goal_eligible": bool(chronological),
        "notices_are_title_only": True,
        "sha256": {"snapshot.json": hashlib.sha256(snap_bytes).hexdigest(),
                   "annotations.jsonl": hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
                   "pairs.jsonl": hashlib.sha256((out/"pairs.jsonl").read_bytes()).hexdigest(),
                   "teacher_labels.jsonl": hashlib.sha256((out/"teacher_labels.jsonl").read_bytes()).hexdigest()},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.snapshot, args.annotations, args.out),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
