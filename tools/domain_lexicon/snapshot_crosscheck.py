"""Small stratified out-of-sample snapshot check; never adds candidate records.

Not a live AWS audit. Preserves build/holdout separation and writes only aggregates.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from build import ROOT, context_role_candidate, excerpt, phrase_pattern

INPUT = ROOT / "eval/golden/notice-changes-30d"
TRAINING = ROOT / "eval/golden/notice-sample-20261006f"


def run(*, limit_per_type: int = 8) -> dict:
    manifest = json.loads((INPUT / "manifest.json").read_text(encoding="utf8"))
    training_manifest = json.loads((TRAINING / "manifest.json").read_text(encoding="utf8"))
    training_notices = {n["dir"] for n in training_manifest["notices"]}
    training_shas = {hashlib.sha256(p.read_bytes()).hexdigest() for p in TRAINING.rglob("*.blocks.json")}
    vocab = json.loads((ROOT / "data/domain_lexicon/candidates-v0.1.json").read_text(encoding="utf8"))
    items = [(x["surface"],x["domain"],phrase_pattern(x["surface"])) for x in vocab["expression_records"]]
    per_type = Counter()
    matched = defaultdict(set)
    roles = defaultdict(Counter)
    sampled = []
    file_hashes = set()
    for notice in manifest["changed"] + manifest["unselected"]:
        kind = notice.get("business_type")
        versions = sorted(notice.get("versions", []), key=lambda v: v.get("order", ""))
        if not versions:
            continue
        version = versions[-1]
        notice_round = version.get("dir")
        if not kind or per_type[kind] >= limit_per_type or notice_round in training_notices:
            continue
        candidates = [(INPUT / notice_round / x["blocks"]) for x in version.get("documents",[]) if x.get("blocks")]
        candidates = [x for x in candidates if x.exists()]
        if not candidates:
            continue
        source = candidates[0]
        raw = source.read_bytes()
        source_sha = hashlib.sha256(raw).hexdigest()
        if source_sha in training_shas:
            continue
        file_hashes.add(source_sha)
        per_type[kind] += 1
        sampled.append(notice_round)
        for block in json.loads(raw.decode("utf-8-sig")):
            text = block.get("text", "")
            if not text:
                continue
            for surface, domain, pattern in items:
                m = pattern.search(text)
                if m:
                    matched[surface].add(notice_round)
                    roles[surface][context_role_candidate(excerpt(text,m.start(),m.end()))] += 1
    return {"dataset_role":"INDEPENDENT_OUT_OF_SAMPLE_SNAPSHOT_NOT_LIVE_AWS",
            "source_manifest":"eval/golden/notice-changes-30d/manifest.json",
            "sampling_cap_per_type":limit_per_type,
            "sample_rounds":len(sampled),"sample_unique_file_sha256":len(file_hashes),
            "business_types":dict(per_type),"training_round_overlap":len(set(sampled)&training_notices),
            "training_file_sha_overlap":len(file_hashes&training_shas),
            "lexicon_expression_count":len(items),"observed_existing_expressions":len(matched),
            "not_observed_in_this_sample":len(items)-len(matched),
            "by_domain":dict(Counter(domain for surface,domain,_ in items if surface in matched)),
            "multi_context_candidate_surfaces": {s:dict(c) for s,c in roles.items() if len(c)>=2 and sum(c.values())>=3 and s in {"수행실적","입찰참가자격","중소기업","본점 소재지","등록","납품실적"}},
            "scope_warning":"Unobserved does not mean obsolete; source is historical and only a small stratified sample."}


if __name__=="__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2))
