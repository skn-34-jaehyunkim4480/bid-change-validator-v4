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

def prepare_alternate_reviews(root: Path, selected: dict[int, list[int]], out: Path,
                              *, targets_file: str = "alternate_targets_8.json",
                              sample_files: tuple[str, ...] | None = None,
                              scope_status: dict[int, str] | None = None,
                              preview_char_limit: int = 550):
    """Review an arbitrary bounded set of version-bound alternate source previews.

    Existing 8-source snapshots remain reproducible. Partial/insufficient scope
    is retained explicitly and never auto-approved as a valid task label.
    """
    if Path(targets_file).name != targets_file or not 1 <= preview_char_limit <= 3000:
        raise ValueError("Unsafe target name or preview character limit")
    targets={x["document_id"]:x for x in read(root/targets_file)}
    indexes={x["index"] for x in targets.values()}
    if not 1 <= len(targets) <= 25 or len(indexes)!=len(targets) or not set(selected).issubset(indexes) or not selected:
        raise ValueError("Require unique target versions and nonempty reviewed subset (max 25)")
    allowed={"DIRECT_TASK_EXCERPT","PARTIAL_TASK_EXCERPT","INSUFFICIENT_SOURCE"}
    if scope_status is not None and (set(scope_status)!=set(selected) or any(v not in allowed for v in scope_status.values())):
        raise ValueError("Every review must have a valid explicit task-scope status")
    if sample_files is None:
        sample_files=tuple(f"alternate_small_{i}.json" for i in range(0,len(targets),2))
    if len(sample_files)!=len(set(sample_files)) or not sample_files:
        raise ValueError("Duplicate/empty source sample names")
    rows=[]
    seen=set()
    for sample_name in sample_files:
        if Path(sample_name).name!=sample_name or not sample_name.endswith(".json"):
            raise ValueError("Unsafe sample filename")
        f=root/sample_name
        for d in read(f):
            doc_id=d["id"]
            if doc_id not in targets:
                raise ValueError("Unknown alternate source document")
            target=targets[doc_id]
            if target["index"] not in selected:
                continue
            if doc_id in seen:
                raise ValueError("Duplicate alternate source document")
            seen.add(doc_id)
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
                "source_block_text_clipped_to_550_chars":preview_char_limit==550,
                "source_block_preview_char_limit":preview_char_limit,
                "source_block_preview_may_be_truncated":any(
                    x.get("full_char_count",len(x["text"]))>len(x["text"])
                    for x in d["sample"] if x["block_index"] in refs),
                "task_scope_status":scope_status[target["index"]] if scope_status else "UNVERIFIED_TASK_SCOPE",
                "review_status":"PRELIMINARY_TASK_EVIDENCE_ONLY",
                "reviewer":"gpt-6-chat",
                "human_approved":False,
                "full_task_verified":False,
                "source_S3_object_independently_verified":False,
            })
    if len(rows)!=len(selected):
        raise ValueError("Incomplete selected source document set")
    rows.sort(key=lambda x:x["reviewed_candidate_index"])
    out.mkdir(parents=True,exist_ok=False)
    path=out/"alternate_review_candidates.jsonl"
    path.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows),encoding="utf-8")
    summary={
        "status":"PRELIMINARY_ONLY",
        "alternate_attachment_count":len(rows),
        "recovered_task_excerpt_candidates":sum(
            x["task_scope_status"]=="DIRECT_TASK_EXCERPT" for x in rows)
            if scope_status else len(rows),
        "review_scope_status_counts":dict(Counter(x["task_scope_status"] for x in rows)),
        "no_human_approval":True,
        "full_task_accuracy_ready":False,
        "candidate_indexes":[x["reviewed_candidate_index"] for x in rows],
        "review_file_sha256":sha256(path.read_bytes()).hexdigest(),
        "warning":f"Preview blocks limited to {preview_char_limit} characters; RDS SHA fields are metadata, not independently hashed full originals.",
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
        if excerpt.get("task_scope_status") in ("INSUFFICIENT_SOURCE","PARTIAL_TASK_EXCERPT"):
            raise ValueError("Cannot label an incomplete or partial task excerpt as complete")
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

def verify_complete_selected_blocks(root: Path, review_dir: Path,
                                   full_files: tuple[str, ...], manifest_file: Path | None = None):
    """Check full contents of SELECTED extracted RDS blocks against cached previews.

    This is NOT full attachment verification, S3 SHA validation or HUMAN_REVIEWED.
    """
    baseline=verify_alternate_review(root,review_dir)
    reviews=[json.loads(x) for x in (review_dir/"alternate_review_candidates.jsonl").read_text(encoding="utf-8").splitlines() if x]
    expected={x["document_id"]:x for x in reviews}
    if not full_files or len(set(full_files))!=len(full_files):
        raise ValueError("Missing or duplicated full source filenames")
    checked={}
    sources={}
    for name in full_files:
        if Path(name).name!=name or not name.endswith(".json"):
            raise ValueError("Unsafe source file path")
        path=root/name
        sources[name]=sha256(path.read_bytes()).hexdigest()
        for doc in read(path):
            doc_id=doc["document_id"]
            if doc_id not in expected or doc_id in checked:
                raise ValueError("Duplicate or unknown full source document")
            review=expected[doc_id]
            if doc["version_id"]!=review["notice_version_id"]:
                raise ValueError("Full block version mismatch")
            if (doc["file_sha256"]!=review["file_sha256_rds"] or
                doc["extracted_text_sha256"]!=review["extracted_text_sha256_rds"]):
                raise ValueError("Full block RDS source SHA metadata mismatch")
            blocks=doc["blocks"]
            actual={b["block_index"]:b["text"] for b in blocks}
            refs=review["sample_block_indices"]
            if len(actual)!=len(blocks) or set(actual)!=set(refs):
                raise ValueError("Complete selected blocks differ from cited indexes")
            preview_file=root/review["sample_file"]
            source=next(x for x in read(preview_file) if x["id"]==doc_id)
            prev={b["block_index"]:b["text"] for b in source["sample"]}
            limit=review.get("source_block_preview_char_limit",550)
            for idx in refs:
                if prev[idx]!=actual[idx][:limit]:
                    raise ValueError("Selected full source block differs from preview")
                recorded_length=next(b.get("full_char_count") for b in source["sample"] if b["block_index"]==idx)
                if recorded_length is not None and len(actual[idx])!=recorded_length:
                    raise ValueError("Original extracted block length mismatch")
            joined="\n".join(actual[idx] for idx in refs)
            checked[doc_id]={"full_selected_block_sha256":sha256(joined.encode("utf-8")).hexdigest(),
                             "complete_selected_block_chars":len(joined),
                             "review_index":review["reviewed_candidate_index"],
                             "task_scope_status":review.get("task_scope_status","UNVERIFIED_TASK_SCOPE")}
    if set(checked)!=set(expected):
        raise ValueError("Not all selected original blocks were re-read")
    result={"verification_status":"COMPLETE_SELECTED_RDS_BLOCKS_ONLY",
            "verified_document_count":len(checked),
            "full_attachment_verified":False,
            "S3_original_verified":False,
            "human_approved":False,
            "source_file_sha256":sources,
            "verified_documents":checked,
            "source_review_sha256":sha256((review_dir/"alternate_review_candidates.jsonl").read_bytes()).hexdigest()}
    if manifest_file is not None:
        if manifest_file.exists():
            raise FileExistsError("Do not overwrite evidence manifest")
        manifest_file.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def audit_alternate_family_overlap(queue: list[dict], reviews: list[dict], lineage: dict):
    """Report split leakage risks without declaring unobserved relations complete."""
    from collections import defaultdict
    by_notice=defaultdict(set)
    by_digest=defaultdict(set)
    sampled_ids=set()
    for row in reviews:
        idx=row["reviewed_candidate_index"]
        q=queue[idx]
        if q["notice_version_id"]!=row["notice_version_id"]:
            raise ValueError("Review queue/source version mismatch")
        nid=q["notice_id"]
        sampled_ids.add(nid)
        by_notice[nid].add(idx)
        digest=row.get("extracted_text_sha256_rds")
        if digest:by_digest[digest].add(idx)
    confirmed=[x for x in lineage["edges"] if x["match_confidence"]=="CONFIRMED"
               and x.get("previous_notice_id")]
    external=set()
    for edge in confirmed:
        a,b=edge["notice_id"],edge["previous_notice_id"]
        if a in sampled_ids and b not in sampled_ids:external.add(a)
        if b in sampled_ids and a not in sampled_ids:external.add(b)
    return {
        "status":"FAMILY_CLOSURE_UNVERIFIED",
        "reviewed_versions":len(reviews),
        "distinct_notices":len(by_notice),
        "same_notice_multiple_version_groups":sorted(
            [sorted(indices) for indices in by_notice.values() if len(indices)>1]),
        "same_extracted_text_digest_groups":sorted(
            [sorted(indices) for indices in by_digest.values() if len(indices)>1]),
        "confirmed_relation_edges_observed":len(confirmed),
        "seed_notices_connected_to_outside_sample":len(external),
        "visited_notice_ids_in_bounded_relation_trace":len(lineage.get("visited_ids",[])),
        "independent_time_family_split_ready":False,
    }
