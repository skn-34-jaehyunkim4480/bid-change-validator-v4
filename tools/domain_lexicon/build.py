"""Build a provenance-preserving, UNREVIEWED domain vocabulary from real extracted blocks.

No production DB, rule engine, canonical code master, or RAG API is modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data/domain_lexicon/seed.tsv"
DATASET_VERSION = "0.1.0-candidate"
HANGUL_BOUNDARY = r"[가-힣A-Za-z0-9]"


def sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def load_seeds(path: Path = SEED) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="|"))
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate concept ids")
    result = []
    for row in rows:
        forms = list(dict.fromkeys([row["name"], *(row["forms"] or "").split(";")]))
        result.append({"concept_id": row["id"], "canonical_name": row["name"],
                       "domain": row["domain"], "canonical_requirement_candidate": row["requirement"] or None,
                       "forms": [f for f in forms if f]})
    return result


def relation(name: str, surface: str) -> str:
    if name == surface:
        return "PREFERRED_LABEL"
    if re.sub(r"\s+", "", name) == re.sub(r"\s+", "", surface):
        return "ORTHOGRAPHIC_VARIANT_CANDIDATE"
    return "RELATED_CANDIDATE"


def phrase_pattern(surface: str) -> re.Pattern:
    # Never match "소기업" as part of "중소기업", or "등록" within "등록증".
    return re.compile(rf"(?<!{HANGUL_BOUNDARY}){re.escape(surface)}(?:에서|으로|부터|까지|은|는|이|가|을|를|에|의|로|과|와|도|만)?(?!{HANGUL_BOUNDARY})")


def document_paths(corpus: Path) -> list[Path]:
    # Guard against accidental holdout ingestion or arbitrary directories.
    if not corpus.is_dir() or "qualification-real" in str(corpus).lower():
        raise ValueError("input must be a non-holdout corpus directory")
    return sorted(corpus.rglob("*.blocks.json"))


def excerpt(text: str, start: int, end: int) -> str:
    snippet = " ".join(text[max(0, start - 55):min(len(text), end + 65)].split())[:160]
    snippet = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL_REDACTED]', snippet)
    return re.sub(r'(?<!\d)0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}(?!\d)', '[PHONE_REDACTED]', snippet)


def context_role_candidate(snippet: str) -> str:
    """Weak keyword hints only; never a verified qualification classification."""
    if re.search(r"(용역대금|지급하|대금을|정산|분기별|잔금|검수대금)", snippet):
        return "PAYMENT_OR_OPERATIONS_CANDIDATE"
    if re.search(r"(배점|평가항목|평가기준|심사기준|가점)", snippet):
        return "EVALUATION_CANDIDATE"
    if re.search(r"(제출서류|첨부해야|첨부하여|제출해야|증명서.*제출|구비서류)", snippet):
        return "SUBMISSION_CANDIDATE"
    if re.search(r"(참가자격|입찰자격|견적제출.*자격|소재지|제한경쟁|자격을.*갖춘)", snippet):
        return "QUALIFICATION_CANDIDATE"
    return "UNCLASSIFIED"

def build(corpus: Path, seeds: list[dict], *, max_files: int = 0) -> dict:
    files = document_paths(corpus)
    if max_files:
        files = files[:max_files]
    catalog = []
    for entry in seeds:
        for term in entry["forms"]:
            catalog.append((entry, term, phrase_pattern(term)))
    found: dict[tuple[str, str], dict] = {}
    stats = Counter()
    notices: set[str] = set()
    source_shas: set[str] = set()
    for path in files:
        raw = path.read_bytes()
        source_sha = sha(raw)
        source_shas.add(source_sha)
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError(f"unexpected blocks schema: {path.name}")
        notice = path.parent.name
        notices.add(notice)
        stats["document_blocks"] += len(data)
        for block in data:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                continue
            text = block["text"]
            block_hash = sha(text.encode("utf-8"))
            for entry, term, pattern in catalog:
                matches = list(pattern.finditer(text))
                if not matches:
                    continue
                key = (entry["concept_id"], term)
                row = found.setdefault(key, {
                    "concept_id": entry["concept_id"], "canonical_name": entry["canonical_name"],
                    "surface": term, "relation_type": relation(entry["canonical_name"], term),
                    "domain": entry["domain"], "canonical_requirement_candidate": entry["canonical_requirement_candidate"],
                    "review_status": "UNREVIEWED", "search_expansion_approved": False, "dataset_version": DATASET_VERSION,
                    "frequency": 0, "source_notice_count": 0, "source_examples": [], "_notices": set(),
                })
                row["frequency"] += len(matches)
                row["_notices"].add(notice)
                if len(row["source_examples"]) < 2:
                    m = matches[0]
                    row["source_examples"].append({
                        "notice_id_round": notice, "extraction_file_sha256": source_sha, "source_file": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name,
                        "block_sha256": block_hash, "block_index": block.get("block_index"),
                        "location": block.get("location"), "context_excerpt": excerpt(text, m.start(), m.end()),
                        "context_role_candidate": context_role_candidate(excerpt(text, m.start(), m.end())),
                    })
    records = sorted(found.values(), key=lambda r: (r["concept_id"], r["surface"]))
    for record in records:
        record["source_notice_count"] = len(record.pop("_notices"))
    represented = {r["concept_id"] for r in records}
    return {"dataset_version": DATASET_VERSION, "status": "RESEARCH_ONLY_NOT_FOR_PRODUCTION",
            "source_kind": "LOCAL_SNAPSHOT_OF_REAL_EXTRACTED_NOTICE_BLOCKS",
            "source_root": corpus.relative_to(ROOT).as_posix() if corpus.is_relative_to(ROOT) else "EXTERNAL_INPUT",
            "notice_count": len(notices), "document_count": len(files),
            "document_blocks": stats["document_blocks"], "distinct_source_sha256": len(source_shas),
            "seed_concepts": len(seeds), "grounded_concepts": len(represented),
            "unobserved_concept_ids": sorted(set(s["concept_id"] for s in seeds) - represented),
            "expression_records": records}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, default=ROOT / "eval/golden/notice-sample-20261006f")
    p.add_argument("--out", type=Path, default=ROOT / "data/domain_lexicon/candidates-v0.1.json")
    p.add_argument("--max-files", type=int, default=0)
    args = p.parse_args()
    result = build(args.corpus.resolve(), load_seeds(), max_files=args.max_files)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("expression_records", "unobserved_concept_ids")}, ensure_ascii=False))
    print("records", len(result["expression_records"]), "unobserved", len(result["unobserved_concept_ids"]))


if __name__ == "__main__":
    main()
