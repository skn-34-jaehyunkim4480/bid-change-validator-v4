"""Offline J01–J32/public-notice *pseudo-label* ranking experiment.

This checks training/inference plumbing, not company recommendation accuracy.
The rule that creates labels uses title/capability overlap, so its test labels
are not independent human judgments and cannot approve a Champion model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .dataset import audit
from .real_dataset import family_map


def _normalized(value: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", (value or "").lower())


def _trigrams(value: str) -> set[str]:
    return {value[i:i + 3] for i in range(max(0, len(value) - 2))}


def _capabilities(company: dict) -> list[str]:
    phrases = [item.get("name") or "" for item in company["industries"]]
    phrases += company["certifications"] + company["performances"]
    phrases += [item.get("role") or "" for item in company["staff_roles"]]
    return sorted({_normalized(s) for s in phrases if len(_normalized(s)) >= 4})


def pseudo_grade(company: dict, notice: dict) -> tuple[int, str]:
    """A bounded lexical proxy; no positive is invented for unknown profiles."""
    title = _normalized(notice["title"])
    title_grams = _trigrams(title)
    best = (0, 0.0, "")
    for phrase in _capabilities(company):
        common = len(_trigrams(phrase) & title_grams)
        ratio = common / max(1, min(len(_trigrams(phrase)), len(title_grams)))
        if (common, ratio) > best[:2]:
            best = (common, ratio, phrase)
        if phrase in title:
            return 3, "exact_capability_phrase"
    common, ratio, _ = best
    if common >= 3 and ratio >= 0.30:
        return 3, "strong_capability_trigram_overlap"
    if common >= 1:
        return 2, "weak_capability_trigram_overlap"
    title_bigrams = {title[i:i + 2] for i in range(max(0, len(title) - 1))}
    if any(len({phrase[i:i + 2] for i in range(len(phrase) - 1)} & title_bigrams) >= 2
           for phrase in _capabilities(company)):
        return 1, "weak_capability_bigram_overlap"
    return 0, "no_capability_evidence"


def _notice_partitions(notices: list[dict], *, seed: int, max_per_date: int = 100):
    ids = {n["notice_id"] for n in notices}
    edges = [(n["notice_id"], previous)
             for n in notices for previous in n["previous_notice_ids"] if previous in ids]
    families = family_map(notices, edges)
    newest = {}
    for notice in notices:
        family = families[notice["notice_id"]]
        key = (notice["posted_at"] or "", notice["notice_id"])
        if family not in newest or key > (newest[family]["posted_at"] or "", newest[family]["notice_id"]):
            newest[family] = notice
    by_date = defaultdict(list)
    for family, notice in newest.items():
        if notice["posted_at"]:
            by_date[notice["posted_at"][:10]].append((family, notice))
    dates = sorted(by_date)
    if len(dates) < 3:
        raise ValueError("At least three independent posting dates are required")
    selected = []
    for date in dates:
        group = sorted(by_date[date], key=lambda item: hashlib.sha256(
            f"{seed}|{item[0]}".encode()).hexdigest())[:max_per_date]
        selected.extend(group)
    counts = Counter(n["posted_at"][:10] for _, n in selected)
    total = len(selected)
    running = 0
    train_end = val_end = None
    for index, date in enumerate(dates[:-2]):
        running += counts[date]
        if train_end is None and running >= total * .60:
            train_end = index + 1
        if train_end is not None and running >= total * .80:
            val_end = index + 1
            break
    train_end = train_end or max(1, len(dates) - 2)
    val_end = val_end or min(len(dates) - 1, train_end + 1)
    if not (0 < train_end < val_end < len(dates)):
        raise ValueError("Temporal holdout cannot be separated by posting date")
    date_split = {date: ("train" if i < train_end else
                         "validation" if i < val_end else "test")
                  for i, date in enumerate(dates)}
    return [(family, notice, date_split[notice["posted_at"][:10]])
            for family, notice in selected], date_split


def build_pairs(snapshot: dict, *, seed: int = 42, max_per_date: int = 100):
    companies = snapshot["companies"]
    if len(companies) != 32 or len({c["company_id"] for c in companies}) != 32:
        raise ValueError("Expected exactly 32 distinct seeded Golden companies")
    notice_rows, date_split = _notice_partitions(snapshot["notices"], seed=seed,
                                                  max_per_date=max_per_date)
    by_split = {split: [(family, n) for family, n, part in notice_rows if part == split]
                for split in ("train", "validation", "test")}
    if min(map(len, by_split.values())) < 5:
        raise ValueError("Each chronological notice partition needs at least five families")
    # Split companies independently. Assignment is deterministic and does not
    # inspect pseudo grades, avoiding a test-set selection based on labels.
    order = sorted(companies, key=lambda c: hashlib.sha256(
        f"{seed}|{c['company_id']}".encode()).hexdigest())
    company_split = {c["company_id"]: ("train" if i < 22 else
                                      "validation" if i < 27 else "test")
                     for i, c in enumerate(order)}
    rows = []
    no_positive = []
    for company in companies:
        split = company_split[company["company_id"]]
        profile = " ".join([company["name"], company.get("region_name") or ""] +
                           [item.get("name") or "" for item in company["industries"]] +
                           company["certifications"] + company["performances"] +
                           [item.get("role") or "" for item in company["staff_roles"]])
        group = []
        for family, notice in by_split[split]:
            grade, reason = pseudo_grade(company, notice)
            group.append({
                "pair_id": hashlib.sha256((company["company_id"] + "|" +
                                           notice["notice_version_id"]).encode()).hexdigest()[:20],
                "company_id": company["company_id"],
                "query_id": "company:" + company["company_id"],
                "query_family_id": "company:" + company["company_id"],
                "query_text": profile, "candidate_family_id": family,
                "notice_id": notice["notice_id"], "notice_version_id": notice["notice_version_id"],
                "notice_text": notice["title"], "notice_no": notice["bid_notice_no"],
                "business_type": notice["business_type"], "posted_at": notice["posted_at"],
                "split": split, "label": grade, "label_source": "pseudo_capability_overlap",
                "pseudo_reason": reason,
            })
        if not any(row["label"] >= 2 for row in group):
            no_positive.append(company["company_id"])
        else:
            rows.extend(group)
    if not rows or not audit(rows)["passed"]:
        raise ValueError("No leak-free pseudo-labelled company/notices pairs")
    usable = Counter(r["split"] for r in rows if r["label"] >= 2)
    if not all(usable[s] for s in ("train", "validation", "test")):
        raise ValueError("All splits need at least one pseudo-positive; no metrics produced")
    report = {
        "company_count": len(companies), "trainable_company_count": len(companies) - len(no_positive),
        "unlabelled_company_count": len(no_positive), "selected_notice_families": len(notice_rows),
        "pairs": len(rows), "label_counts": dict(Counter(str(r["label"]) for r in rows)),
        "query_counts": {s: len({r["company_id"] for r in rows if r["split"] == s})
                         for s in ("train", "validation", "test")},
        "notice_counts": {s: len(by_split[s]) for s in by_split},
        "date_ranges": {s: [min(d for d, part in date_split.items() if part == s),
                            max(d for d, part in date_split.items() if part == s)]
                        for s in by_split},
        "leakage": audit(rows),
        "label_policy": "PSEUDO only; independent relevance accuracy NOT_RUN",
    }
    return rows, report


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(snapshot_path: Path, out: Path, *, seed: int = 42):
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    rows, report = build_pairs(snapshot, seed=seed)
    out.mkdir(parents=True, exist_ok=False)
    pairs = out / "pairs.jsonl"
    with pairs.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    manifest = {
        "schema": "bidcheck-synthetic-company-pseudo-v1",
        "dataset_version": snapshot_path.parent.name,
        "seed": seed, "reviewed_labels": 0,
        "synthetic_labels": len(rows), "evaluation_scope": "PSEUDO_LABELED_RULE_IMITATION",
        "snapshot_sha256": _sha(snapshot_path), "sha256": {"pairs.jsonl": _sha(pairs)},
        **report,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(prepare(args.snapshot, args.out, seed=args.seed),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
