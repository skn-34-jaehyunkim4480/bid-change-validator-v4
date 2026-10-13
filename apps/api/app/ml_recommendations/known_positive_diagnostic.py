"""Locally frozen, positive-only RETRIEVAL smoke.
Not a production valid-universe accuracy benchmark: only 442 historical/current
snapshot versions and heavily enriched GPT teacher development judgments.
No AWS access and no GPT paid API.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import time

from .light_retrieval_eval import bm25_scores, companies, dense_scores, rank
from .alternate_source_review import (
    verify_alternate_review, verify_complete_selected_blocks,
)

def _load(path:Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def _jsonl(path:Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

def _sha(text:str):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def source_backed_documents(snapshot, historic, *, private_root:Path):
    """Exactly one source text per notice version, never joining across title matches."""
    docs={}
    for notice in snapshot["notices"]+historic:
        version=notice["notice_version_id"]
        current=docs.get(version)
        if current and current["notice_id"]!=notice["notice_id"]:
            raise ValueError("Version copied across notices")
        if current:continue
        docs[version]={"id":version,"notice_id":notice["notice_id"],
                       "title":notice["title"],"text":notice["title"],
                       "source_type":"TITLE_ONLY"}
    def attach(version, text, stage):
        if version not in docs:raise ValueError("Selected source version not in sampled universe")
        if not text.strip():raise ValueError("Empty source excerpt")
        if docs[version]["source_type"]!="TITLE_ONLY":
            raise ValueError("Version provided conflicting source documents: "+version)
        docs[version]["text"]=docs[version]["title"]+"\n"+text
        docs[version]["source_type"]=stage
    old=_jsonl(private_root/"gpt6_reviewed_excerpt_pilot_v1"/"task_review.jsonl")
    for row in old:
        if row["teacher_review_status"]!="REVIEWED_EXCERPT" or row["evidence_type"]!="DIRECT":continue
        if _sha(row["excerpt_text"])!=row["excerpt_sha256"]:raise ValueError("Old excerpt SHA mismatch")
        attach(row["notice_version_id"],row["excerpt_text"],"DIRECT_EXTRACTED")
    recent=_jsonl(private_root/"gpt6_reviewed_excerpt_pilot_v2"/"remaining_34_review.jsonl")
    for row in recent:
        if row["status"]!="DIRECT_EXCERPT":continue
        if _sha(row["selected_excerpt_text"])!=row["selected_excerpt_sha256"]:raise ValueError("Review excerpt SHA mismatch")
        attach(row["notice_version_id"],row["selected_excerpt_text"],"DIRECT_EXTRACTED")
    old_alt=private_root/"alternate_review_v1"
    verify_alternate_review(private_root,old_alt)
    for row in _jsonl(old_alt/"alternate_review_candidates.jsonl"):
        attach(row["notice_version_id"],row["task_excerpt_preview"],"ALTERNATE_SOURCE_PREVIEW")
    new_alt=private_root/"alternate_review_remaining_v1"
    full_files=tuple(f"alternate_remaining_full_{i}.json" for i in (0,2,4,6,8,10))
    audit=verify_complete_selected_blocks(private_root,new_alt,full_files)
    full={}
    for f in full_files:
        for doc in _load(private_root/f):
            full[doc["document_id"]]={b["block_index"]:b["text"] for b in doc["blocks"]}
    for row in _jsonl(new_alt/"alternate_review_candidates.jsonl"):
        if row["task_scope_status"]=="INSUFFICIENT_SOURCE":continue
        blocks=full[row["document_id"]]
        task="\n".join(blocks[i] for i in row["sample_block_indices"])
        attach(row["notice_version_id"],task,"DIRECT_EXTRACTED" if row["task_scope_status"]=="DIRECT_TASK_EXCERPT" else "PARTIAL_EXTRACTED")
    return sorted(docs.values(),key=lambda d:d["id"])

def read_dev_positive_labels(private_root):
    files=[
        private_root/"gpt6_reviewed_excerpt_pilot_v1"/"teacher_judgments.jsonl",
        private_root/"gpt6_reviewed_excerpt_pilot_v2"/"targeted_dev_pairs.jsonl",
        private_root/"alternate_preview_dev_v1"/"alternate_preview_dev_labels.jsonl"]
    rows=[row for f in files for row in _jsonl(f)]
    judged=set()
    for row in rows:
        key=(row["company_id"],row["notice_version_id"])
        if key in judged:raise ValueError("Duplicate development judgment")
        judged.add(key)
        if row["human_approved"] is not False or row["grade"] not in (0,1,2,3):
            raise ValueError("Invalid GPT development judgment provenance")
    positive=defaultdict(set)
    for row in rows:
        if row["grade"]>=2:positive[row["company_id"]].add(row["notice_version_id"])
    return positive,rows

def _rrf(a,b,top):
    s=defaultdict(float)
    for order in (a,b):
        for pos,doc in enumerate(order,1):s[doc]+=1/(60+pos)
    return [id for id,_ in sorted(s.items(),key=lambda x:(-x[1],x[0]))[:top]]

def compare_positives(documents,queries,positives,model,top=100):
    """Known-positive coverage only; never NDCG over unlabeled documents."""
    if len(documents)<top:raise ValueError("Sampled universe too small")
    ids={d["id"] for d in documents}
    qids={q["id"] for q in queries}
    if any(cid not in qids or not cases.issubset(ids) for cid,cases in positives.items()):
        raise ValueError("Known positive outside query/candidate universe")
    start=time.perf_counter()
    bm=bm25_scores(documents,queries)
    bm_sec=time.perf_counter()-start
    start=time.perf_counter()
    dense,latencies=dense_scores(documents,queries,model=model)
    dense_sec=time.perf_counter()-start
    ranks={}
    for query in queries:
        cid=query["id"]
        a=rank(documents,bm[cid],top)
        b=rank(documents,dense[cid],top)
        ranks[cid]={"bm25":a,"e5_small":b,"hybrid_rrf":_rrf(a,b,top)}
    per_model={}
    for name in ("bm25","e5_small","hybrid_rrf"):
        valid=[(cid,positives[cid]) for cid in sorted(positives) if positives[cid]]
        counts={k:0 for k in (10,50,100)}
        totals=sum(len(p) for _,p in valid)
        company_counts={}
        for cid,p in valid:
            r=ranks[cid][name]
            for k in counts:counts[k]+=len(p & set(r[:k]))
            company_counts[cid]={"known_positive_count":len(p),
               "top10_known_hits":len(p & set(r[:10])),
               "top50_known_hits":len(p & set(r[:50])),
               "top100_known_hits":len(p & set(r[:100]))}
        per_model[name]={
            "micro_known_positive_coverage_at_10":round(counts[10]/totals,4),
            "micro_known_positive_coverage_at_50":round(counts[50]/totals,4),
            "micro_known_positive_coverage_at_100":round(counts[100]/totals,4),
            "hit_counts":{str(k):n for k,n in counts.items()},
            "company_detail":company_counts}
    return {"status":"POSITIVE_ENRICHED_GPT_DEV_DIAGNOSTIC_NOT_INDEPENDENT_ACCURACY",
            "candidate_versions":len(documents),
            "source_backed_versions":sum(d["source_type"]!="TITLE_ONLY" for d in documents),
            "candidate_source_distribution":dict(__import__("collections").Counter(d["source_type"] for d in documents)),
            "company_queries":len(queries),
            "positive_profiles":len(positives),
            "known_positive_pairs":sum(len(v) for v in positives.values()),
            "distinct_positive_notice_versions":len(set().union(*positives.values())),
            "full_AWS_universe":False,
            "label_source":"GPT-6 model-authored targeted development only",
            "untouched_test_set":False,
            "real_business_accuracy":"NOT_MEASURED",
            "metrics":per_model,
            "query_latency_p50_ms":round(statistics.median(latencies),2),
            "bm25_all_queries_seconds":round(bm_sec,3),
            "e5_encode_all_seconds":round(dense_sec,3)}

def evaluate(snapshot,historical,root,model):
    docs=source_backed_documents(snapshot,historical,private_root=root)
    queries=companies(snapshot)
    positives,labels=read_dev_positive_labels(root)
    title=[{**row,"text":row["title"],"source_type":"TITLE_ONLY"} for row in docs]
    title_stats=compare_positives(title,queries,positives,model)
    body_stats=compare_positives(docs,queries,positives,model)
    return {"status":"EXPLORATORY_ONLY",
        "sampled_corpus_sha256":hashlib.sha256(json.dumps([(x["id"],x["text"]) for x in docs],ensure_ascii=False).encode()).hexdigest(),
        "dev_label_count":len(labels),
        "title_only":title_stats,"source_backed":body_stats}

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot",required=True,type=Path)
    p.add_argument("--historical",required=True,type=Path)
    p.add_argument("--private-root",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--model",default="intfloat/multilingual-e5-small")
    a=p.parse_args()
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(min(6,torch.get_num_threads()))
    model=SentenceTransformer(a.model,device="cpu",local_files_only=True,trust_remote_code=False)
    model.max_seq_length=256
    results=evaluate(_load(a.snapshot),_load(a.historical),a.private_root,model)
    if a.out.exists():raise FileExistsError("Never overwrite private frozen evaluations")
    a.out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    for case in ("title_only","source_backed"):
        stat=results[case]
        print(case,"universe",stat["candidate_versions"],"source_backed",stat["source_backed_versions"],
              "known positives",stat["known_positive_pairs"],"positive firms",stat["positive_profiles"],
              "p50ms",stat["query_latency_p50_ms"])
        for name,r in stat["metrics"].items():
            print(" ",name,"hits@10/50/100",r["hit_counts"],
                  "coverage",r["micro_known_positive_coverage_at_10"],
                  r["micro_known_positive_coverage_at_50"],
                  r["micro_known_positive_coverage_at_100"])
    print("PRIVATE_RESULT",a.out)

if __name__=="__main__":main()
