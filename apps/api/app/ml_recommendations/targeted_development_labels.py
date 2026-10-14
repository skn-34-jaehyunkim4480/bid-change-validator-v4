"""Audit manually-authored targeted development pairs; never generate labels from overlap."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path

def lines(path:Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

def sha(data:str):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

def build_reviewed_map(old:list[dict],new:list[dict],queue:list[dict]):
    verified={}
    versions={x["notice_version_id"]:x for x in queue}
    for t in old:
        if t["teacher_review_status"]!="REVIEWED_EXCERPT" or t["evidence_type"]!="DIRECT":
            continue
        verified[t["notice_version_id"]]={
            "refs":t["evidence_blocks"],"excerpt_sha256":t["excerpt_sha256"],
            "excerpt":t["excerpt_text"]}
    for t in new:
        if t["status"]!="DIRECT_EXCERPT":continue
        verified[t["notice_version_id"]]={
            "refs":t["block_indices"],"excerpt_sha256":t["selected_excerpt_sha256"],
            "excerpt":t["selected_excerpt_text"]}
    for version,t in verified.items():
        if version not in versions:raise ValueError("Review version missing from source queue")
        if sha(t["excerpt"])!=t["excerpt_sha256"]:raise ValueError("Excerpt SHA changed")
        if not t["refs"]:raise ValueError("Source refs absent")
    return verified

def check_targeted_pairs(pairs, profiles, queue, verified, existing):
    by_company={c["company_id"]:c for c in profiles["companies"]}
    by_version={r["notice_version_id"]:r for r in queue}
    protected={(r["company_id"],r["notice_version_id"]) for r in existing}
    seen=set()
    for r in pairs:
        key=r["company_id"],r["notice_version_id"]
        if key in seen:raise ValueError("Duplicate targeted pair")
        if key in protected:raise ValueError("Previously labeled pair cannot be relabeled")
        seen.add(key)
        if key[0] not in by_company or key[1] not in verified:
            raise ValueError("Unknown company or unverified task excerpt")
        n=by_version[key[1]]
        if r["notice_id"]!=n["notice_id"] or r["evidence_sha256"]!=verified[key[1]]["excerpt_sha256"]:
            raise ValueError("Source lineage mismatch")
        if r["grade"] not in (0,1,2,3) or type(r["grade"]) is not int:
            raise ValueError("Invalid grade")
        if r["human_approved"] is not False or r["label_source"]!="gpt_teacher":
            raise ValueError("Not model-authored label")
        if r["annotation_basis"]!="REVIEWED_SOURCE_EXCERPT" or r["split"]!="targeted_development":
            raise ValueError("Cannot claim independent holdout")
        if len(r["rationale"])<25:raise ValueError("Insufficient rationale")
    return {"new_pairs":len(pairs),"positive_2plus":sum(x["grade"]>=2 for x in pairs),
            "grades":dict(Counter(x["grade"] for x in pairs)),
            "distinct_positive_notice_versions":len({x["notice_version_id"] for x in pairs if x["grade"]>=2}),
            "distinct_positive_company_profiles":len({x["company_id"] for x in pairs if x["grade"]>=2}),
            "ready_for_independent_evaluation":False}

def make_pairs(profiles,queue,old,new,existing,seed):
    reviewed=build_reviewed_map(old,new,queue)
    byidx={i:r for i,r in enumerate(queue)}
    result=[]
    for r in seed:
        number=r["company_index"]
        if type(number) is not int or not 1<=number<=len(profiles["companies"]):
            raise ValueError("Out-of-range company number")
        company=profiles["companies"][number-1]
        source=byidx[r["source_index"]]
        result.append({"company_id":company["company_id"],"company_name":company["name"],
             "notice_id":source["notice_id"],"notice_version_id":source["notice_version_id"],
             "notice_title":source["title"],"grade":r["grade"],
             "rationale":r["rationale"],"evidence_sha256":reviewed[source["notice_version_id"]]["excerpt_sha256"],
             "evidence_blocks":reviewed[source["notice_version_id"]]["refs"],
             "label_source":"gpt_teacher","annotation_basis":"REVIEWED_SOURCE_EXCERPT",
             "human_approved":False,"split":"targeted_development",
             "sampling":"capability_match_and_hard_negative_not_population_prevalence"})
    return result,check_targeted_pairs(result,profiles,queue,reviewed,existing)
