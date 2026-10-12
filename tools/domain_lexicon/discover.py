"""Induce previously unlisted terminology candidates from local real-notice extracts.

Patterns produce hypotheses, not approved concept names or legal synonyms.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from build import ROOT, DATASET_VERSION, context_role_candidate, document_paths, excerpt, load_seeds, sha

PATTERNS = {
    "industry": re.compile(r"(?<![가-힣])([가-힣]{2,15}(?:업|공사업))\s*(?:면허|등록|신고)(?![가-힣])"),
    "certificate": re.compile(r"(?<![가-힣])([가-힣]{3,16}(?:확인서|증명서))(?![가-힣])"),
    "staff": re.compile(r"(?<![가-힣])([가-힣]{2,12}(?:기술자|기술인|책임자))(?![가-힣])"),
}


def discover(corpus: Path, *, min_notices: int = 2, max_terms: int = 75) -> dict:
    seeds = load_seeds()
    already = {name for item in seeds for name in item["forms"]}
    seen = defaultdict(lambda: {"notices": set(), "frequency": 0, "examples": []})
    files = document_paths(corpus)
    for source in files:
        raw = source.read_bytes()
        blocks = json.loads(raw.decode("utf-8-sig"))
        for block in blocks:
            text = block.get("text", "")
            if not isinstance(text, str):
                continue
            for domain, pattern in PATTERNS.items():
                for match in pattern.finditer(text):
                    term = match.group(1).strip()
                    if term in already or len(term) > 18:
                        continue
                    state = seen[(domain, term)]
                    state["notices"].add(source.parent.name)
                    state["frequency"] += 1
                    if len(state["examples"]) < 1:
                        state["examples"].append({
                            "notice_id_round": source.parent.name,
                            "extraction_file_sha256": sha(raw),
                            "block_sha256": sha(text.encode("utf-8")),
                            "block_index": block.get("block_index"),
                            "context_excerpt": excerpt(text, match.start(), match.end()),
                            "context_role_candidate": context_role_candidate(excerpt(text, match.start(), match.end()))})
    records = []
    for (domain, surface), item in seen.items():
        if len(item["notices"]) < min_notices:
            continue
        records.append({"surface": surface, "domain": domain, "frequency": item["frequency"],
                        "source_notice_count": len(item["notices"]), "source_examples": item["examples"],
                        "review_status": "UNREVIEWED", "relation_type": "UNMAPPED_CANDIDATE",
                        "canonical_requirement_candidate": None})
    records.sort(key=lambda r: (-r["source_notice_count"], -r["frequency"], r["surface"]))
    return {"dataset_version": DATASET_VERSION, "source_kind": "LOCAL_SNAPSHOT_OF_REAL_EXTRACTED_NOTICE_BLOCKS",
            "status": "UNREVIEWED_AUTO_EXTRACTION", "total_discovered": len(records),
            "minimum_distinct_notices": min_notices, "records": records[:max_terms]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=ROOT / "eval/golden/notice-sample-20261006f")
    parser.add_argument("--out", type=Path, default=ROOT / "data/domain_lexicon/auto-candidates-v0.1.json")
    args = parser.parse_args()
    obj = discover(args.corpus.resolve())
    args.out.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("auto_candidates", obj["total_discovered"], "stored", len(obj["records"]))


if __name__ == "__main__":
    main()
