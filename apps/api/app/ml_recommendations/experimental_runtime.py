"""Opt-in artifact-only CPU BM25/E5-small/RRF; NEVER loads transformer on AWS.

Artifacts are generated offline and used only after live-valid version filtering.
No model scores should be interpreted as eligibility or a relevance probability.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
import time

from .light_retrieval_eval import tokens


def _dot(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Embedding dimension mismatch")
    return sum(float(x) * float(y) for x, y in zip(a, b))


@lru_cache(maxsize=1)
def read_artifacts(directory: str) -> tuple[list[dict], dict]:
    folder = Path(directory).resolve()
    corpus_path = folder / "corpus.json"
    vectors_path = folder / "vectors.json"
    if not corpus_path.is_file() or not vectors_path.is_file():
        raise FileNotFoundError("Experimental corpus/vector files missing")
    if corpus_path.stat().st_size > 60_000_000 or vectors_path.stat().st_size > 60_000_000:
        raise ValueError("Unexpected oversized retrieval artifact")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8-sig"))
    vectors = json.loads(vectors_path.read_text(encoding="utf-8-sig"))
    if not isinstance(corpus, list) or not 1 <= len(corpus) <= 100_000:
        raise ValueError("Invalid frozen corpus size")
    if vectors.get("schema") != "bidcheck-e5-offline-v1":
        raise ValueError("Unknown offline E5 artifact schema")
    if sha256(corpus_path.read_bytes()).hexdigest() != vectors.get("corpus_sha256"):
        raise ValueError("Corpus/vector digest mismatch")
    ids = [x["notice_version_id"] for x in corpus]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate artifact notice versions")
    source_vectors = vectors.get("docs", [])
    if not isinstance(source_vectors,list) or len(source_vectors)!=len(corpus):
        raise ValueError("Incomplete offline E5 vectors")
    docs = {x["notice_version_id"]:x["vector"] for x in source_vectors}
    if len(docs) != len(corpus) or set(docs) != set(ids):
        raise ValueError("Duplicate or missing offline E5 vectors")
    size = len(next(iter(docs.values())))
    if not 100 <= size <= 2048:
        raise ValueError("Invalid E5 embedding dimensions")
    def valid_vector(v):
        if not isinstance(v,list) or len(v)!=size:
            return False
        if any(isinstance(z,bool) or not isinstance(z,(float,int)) or
               not math.isfinite(z) for z in v):
            return False
        norm = sum(z*z for z in v)
        return .8 <= norm <= 1.2
    if any(not valid_vector(v) for v in docs.values()):
        raise ValueError("Nonfinite, dimension-mismatched or unnormalized E5 document vector")
    queries = vectors.get("queries",[])
    if not isinstance(queries,list) or len(queries)>100_000 or any(
        not isinstance(q.get("query_sha256"),str) or
        len(q["query_sha256"])!=64 or not valid_vector(q.get("vector"))
        for q in queries):
        raise ValueError("Invalid offline E5 query vector")
    by_query_sha={}
    for q in queries:
        digest=q["query_sha256"]
        if digest in by_query_sha and q["vector"]!=by_query_sha[digest]:
            raise ValueError("Conflicting cached query vectors")
        by_query_sha[digest]=q["vector"]
    for x in corpus:
        if x["source_status"] not in ("TASK_CANDIDATE_UNVERIFIED","TITLE_FALLBACK"):
            raise ValueError("Unrecognized corpus evidence status")
        if (not isinstance(x.get("search_text"),str) or
            not x["search_text"].strip() or len(x["search_text"])>12_000):
            raise ValueError("Invalid corpus retrieval text")
    return corpus,vectors


def _bm25(documents: list[dict], query: str) -> dict[str,float]:
    qt = set(tokens(query))
    counts = [Counter(tokens(x["search_text"])) for x in documents]
    dfs = Counter(t for c in counts for t in c)
    n = len(counts)
    avgdl = sum(sum(c.values()) for c in counts)/max(n,1)
    scores = {}
    for doc,c in zip(documents,counts):
        dl=sum(c.values())
        value=0.
        for term in qt:
            freq=c.get(term,0)
            if not freq:
                continue
            value += math.log(1+(n-dfs[term]+.5)/(dfs[term]+.5)) * (
                freq*2.2/(freq+1.2*(.25+.75*dl/max(1,avgdl)))
            )
        scores[doc["notice_version_id"]]=value
    return scores


def rank_artifacts(corpus: list[dict], vectors: dict, *,
                   valid_versions: set[str], query: str, mode: str = "hybrid_rrf",
                   live_titles: dict[str, str] | None = None, top=100) -> dict:
    """Rank ONLY live versions; title fallback includes unindexed new versions."""
    if mode not in ("bm25", "e5_small", "hybrid_rrf"):
        raise ValueError("Invalid experiment mode")
    if not query.strip() or top < 1 or top > 500:
        raise ValueError("Empty query or invalid top")
    start = time.perf_counter()
    docs = [r for r in corpus if r["notice_version_id"] in valid_versions]
    indexed_ids = {r["notice_version_id"] for r in docs}
    for ident, title in sorted((live_titles or {}).items()):
        if ident in valid_versions and ident not in indexed_ids:
            docs.append({"notice_version_id": ident, "title": title,
                         "search_text": title, "source_status": "TITLE_FALLBACK"})
    if not docs:
        return {"rankings": [], "fallback_used": True,
                "fallback_reason": "NO_LIVE_VALID_CANDIDATES", "mode_used": "bm25",
                "valid_indexed_count": 0, "live_title_fallback_count": 0, "latency_ms": 0.}
    index = {d["notice_version_id"]: d for d in docs}
    scores = _bm25(docs, query)
    bm = sorted(index, key=lambda k: (-scores[k], k))
    query_sha = sha256(query.encode("utf-8")).hexdigest()
    qvec = next((q["vector"] for q in vectors.get("queries", [])
                 if q["query_sha256"] == query_sha), None)
    embeddings = {r["notice_version_id"]: r["vector"] for r in vectors.get("docs", [])}
    # Exclude live title-fallback rows whose old frozen version vectors are stale.
    dense_ids = indexed_ids & set(embeddings)
    missing = len(index) - len(dense_ids)
    effective = mode
    fallback_reason = None
    if mode in ("e5_small", "hybrid_rrf") and qvec is None:
        effective = "bm25"
        fallback_reason = "NO_EXACT_CACHED_QUERY_VECTOR"
    if effective in ("e5_small", "hybrid_rrf") and not dense_ids:
        effective = "bm25"
        fallback_reason = "NO_CURRENT_E5_DOCUMENT_VECTORS"
    if effective in ("e5_small", "hybrid_rrf"):
        dense = {id: _dot(embeddings[id], qvec) for id in dense_ids}
        dr = sorted(dense, key=lambda id: (-dense[id], id))
        if effective == "e5_small":
            ranked = [(id, dense[id]) for id in dr]
            # New or stale source versions still appear through title BM25.
            ranked.extend((id, scores[id]) for id in bm if id not in dense_ids)
        else:
            totals = defaultdict(float)
            for ids in (bm[:top], dr[:top]):
                for rank, id in enumerate(ids, 1):
                    totals[id] += 1. / (60 + rank)
            ranked = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    else:
        ranked = [(id, scores[id]) for id in bm]
    if missing and not fallback_reason:
        fallback_reason = "UNINDEXED_LIVE_TITLE_FALLBACK"
    return {"rankings": [{"notice_version_id": id, "score": float(value)}
                         for id, value in ranked[:top]],
            "mode_used": effective,
            "fallback_used": effective != mode or missing > 0,
            "fallback_reason": fallback_reason,
            "valid_indexed_count": len(dense_ids),
            "live_title_fallback_count": missing,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
