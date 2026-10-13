"""CPU-only BM25/E5/RRF on SAME frozen corpus, with GPT development-positive hits.

No nDCG/precision/full recall claim: unjudged candidates remain unjudged.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time

from .light_retrieval_eval import bm25_scores, companies, rank
from .known_positive_diagnostic import read_dev_positive_labels


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _rrf(a, b, limit=100):
    scores = defaultdict(float)
    for ranked in (a, b):
        for i, item in enumerate(ranked, 1):
            scores[item] += 1. / (60 + i)
    return sorted(scores, key=lambda ident:(-scores[ident], ident))[:limit]


def evaluate(corpus, snapshot, vectors, positives, *, top=100, corpus_file_sha256=None):
    if not 1 <= top <= 100:
        raise ValueError("invalid top")
    if vectors["schema"] != "bidcheck-e5-offline-v1":
        raise ValueError("unrecognized artifact schema")
    if corpus_file_sha256 is None:
        raise ValueError("Frozen corpus file SHA required for artifact validation")
    if vectors["corpus_sha256"] != corpus_file_sha256:
        raise ValueError("Corpus differs from precomputed vectors")
    docs = [{"id": d["notice_version_id"], "text": d["search_text"]} for d in corpus]
    queries = companies(snapshot)
    if len(set(d["id"] for d in docs)) != len(docs):
        raise ValueError("duplicate notice version")
    documents = {r["notice_version_id"]:r for r in vectors["docs"]}
    query_vec = {r["company_id"]:r for r in vectors["queries"]}
    if set(documents) != {d["id"] for d in docs}:
        raise ValueError("incomplete document vectors")
    import numpy as np
    matrix = np.asarray([documents[d["id"]]["vector"] for d in docs],dtype=np.float32)
    started=time.perf_counter()
    bm25 = bm25_scores(docs, queries)
    bm25_seconds=time.perf_counter()-started
    hits = {m:Counter() for m in ("bm25","e5_small","hybrid_rrf")}
    known = 0
    known_profiles = 0
    valid_positive = {q["id"]:positives.get(q["id"],set()) & set(documents) for q in queries}
    for q in queries:
        cid=q["id"]
        stored=query_vec.get(cid)
        if not stored or stored["query_sha256"] != hashlib.sha256(q["text"].encode()).hexdigest():
            raise ValueError("Precomputed company vector no longer matches profile query")
        scores=(matrix @ np.asarray(stored["vector"],dtype=np.float32)).tolist()
        a=rank(docs,bm25[cid],top)
        b=rank(docs,scores,top)
        ranked={"bm25":a,"e5_small":b,"hybrid_rrf":_rrf(a,b,top)}
        known_set=valid_positive[cid]
        if not known_set:
            continue
        known+=len(known_set)
        known_profiles+=1
        for model,entries in ranked.items():
            for cutoff in (10,50,100):
                hits[model][str(cutoff)]+=len(known_set & set(entries[:cutoff]))
    return {"status":"POSITIVE_ENRICHED_GPT_DEV_DIAGNOSTIC",
            "source": "Frozen AWS read-only RDS excerpts, locally precomputed E5",
            "same_candidate_universe":True,
            "candidate_count":len(docs), "body_candidate_count":
                sum(d["source_status"]=="TASK_CANDIDATE_UNVERIFIED" for d in corpus),
            "positive_pairs_within_universe":known,
            "positive_profiles_within_universe":known_profiles,
            "all_labels_human_approved":False,
            "true_precision_recall_ndcg":"NOT_MEASURED",
            "independent_blind_holdout":False,
            "bm25_all_queries_seconds":round(bm25_seconds,3),
            "known_positive_hits":{model:dict(counts) for model,counts in hits.items()}}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--corpus",type=Path,required=True)
    p.add_argument("--snapshot",type=Path,required=True)
    p.add_argument("--vectors",type=Path,required=True)
    p.add_argument("--private-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():
        raise FileExistsError("Frozen evaluation report already exists")
    result=evaluate(_load(args.corpus),_load(args.snapshot),_load(args.vectors),
                    read_dev_positive_labels(args.private_root)[0],
                    corpus_file_sha256=hashlib.sha256(args.corpus.read_bytes()).hexdigest())
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
