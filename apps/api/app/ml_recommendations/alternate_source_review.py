"""Verify alternate AWS RDS-extracted preview snippets, without promoting them to Golden.

Does not download or independently verify original S3 objects; reviews are model-authored.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def prepare_alternate_reviews(root: Path, selected: dict[int, list[int]], out: Path):
    targets={x["document_id"]:x for x in read(root/"alternate_targets_8.json")}
    if len(targets)!=8 or set(selected)!={x["index"] for x in targets.values()}:
        raise ValueError("Expected eight unique source versions and reviewed source indices")
    rows=[]
    seen=set()
    for batch_index in (0,2,4,6):
        f=root/f"alternate_small_{batch_index}.json"
        for d in read(f):
            doc_id=d["id"]
            if doc_id not in targets or doc_id in seen:
                raise ValueError("Unknown or duplicate alternate source document")
            seen.add(doc_id)
            target=targets[doc_id]
            if d["version_id"]!=target["version_id"]:
                raise ValueError("Alternate document mismatch to notice version")
            if d["file_sha256"]!=target["file_sha256"] or d["extracted_text_sha256"]!=target["extracted_text_sha256"]:
                raise ValueError("AWS source digest metadata changed")
            sample={b["block_index"]:b["text"] for b in d["sample"]}
            if len(sample)!=len(d["sample"]):
                raise ValueError("Duplicate source blocks")
            refs=selected[target["index"]]
            if not refs or any(k not in sample for k in refs):
                raise ValueError("Referenced source block missing")
            excerpt="\n".join(sample[k] for k in refs)
            if len(excerpt)<40:
                raise ValueError("Preview excerpt too short for preliminary review")
            rows.append({
                "reviewed_candidate_index":target["index"],
                "notice_version_id":target["version_id"],
                "document_id":doc_id,
                "document_name":target["name"],
                "file_sha256_rds":d["file_sha256"],
                "extracted_text_sha256_rds":d["extracted_text_sha256"],
                "sample_file":f.name,
                "sample_file_sha256":sha256(f.read_bytes()).hexdigest(),
                "sample_block_indices":refs,
                "task_excerpt_preview":excerpt,
                "task_excerpt_sha256":sha256(excerpt.encode("utf-8")).hexdigest(),
                "source_block_text_clipped_to_550_chars":True,
                "review_status":"PRELIMINARY_TASK_EVIDENCE_ONLY",
                "reviewer":"gpt-6-chat",
                "human_approved":False,
                "full_task_verified":False,
                "source_S3_object_independently_verified":False,
            })
    if len(rows)!=len(targets):
        raise ValueError("Incomplete set of eight documents")
    rows.sort(key=lambda x:x["reviewed_candidate_index"])
    out.mkdir(parents=True,exist_ok=False)
    path=out/"alternate_review_candidates.jsonl"
    path.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows),encoding="utf-8")
    summary={
        "status":"PRELIMINARY_ONLY",
        "alternate_attachment_count":len(rows),
        "recovered_task_excerpt_candidates":len(rows),
        "no_human_approval":True,
        "full_task_accuracy_ready":False,
        "candidate_indexes":[x["reviewed_candidate_index"] for x in rows],
        "review_file_sha256":sha256(path.read_bytes()).hexdigest(),
        "warning":"Remote extracted block texts cached with first 550 characters only; RDS SHA fields are source metadata, not independent verification of complete source objects.",
    }
    (out/"manifest.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary
import csv
from collections import Counter
from pathlib import Path

def persist_preview_dev_labels(root: Path, snapshot: dict, seed_file: Path, review_dir: Path, output: Path, old_pairs: list[dict]):
    """Explicit GPT-authored development labels for preview evidence; never benchmark ready."""
    existing={(x["company_id"],x["notice_version_id"]) for x in old_pairs}
    reviews=[json.loads(s) for s in (review_dir/"alternate_review_candidates.jsonl").read_text(encoding="utf-8").splitlines() if s]
    by_idx={x["reviewed_candidate_index"]:x for x in reviews}
    with seed_file.open("r",encoding="utf-8-sig",newline="") as f:
        seed=list(csv.DictReader(f,delimiter="\t"))
    labels=[]
    pairs=set()
    for row in seed:
        ci=int(row["company_index"])
        idx=int(row["source_index"])
        grade=int(row["grade"])
        if not 1<=ci<=len(snapshot["companies"]) or idx not in by_idx or grade not in (0,1,2):
            raise ValueError("Invalid development row")
        company=snapshot["companies"][ci-1]
        excerpt=by_idx[idx]
        pair=company["company_id"],excerpt["notice_version_id"]
        if pair in existing or pair in pairs:
            raise ValueError("Duplicate or previously used label")
        pairs.add(pair)
        if len(row["rationale"])<30:
            raise ValueError("Explain the task and company capabilities explicitly")
        labels.append({
            "company_id":company["company_id"],
            "company_name":company["name"],
            "notice_version_id":excerpt["notice_version_id"],
            "document_id":excerpt["document_id"],
            "grade":grade,
            "rationale":row["rationale"],
            "evidence_block_indices":excerpt["sample_block_indices"],
            "evidence_sha256":excerpt["task_excerpt_sha256"],
            "label_source":"gpt_teacher",
            "annotation_basis":"ALTERNATE_EXTRACTED_BLOCK_PREVIEW",
            "preview_truncated":True,
            "split":"targeted_development",
            "human_approved":False,
            "full_task_approved":False,
            "notice_family_closure":"UNVERIFIED"
        })
    if not labels or output.exists():
        raise ValueError("Refuse empty or overwriting label set")
    output.mkdir(parents=True)
    file=output/"alternate_preview_dev_labels.jsonl"
    file.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in labels),encoding="utf-8")
    summary={
        "new_pairs":len(labels),
        "positive_2plus":sum(x["grade"]>=2 for x in labels),
        "distinct_positive_notice_versions":len({x["notice_version_id"] for x in labels if x["grade"]>=2}),
        "grade_counts":dict(Counter(x["grade"] for x in labels)),
        "status":"TARGETED_DEVELOPMENT_MODEL_AUTHORED_UNVERIFIED_PREVIEWS",
        "independent_test_ready":False,
        "human_approved":False,
        "sha256":sha256(file.read_bytes()).hexdigest(),
    }
    (output/"manifest.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary

def verify_alternate_review(root: Path, review_dir: Path):
    """Check frozen preview bytes and version-bound block references, not full originals."""
    manifest=read(review_dir/"manifest.json")
    file=review_dir/"alternate_review_candidates.jsonl"
    if sha256(file.read_bytes()).hexdigest()!=manifest["review_file_sha256"]:
        raise ValueError("Frozen review manifest SHA drift")
    rows=[json.loads(x) for x in file.read_text(encoding="utf-8").splitlines() if x]
    if len(rows)!=manifest["alternate_attachment_count"]:
        raise ValueError("Review count drift")
    seen=set()
    for row in rows:
        if row["document_id"] in seen:
            raise ValueError("Duplicate source document")
        seen.add(row["document_id"])
        if row["human_approved"] or row["full_task_verified"] or row["source_S3_object_independently_verified"]:
            raise ValueError("Unexpected approval flag")
        sample_path=root/row["sample_file"]
        if sample_path.parent.resolve()!=root.resolve():
            raise ValueError("Unsafe preview source path")
        if sha256(sample_path.read_bytes()).hexdigest()!=row["sample_file_sha256"]:
            raise ValueError("Preview source cache SHA drift")
        original=next((x for x in read(sample_path) if x["id"]==row["document_id"]),None)
        if original is None or original["version_id"]!=row["notice_version_id"]:
            raise ValueError("Missing source document / version")
        blocks={x["block_index"]:x["text"] for x in original["sample"]}
        refs=row["sample_block_indices"]
        if not refs or any(k not in blocks for k in refs):
            raise ValueError("Missing preview source block")
        joined="\n".join(blocks[k] for k in refs)
        if joined!=row["task_excerpt_preview"] or sha256(joined.encode()).hexdigest()!=row["task_excerpt_sha256"]:
            raise ValueError("Excerpt hash mismatch")
    return {"verified_previews":len(rows),"full_task_verified":False,"human_approved":False}
