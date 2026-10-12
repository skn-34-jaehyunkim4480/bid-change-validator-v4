"""Integrity checks for provenance-only domain candidates; does not approve terms."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from build import ROOT, sha

DATA = ROOT / "data/domain_lexicon"


def validate(data_path: Path = DATA / "candidates-v0.1.json") -> dict:
    data = json.loads(data_path.read_text(encoding="utf-8-sig"))
    expressions = data["expression_records"]
    ids = {(r["concept_id"], r["surface"]) for r in expressions}
    assert len(ids) == len(expressions), "duplicate surface per concept"
    existing_concepts = {r["concept_id"] for r in expressions}
    pairs = json.loads((DATA / "relations-v0.1.json").read_text(encoding="utf-8-sig"))["relations"]
    assert all(p["from"] in existing_concepts and p["to"] in existing_concepts for p in pairs)
    cache = {}
    example_count = 0
    for row in expressions:
        assert row["review_status"] == "UNREVIEWED"
        assert row["search_expansion_approved"] is False
        assert row["relation_type"] in {"PREFERRED_LABEL", "ORTHOGRAPHIC_VARIANT_CANDIDATE", "RELATED_CANDIDATE"}
        assert row["frequency"] >= row["source_notice_count"] > 0
        for example in row["source_examples"]:
            source = ROOT / example["source_file"]
            assert source.resolve().is_relative_to(ROOT.resolve())
            assert source.parent.name == example["notice_id_round"]
            assert "qualification-real" not in str(source).lower(), "holdout contamination"
            if source not in cache:
                raw = source.read_bytes()
                cache[source] = (sha(raw), {b["block_index"]: b["text"] for b in json.loads(raw.decode("utf-8-sig"))})
            source_sha, blocks = cache[source]
            assert source_sha == example["extraction_file_sha256"]
            assert sha(blocks[example["block_index"]].encode("utf-8")) == example["block_sha256"]
            assert len(example["context_excerpt"]) <= 180
            assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", example["context_excerpt"])
            example_count += 1
    auto_path = DATA / "auto-candidates-v0.1.json"
    auto = json.loads(auto_path.read_text(encoding="utf-8-sig"))
    assert all(r["review_status"] == "UNREVIEWED" and r["relation_type"] == "UNMAPPED_CANDIDATE" for r in auto["records"])
    return {"expression_records": len(expressions), "unique_concepts": len(existing_concepts),
            "relation_types": dict(Counter(r["relation_type"] for r in expressions)),
            "relationship_edges": len(pairs), "auto_candidates": len(auto["records"]),
            "evidence_samples_verified": example_count, "source_files_verified": len(cache)}


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, sort_keys=True))
