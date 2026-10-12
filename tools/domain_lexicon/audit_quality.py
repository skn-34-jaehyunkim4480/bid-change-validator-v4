"""BCV4-03-002: provenance, ambiguity and relation graph audit (read-only)."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/domain_lexicon"
SOURCE_ROOT = ROOT / "eval/golden/notice-sample-20261006f"
HOLDOUT_ROOT = ROOT / "eval/golden/qualification-real-v0.1"
VALID_ROLES = {"UNCLASSIFIED", "PAYMENT_OR_OPERATIONS_CANDIDATE", "EVALUATION_CANDIDATE", "SUBMISSION_CANDIDATE", "QUALIFICATION_CANDIDATE"}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(text: str) -> str:
    return " ".join(text.split())


def graph_audit(relations: list[dict], ids: set[str]) -> dict:
    edges = set()
    broader = defaultdict(list)
    for edge in relations:
        a, b, typ = edge["from"], edge["to"], edge["type"]
        assert a in ids and b in ids and a != b
        assert typ in {"NOT_EQUIVALENT", "BROADER_THAN_CANDIDATE"}
        key = (a, b) if typ != "NOT_EQUIVALENT" else (*sorted((a, b)),)
        assert (typ, key) not in edges, "duplicate graph edge"
        edges.add((typ, key))
        if typ == "BROADER_THAN_CANDIDATE":
            assert ("NOT_EQUIVALENT", (*sorted((a, b)),)) not in edges
            broader[a].append(b)
        if typ == "NOT_EQUIVALENT":
            assert ("BROADER_THAN_CANDIDATE", (a, b)) not in edges
            assert ("BROADER_THAN_CANDIDATE", (b, a)) not in edges
    visiting, visited = set(), set()
    def walk(n: str) -> None:
        if n in visiting:
            raise AssertionError("broader/narrower relation cycle")
        if n in visited:
            return
        visiting.add(n)
        for other in broader[n]:
            walk(other)
        visiting.remove(n)
        visited.add(n)
    for n in ids:
        walk(n)
    return {"graph_edges": len(relations), "broader_candidate_edges": sum(len(x) for x in broader.values()), "cycles": 0}


def run(*, source_root: Path = SOURCE_ROOT, holdout_root: Path = HOLDOUT_ROOT) -> dict:
    base = json.loads((DATA / "candidates-v0.1.json").read_text(encoding="utf-8-sig"))
    auto = json.loads((DATA / "auto-candidates-v0.1.json").read_text(encoding="utf-8-sig"))
    relation_list = json.loads((DATA / "relations-v0.1.json").read_text(encoding="utf-8-sig"))["relations"]
    seed = list(base["expression_records"])
    names = {r["concept_id"] for r in seed}
    graph = graph_audit(relation_list, names)
    seen_surfaces = defaultdict(set)
    for row in seed:
        seen_surfaces[row["surface"]].add(row["concept_id"])
        assert row["review_status"] == "UNREVIEWED" and not row["search_expansion_approved"]
        assert row["dataset_version"] == base["dataset_version"]
    seen_files = {}
    raw_to_notices = defaultdict(set)
    examples = 0
    for path in sorted(source_root.rglob("*.blocks.json")):
        raw = path.read_bytes()
        source_hash = digest(raw)
        raw_to_notices[source_hash].add(path.parent.name)
        data = json.loads(raw.decode("utf-8-sig"))
        indexes = [b["block_index"] for b in data]
        assert len(indexes) == len(set(indexes)), f"duplicate block indexes: {path.name}"
        seen_files[path.relative_to(ROOT).as_posix()] = (source_hash, {b["block_index"]: b for b in data})
    for row in seed:
        for evidence in row["source_examples"]:
            source_file = evidence["source_file"]
            assert source_file in seen_files and "qualification-real" not in source_file
            source_sha, blocks = seen_files[source_file]
            assert evidence["extraction_file_sha256"] == source_sha
            assert evidence["notice_id_round"] == Path(source_file).parent.name
            block = blocks[evidence["block_index"]]
            text = block["text"]
            assert evidence["block_sha256"] == digest(text.encode("utf8"))
            assert evidence["location"] == block.get("location")
            excerpt = canonical(evidence["context_excerpt"])
            # Redactions are placeholders and cannot be exact-matched to original text.
            if "[EMAIL_REDACTED]" not in excerpt and "[PHONE_REDACTED]" not in excerpt:
                assert excerpt in canonical(text), f"context excerpt does not belong to source: {source_file}"
            assert evidence["context_role_candidate"] in VALID_ROLES
            examples += 1
    by_sha = defaultdict(list)
    for rel, (source_sha, blocks) in seen_files.items():
        by_sha[source_sha].append((rel, blocks))
    # Auto-discovered candidates never silently become reviewed/approved.
    auto_examples = 0
    for row in auto["records"]:
        assert row["review_status"] == "UNREVIEWED" and row["relation_type"] == "UNMAPPED_CANDIDATE"
        for ex in row["source_examples"]:
            assert re.fullmatch(r"[0-9a-f]{64}", ex["block_sha256"])
            assert any(
                Path(rel).parent.name == ex["notice_id_round"]
                and ex["block_index"] in blocks
                and digest(blocks[ex["block_index"]]["text"].encode("utf8")) == ex["block_sha256"]
                and (canonical(ex["context_excerpt"]) in canonical(blocks[ex["block_index"]]["text"])
                     or "[EMAIL_REDACTED]" in ex["context_excerpt"]
                     or "[PHONE_REDACTED]" in ex["context_excerpt"])
                for rel,blocks in by_sha[ex["extraction_file_sha256"]]
            ), "auto evidence SHA/notice/block mismatch"
            assert re.fullmatch(r"[0-9a-f]{64}", ex["extraction_file_sha256"])
            assert ex["context_role_candidate"] in VALID_ROLES
            auto_examples += 1
    build_hashes = set(raw_to_notices)
    holdout_hashes = {digest(p.read_bytes()) for p in holdout_root.rglob("*.blocks.json")}
    assert not build_hashes.intersection(holdout_hashes), "holdout file hash leakage"
    duplicate_hashes = {h: dirs for h, dirs in raw_to_notices.items() if len(dirs) > 1}
    return {"status": "PASS", "build_notice_rounds": len({p.parent.name for p in source_root.rglob('*.blocks.json')}),
            "build_files": len(seen_files), "build_unique_file_shas": len(build_hashes),
            "source_sha_reused_across_notice_rounds": len(duplicate_hashes),
            "holdout_documents": len(list(holdout_root.rglob('*.blocks.json'))),
            "holdout_file_sha_overlap": len(build_hashes & holdout_hashes),
            "verified_lexicon_excerpts": examples, "auto_candidate_source_sha_verified": auto_examples,
            "ambiguous_surface_forms": {s: sorted(ids) for s,ids in seen_surfaces.items() if len(ids)>1},
            "approved_synonyms": 0, "unreviewed_expression_count": len(seed),
            "unreviewed_auto_candidates": len(auto["records"]), **graph}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
