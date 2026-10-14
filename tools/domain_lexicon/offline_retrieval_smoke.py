"""Offline held-out, version-scoped BM25 retrieval smoke; NEVER calls embeddings or LLMs.

This tiny non-independent diagnostic is NOT comparable with hosted E3 and cannot
support a deployment claim. Frozen queries and gold spans are separate from
candidate lexicon training snapshots.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
from bidengine.rag.retrieval import _lexical_ranking, navigation_like, normalized_text
from bidengine.rag.store import build_notice_version_records

CONFIG = ROOT / "data/domain_lexicon/holdout-smoke-v0.1.json"


def prepare():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    source = ROOT / cfg["input_case_path"]
    labels = ROOT / cfg["evidence_fixture_path"]
    spec = json.loads(source.read_text(encoding="utf8"))
    spans = json.loads(labels.read_text(encoding="utf8"))["cases"][0]["spans"]
    assert spec["notice_no"] == cfg["notice_no"]
    assert any(v["bid_notice_order"] == cfg["source_order"] for v in spec["versions"])
    assert cfg["notice_no"] == json.loads(labels.read_text(encoding="utf8"))["cases"][0]["notice_no"]
    doc_objs = []
    for i, document in enumerate(spec["documents"]):
        if document["version_key"] != "C01-source-order-000":
            continue
        filename = source.parent.parent.parent / document["blocks"]["path"]
        raw = filename.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == document["blocks"]["sha256"]
        doc_objs.append(SimpleNamespace(id=document["document_key"], document_order=i,
                                        name=document["name"], source_field="DOCUMENT",
                                        extraction_status="EXTRACTED", extracted_blocks=json.loads(raw),
                                        file_sha256=document["source_file_sha256"],
                                        extracted_text_sha256=document["extracted_text_sha256"]))
    version = SimpleNamespace(notice_id=cfg["notice_no"], id="C01-source-order-000", version_number=1,
                              documents=doc_objs)
    records = build_notice_version_records(version)
    labels_by_id = {row["span_id"]: row for row in spans}
    for q in cfg["questions"]:
        assert all(sid in labels_by_id for sid in q["span_ids"])
    return cfg, labels_by_id, records, hashlib.sha256(CONFIG.read_bytes()).hexdigest()


def space_only(query: str) -> str:
    """Safe unicode/whitespace normalization; do not delete semantic words."""
    return normalized_text(query)


def rank(records, query, method):
    ids = _lexical_ranking(records, space_only(query) if method != "existing_bm25" else query)
    if method == "context_candidate":
        by_id = {r.metadata.chunk_id: r for r in records}
        # Conservative navigation suppression only. Qualification inference remains disabled.
        ids = sorted(ids[:20], key=lambda key: navigation_like(by_id[key].text)) + ids[20:]
    return ids


def matches(hit, span):
    if hit.metadata.document_id != "C01-cache-" + {
        "NOTICE-HWPX": "0f39b1f925e1d4c9", "NOTICE-PDF": "3f31ff624b51646c",
        "RFP-HWPX": "dff181bb843ba322"}[span["document_id"]]:
        return False
    actual, expected = normalized_text(hit.text), normalized_text(span["quote"])
    return bool(expected in actual or (len(actual) >= 40 and actual in expected))


def run() -> dict:
    cfg, labels, records, fixture_sha = prepare()
    by_id = {r.metadata.chunk_id: r for r in records}
    methods = ["existing_bm25", "spacing_only", "context_candidate"]
    results = {}
    for method in methods:
        elapsed = []
        hits_by_k = {4: 0, 10: 0}
        trap_by_k = {4: 0, 10: 0}
        rows = []
        for q in cfg["questions"]:
            started = time.perf_counter()
            ids = rank(records, q["query"], method)
            elapsed.append((time.perf_counter() - started)*1000)
            ranked = [by_id[key] for key in ids]
            hit_rank = min((i for i,r in enumerate(ranked,1) if any(matches(r,labels[e]) for e in q["span_ids"])),default=None)
            trap_ids = [s for s in labels.values() if s["span_kind"] == "TRAP"]
            trap_ranks = [i for i,r in enumerate(ranked,1) if any(matches(r,s) for s in trap_ids)]
            for k in hits_by_k:
                hits_by_k[k] += int(hit_rank is not None and hit_rank<=k)
                trap_by_k[k] += sum(i<=k for i in trap_ranks)
            rows.append({"query_id":q["query_id"],"matched_rank":hit_rank,"known_trap_ranks":trap_ranks[:3],
                         "returned_notice_versions": sorted({r.metadata.notice_version_id for r in ranked[:10]})})
        results[method] = {"recall_at_4": round(hits_by_k[4]/len(rows),4), "recall_at_10":round(hits_by_k[10]/len(rows),4),
                           "known_trap_hits_at_4":trap_by_k[4], "known_trap_hits_at_10":trap_by_k[10],
                           "p50_latency_ms":round(statistics.median(elapsed),3),
                           "p95_latency_ms":round(sorted(elapsed)[int((len(elapsed)-1)*.95)],3),
                           "avg_query_cost_usd":0,"queries":rows}
    return {"status":"COMPLETED_SMALL_DIAGNOSTIC_NOT_E3", "scope":"One real historical notice, four fixed researcher queries, offline BM25",
            "dataset_version":"BCV4-03-002-HOLDOUT-DIAGNOSTIC", "query_fixture_sha256":fixture_sha,
            "documents":3,"chunks":len(records), "query_count":len(cfg["questions"]),
            "reviewed_synonyms_available":0, "paid_api_calls":0, "live_e3_comparison":"NOT_COMPARABLE",
            "dense":"NOT_RUN_NO_FREE_EXISTING_VERSION_INDEX", "hybrid":"NOT_RUN_NO_FREE_EXISTING_VERSION_INDEX",
            "synonym_expansion":"NOT_RUN_ZERO_REVIEWED", "llm_rerank":"NOT_RUN_PAID_API_PROHIBITED", "results":results}


if __name__ == "__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2))
