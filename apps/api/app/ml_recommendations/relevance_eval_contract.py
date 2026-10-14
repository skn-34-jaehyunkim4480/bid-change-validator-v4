"""Offline data/review contract for business relevance; NO eligibility decisions.

No network, production database writes, model training, or generated labels.
Unjudged retrieval results are NEVER treated as grade zero.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "bidcheck-business-relevance-v1"
SPLITS = ("train", "validation", "test")
ACCEPTED_LABEL_SOURCES = {"gpt_teacher", "human_reviewed"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _datetime(value: str):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing posted_at or collected_at")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("naive timestamp is prohibited")
    return parsed.astimezone(timezone.utc)


def _require_sha(value, field):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"Invalid {field} SHA256")


def _ident(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    return value


def notice_fingerprint(notice: dict) -> str:
    """Label becomes stale whenever title, task, provenance or version changes."""
    return sha({key: notice[key] for key in (
        "notice_id", "notice_version_id", "family_id", "title", "task_text",
        "body_status", "task_evidence")})


def company_fingerprint(company: dict) -> str:
    return sha({key: company[key] for key in (
        "company_id", "profile_origin", "profile_text", "industry_codes", "product_codes")})


def audit(corpus: dict, labels: dict | None = None, pool: dict | None = None,
          *, source_root: str | Path | None = None, minimum_test_queries: int = 10, minimum_test_judgments: int = 30) -> dict:
    """Fail closed; READY requires provenance, non-leaky splits and blind reviews."""
    errors, notes = [], []
    if corpus.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported corpus schema")
    _datetime(corpus["collected_at"])
    companies, notices = corpus["companies"], corpus["notices"]
    if not companies or not notices:
        raise ValueError("Empty corpus")
    c_by_id, n_by_version = {}, {}
    if corpus.get("family_linkage_status") != "CONFIRMED_CLOSED":
        errors.append("Confirmed notice-family relation closure unavailable")
    body_counts = Counter()
    checked_sources = {}
    for c in companies:
        cid = _ident(c["company_id"], "company_id")
        if cid in c_by_id:
            raise ValueError("Duplicate company ID")
        if c.get("profile_origin") not in {"synthetic", "verified_real"}:
            raise ValueError("Company origin must be explicit")
        _ident(c["profile_text"], "profile_text")
        if not isinstance(c["industry_codes"], list) or not isinstance(c["product_codes"], list):
            raise ValueError("Codes must be lists; unreviewed synonyms are not codes")
        c_by_id[cid] = c
    for n in notices:
        for field in ("notice_id", "notice_version_id", "family_id", "title"):
            _ident(n[field], field)
        version = n["notice_version_id"]
        if version in n_by_version:
            raise ValueError("Duplicate notice version")
        _datetime(n["posted_at"])
        if n["body_status"] not in {"VERIFIED_TASK", "MISSING", "UNVERIFIED"}:
            raise ValueError("Unknown task body status")
        task = n.get("task_text")
        provenance = n.get("task_evidence")
        if not isinstance(task, str) or not isinstance(provenance, list):
            raise ValueError("Task text/evidence must be explicit")
        if n["body_status"] == "VERIFIED_TASK":
            if len(task.strip()) < 30 or not provenance:
                raise ValueError("Verified task requires actual body and evidence")
            for e in provenance:
                if e.get("notice_id") != n["notice_id"] or e.get("notice_version_id") != version:
                    raise ValueError("Cross-notice or cross-version task provenance")
                _require_sha(e.get("document_sha256"), "document")
                _require_sha(e.get("excerpt_sha256"), "excerpt")
                if not isinstance(e.get("block_refs"), list) or not e["block_refs"]:
                    raise ValueError("Task evidence needs source block refs")
            if source_root is None:
                errors.append("Document provenance not verified: --source-root required")
            else:
                root = Path(source_root).resolve()
                for e in provenance:
                    rel = Path(e.get("source_file", ""))
                    if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".json":
                        raise ValueError("Unsafe or absent block extraction source path")
                    path = (root / rel).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        raise ValueError("Source extraction file not found under source root")
                    if path not in checked_sources:
                        raw = path.read_bytes()
                        checked_sources[path] = (hashlib.sha256(raw).hexdigest(),
                                                 json.loads(raw.decode("utf-8-sig")))
                    actual_sha, blocks = checked_sources[path]
                    if e["document_sha256"] != actual_sha:
                        raise ValueError("Extraction file SHA mismatch")
                    excerpt = e.get("excerpt", "")
                    if not excerpt or excerpt not in task or text_sha(excerpt) != e["excerpt_sha256"]:
                        raise ValueError("Task excerpt SHA/text mismatch")
                    if not any(excerpt in b.get("text", "") and b.get("block_index") in e["block_refs"]
                               for b in blocks):
                        raise ValueError("Excerpt not found in cited extraction blocks")
        elif task or provenance:
            raise ValueError("Title-only/unverified body may not be promoted to task evidence")
        body_counts[n["body_status"]] += 1
        n_by_version[version] = n
    report = {
        "schema_version": SCHEMA, "corpus_sha256": sha(corpus),
        "company_count": len(companies), "notice_count": len(notices),
        "body_coverage": dict(body_counts), "label_count": 0,
        "independent_test_queries": 0, "test_judgments_by_company": {},
        "errors": errors, "notes": notes, "status": "DATA_ONLY_NOT_EVALUATED",
        "eligibility_accuracy": "NOT_EVALUATED",
    }
    if not labels:
        notes.append("No independently reviewed labels; ranking metrics prohibited")
        report["status"] = "NOT_READY" if errors else "DATA_ONLY_NOT_EVALUATED"
        return report
    if labels.get("schema_version") != SCHEMA or labels.get("corpus_sha256") != sha(corpus):
        raise ValueError("Review file schema/corpus fingerprint mismatch")
    reviews = labels.get("reviews", [])
    if not reviews:
        errors.append("No independent GPT/human labels")
    seen, split_companies, split_families, split_dates = set(), defaultdict(set), defaultdict(set), defaultdict(list)
    judged_by_query = Counter()
    positives, negatives = Counter(), Counter()
    for row in reviews:
        cid = row["company_id"]
        version = row["notice_version_id"]
        pair = (cid, version)
        if pair in seen:
            raise ValueError("Duplicate company/notice judgment")
        seen.add(pair)
        if cid not in c_by_id or version not in n_by_version:
            raise ValueError("Review references unknown company or notice version")
        c, n = c_by_id[cid], n_by_version[version]
        split = row.get("split")
        if split not in SPLITS:
            raise ValueError("Unrecognized review split")
        if row.get("label_source") not in ACCEPTED_LABEL_SOURCES:
            raise ValueError("Pseudo-labels cannot enter independent evaluation")
        if type(row.get("grade")) is not int or row["grade"] not in (0, 1, 2, 3):
            raise ValueError("Grade must be independent integer 0..3")
        if len(row.get("rationale", "").strip()) < 12:
            raise ValueError("Review requires substantive rationale")
        if row.get("annotation_basis") != "FULL_TASK":
            raise ValueError("Title-only review cannot enter full-task evaluation")
        if row.get("company_sha256") != company_fingerprint(c) or row.get("notice_sha256") != notice_fingerprint(n):
            raise ValueError("Stale or corrupted review input fingerprint")
        if n["body_status"] != "VERIFIED_TASK":
            raise ValueError("Full-task judgment without verified task body")
        if row.get("reviewer_id", "").strip() == "":
            raise ValueError("Anonymous reviewer not accepted")
        split_companies[split].add(cid)
        split_families[split].add(n["family_id"])
        # Also prevent revisions assigned to different splits.
        split_families[split].add("notice:" + n["notice_id"])
        split_dates[split].append(_datetime(n["posted_at"]))
        if split == "test":
            judged_by_query[cid] += 1
            if row["grade"] >= 2:
                positives[cid] += 1
            else:
                negatives[cid] += 1
    for i, left in enumerate(SPLITS):
        for right in SPLITS[i + 1:]:
            if split_companies[left] & split_companies[right]:
                errors.append(f"Company leakage between {left} and {right}")
            if split_families[left] & split_families[right]:
                errors.append(f"Notice family leakage between {left} and {right}")
    if not all(split_dates[s] for s in SPLITS):
        errors.append("Train/validation/test all need independently reviewed pairs")
    elif not (max(split_dates["train"]) < min(split_dates["validation"])
              and max(split_dates["validation"]) < min(split_dates["test"])):
        errors.append("Strict chronological train < validation < test holdout violated")
    if len(judged_by_query) < minimum_test_queries:
        errors.append(f"Test needs {minimum_test_queries}+ independently reviewed companies")
    for cid, count in judged_by_query.items():
        if count < minimum_test_judgments or positives[cid] == 0 or negatives[cid] == 0:
            errors.append(f"Insufficient or single-class test judgments: {cid}")
    if all(c["profile_origin"] == "synthetic" for c in companies):
        notes.append("Synthetic companies: real-company generalization NOT_VALIDATED")
    report.update(label_count=len(reviews), independent_test_queries=len(judged_by_query),
                  test_judgments_by_company=dict(judged_by_query),
                  status="READY_FOR_OFFLINE_EVALUATION" if not errors else "NOT_READY",
                  errors=errors)
    if pool is not None:
        pool_report = audit_pool(pool, corpus)
        report["pool_audit"] = pool_report
        if pool_report["errors"]:
            report["errors"].extend(pool_report["errors"])
            report["status"] = "NOT_READY"
    return report


def audit_pool(pool: dict, corpus: dict) -> dict:
    """Independent full-universe retrieval runs; never treat unjudged as negative."""
    errors = []
    universe = {n["notice_version_id"] for n in corpus["notices"]}
    if pool.get("corpus_sha256") != sha(corpus):
        raise ValueError("Pool/corpus hash mismatch")
    expected_universe = sha(sorted(universe))
    runs = pool.get("runs", [])
    if len({r.get("model") for r in runs}) != len(runs):
        errors.append("Duplicate retrieval model")
    by_query = defaultdict(dict)
    for run in runs:
        if run.get("universe_sha256") != expected_universe:
            errors.append(f"{run.get('model')}: retrieval universe differs from full corpus")
        if run.get("retrieval_mode") != "INDEPENDENT_FULL_CORPUS":
            errors.append(f"{run.get('model')}: prefiltered candidates are prohibited")
        for query_id, ranked in run.get("rankings", {}).items():
            if len(ranked) > 100 or len(set(ranked)) != len(ranked) or not set(ranked) <= universe:
                errors.append(f"{run.get('model')}: malformed top-100 for {query_id}")
            by_query[query_id][run["model"]] = ranked
    if len(runs) < 2:
        errors.append("At least two independent retrievers required to construct blind pools")
    sizes = {}
    for cid, ranking in by_query.items():
        if len(ranking) != len(runs):
            errors.append(f"Missing model retrieval for {cid}")
        sizes[cid] = len(set().union(*(set(r) for r in ranking.values())))
    return {"errors": errors, "pool_sizes": sizes,
            "universe_sha256": expected_universe,
            "note": "Blind union; unjudged documents excluded from judged-only ranking metrics"}


def make_blind_pool(pool: dict, corpus: dict) -> dict:
    checked = audit_pool(pool, corpus)
    if checked["errors"]:
        raise ValueError("; ".join(checked["errors"]))
    query_ids = {c["company_id"] for c in corpus["companies"]}
    n_by_version = {n["notice_version_id"]: n for n in corpus["notices"]}
    by_query = defaultdict(set)
    for run in pool["runs"]:
        for cid, versions in run["rankings"].items():
            if cid not in query_ids:
                raise ValueError("Unknown company in retrieval run")
            by_query[cid].update(versions)
    return {"corpus_sha256": sha(corpus), "schema_version": SCHEMA,
            "candidates": {cid: [{"notice_version_id": v,
                                  "body_status": n_by_version[v]["body_status"]}
                                 for v in sorted(versions)]
                           for cid, versions in sorted(by_query.items())},
            "note": "Source model identity and rankings intentionally excluded for blind reviewers"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--labels")
    parser.add_argument("--pool")
    parser.add_argument("--source-root")
    parser.add_argument("--output")
    args = parser.parse_args()
    corpus = read_json(args.corpus)
    result = audit(corpus, read_json(args.labels) if args.labels else None,
                   read_json(args.pool) if args.pool else None, source_root=args.source_root)
    blob = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(blob + "\n", encoding="utf-8")
    print(blob)
    if result["status"] == "NOT_READY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
