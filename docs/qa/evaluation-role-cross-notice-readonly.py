"""Read-only cross-notice scoring role audit for BidCheck engine.

Run inside an existing authorized AWS API container with the deployed read-only DB
credentials. The caller injects the exact proposed PR guard source into
PR_GUARD_SOURCE_B64 (base64-encoded UTF-8); no deployed code is modified.
Outputs only public tender numbers, summary statistics, selected requirement
and document snippets. Does not write to DB or local disk.
"""
from __future__ import annotations
import base64, json, os, re
from collections import Counter
from sqlalchemy import text
from app.database import SessionLocal
from bidengine.contracts import Evidence, EvidenceLocation, QualificationRequirement
from bidengine.pipeline.analysis_pipeline import QualificationDocumentInput, _build_global_chunks

guard_src=base64.b64decode(os.environ["PR_GUARD_SOURCE_B64"]).decode("utf8")
ns={"__name__":"pr_guard_test"}
exec(compile(guard_src, "PR108/evaluation_role_guard.py", "exec"), ns)
guard=ns["guard_scoring_only_performance"]
score_heading=re.compile(r"(?:정량\s*평가|정량적\s*평가|평가\s*항목|수행실적\s*평가|실적\s*평가|배점|평가\s*등급|평점|점수)",re.I)
eligibility_heading=re.compile(r"(?:입찰\s*참가\s*자격|참가\s*자격\s*및\s*조건|입찰\s*참가\s*조건)")
out=[]
with SessionLocal() as s:
    s.execute(text("SET TRANSACTION READ ONLY"))
    pairs=s.execute(text("""
    select distinct r.id run_id, r.notice_version_id ver_id, n.bid_notice_no notice_no, v.version_number, r.created_at
    from qualification_analysis_runs r join qualification_requirements q on q.analysis_run_id=r.id
    join bid_notice_versions v on v.id=r.notice_version_id
    join bid_notices n on n.id=v.notice_id
    where q.requirement_role='mandatory' and q.type in
    ('PERFORMANCE_AMOUNT','PERFORMANCE_COUNT','EXPERIENCE_FIELD')
    and jsonb_array_length(coalesce(q.evidence_keys,'[]'::jsonb))>0
    order by n.bid_notice_no, v.version_number, r.created_at
    """)).mappings().all()
    chunks_by_version={}
    summary=Counter()
    for row in pairs:
        verid=row["ver_id"]
        if verid not in chunks_by_version:
            docs=s.execute(text("""
            select id, file_sha256, extracted_text_sha256, extracted_blocks
            from notice_documents where notice_version_id=:v
            and extraction_status='EXTRACTED' and extracted_blocks is not null
            order by document_order,id
            """), {"v":verid}).mappings().all()
            inputs=[QualificationDocumentInput(
                document_id=str(d["id"]),file_sha256=d["file_sha256"],
                extracted_text_sha256=d["extracted_text_sha256"],
                extracted_blocks=d["extracted_blocks"]
            ) for d in docs]
            chunks=_build_global_chunks(inputs,max_chunk_chars=1800)
            chunks_by_version[verid]=chunks
        else: chunks=chunks_by_version[verid]
        by_id={c["chunk_id"]:c["text"] for c in chunks}
        items=s.execute(text("""
        select requirement_key, type, requirement_role, raw, evidence_keys
        from qualification_requirements where analysis_run_id=:r
        and requirement_role='mandatory' and type in
        ('PERFORMANCE_AMOUNT','PERFORMANCE_COUNT','EXPERIENCE_FIELD')
        """),{"r":row["run_id"]}).mappings().all()
        evid=s.execute(text("""
        select evidence_key, document_id, source_type, chunk_id, quote
        from qualification_evidence where analysis_run_id=:r
        """),{"r":row["run_id"]}).mappings().all()
        refs=[Evidence(
            evidence_key=e["evidence_key"], source_type=e["source_type"],
            document_id=str(e["document_id"]),chunk_id=e["chunk_id"],
            quote=e["quote"],location=EvidenceLocation()
        ) for e in evid]
        requirements=[QualificationRequirement(
            requirement_key=q["requirement_key"],notice_version_id=str(verid),
            type=q["type"],raw=q["raw"],evidence_keys=q["evidence_keys"] or [],
            requirement_role=q["requirement_role"],
        ) for q in items]
        new,diags=guard(requirements,refs,chunks)
        e_by_key={e.evidence_key:e for e in refs}
        for old,modified in zip(requirements,new):
            contexts=[by_id.get(e_by_key[k].chunk_id,"")
                      for k in old.evidence_keys if k in e_by_key]
            score=any(score_heading.search(ctx) for ctx in contexts)
            elig=any(eligibility_heading.search(ctx) for ctx in contexts)
            info={"notice":row["notice_no"],"version":row["version_number"],
                  "run":str(row["run_id"])[:8], "key":old.requirement_key,
                  "type":old.type, "changed":modified.requirement_role!="mandatory",
                  "evidence_chunks":[e_by_key[k].chunk_id if k in e_by_key else None for k in old.evidence_keys],
                  "has_score_signal":score,"has_eligibility_signal":elig,
                  "raw":(old.raw or "")[:170],
                  "chunk_headings":[str(ctx)[:135] for ctx in contexts[:2]]}
            out.append(info)
            summary["total_items"]+=1
            summary["changed" if info["changed"] else "unchanged"]+=1
            summary["score_signal_items" if score else "no_score_signal_items"]+=1
            if score and not info["changed"]:summary["score_signal_not_downgraded"]+=1
            if elig and info["changed"]:summary["eligibility_signal_downgraded"]+=1
    summary["runs"]=len(pairs)
    summary["versions"]=len(chunks_by_version)
    summary["public_notice_numbers"]=len(set(x["notice"] for x in out))
    summary["extracted_chunks"]=sum(len(x) for x in chunks_by_version.values())
print("CROSS_SUMMARY "+json.dumps(summary,ensure_ascii=True))
for item in out:print("CROSS_ITEM "+json.dumps(item,ensure_ascii=True))