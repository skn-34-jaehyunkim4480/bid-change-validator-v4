"""Read-only, bounded AWS RDS document -> local corpus extraction through SSM.

Writes ONLY to the local --out directory. Never changes AWS RDS/S3 or deploys.
Source excerpts are UNVERIFIED candidate text, NOT independently judged scope.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path
import re
import shlex
import time

from .full_task_corpus import build_corpus, document_priority, save_corpus

INSTANCE = "i-080c0feecbcfb9826"
CONTAINER = "bidcheck-v4-aws-api-1"
MARKER = "ML_CORPUS_DATA:"
REMOTE = r'''
import base64,gzip,json,re
from sqlalchemy import text
from app.database import engine
args=json.loads(base64.b64decode("__ARGS__"))
if len(args["ids"])>25:raise ValueError("Overlarge query batch")
with engine.connect() as c:
 c.execute(text("SET TRANSACTION READ ONLY"))
 c.execute(text("SET LOCAL statement_timeout = 10000"))
 if args["kind"]=="metadata":
  rows=[dict(r) for r in c.execute(text("""
   SELECT id::text document_id,notice_version_id::text version_id,name,
    extraction_status,extracted_char_count,file_sha256,extracted_text_sha256
   FROM notice_documents WHERE notice_version_id=ANY(CAST(:ids AS uuid[]))
     AND extraction_status='EXTRACTED' AND extracted_char_count >= 180
     AND jsonb_typeof(extracted_blocks)='array'
   ORDER BY notice_version_id,id
   """),{"ids":args["ids"]}).mappings()]
 else:
  rows=[dict(r) for r in c.execute(text("""
   SELECT id::text document_id,notice_version_id::text version_id,
    extracted_blocks
   FROM notice_documents WHERE id=ANY(CAST(:ids AS uuid[]))
    AND extraction_status='EXTRACTED'
   """),{"ids":args["ids"]}).mappings()]
  heading=re.compile(r"사업\s*(?:개요|내용|목적|범위)|과업\s*(?:지시|내용|범위|목적)|수행\s*(?:업무|내용|범위)|요구\s*(?:기능|사항)|물품\s*(?:규격|사양)|납품\s*(?:규격|범위)|공사\s*(?:내용|개요)|구축\s*(?:내용|범위)|기술\s*(?:사양|규격)",re.I)
  boiler=re.compile(r"입찰참가자격|계약보증|입찰보증|청렴계약|개찰일시|계약일반조건|서약|제출서류")
  for d in rows:
   blocks=d.pop("extracted_blocks") or []
   ranked=[]
   for i,b in enumerate(blocks):
    if not isinstance(b,dict):continue
    raw=str(b.get("text") or "").strip()
    if len(raw)<25 or boiler.search(raw[:100]):continue
    strong=bool(heading.search(raw[:180]))
    if raw.count("........")>3:continue
    score=10*strong+min(len(raw),400)/150
    if i<15 and not strong:score-=2
    ranked.append((score,i,b.get("block_index",i),raw))
   ranked.sort(key=lambda x:(-x[0],x[1]))
   found=[];positions=[]
   for sc,i,ix,raw in ranked:
    if any(abs(i-j)<2 for j in positions):continue
    if len(found)>=8:break
    positions.append(i)
    found.append({"block_index":ix if isinstance(ix,int) else i,"text":raw[:750]})
   d["extracted_blocks"]=sorted(found,key=lambda b:b["block_index"])
   d["original_block_count"]=len(blocks)
payload=gzip.compress(json.dumps(rows,ensure_ascii=False,default=str,separators=(",",":")).encode(),compresslevel=7)
print("ML_CORPUS_DATA:"+base64.b64encode(payload).decode())
'''


def fetch(ssm, kind: str, ids: list[str], *, instance=INSTANCE, container=CONTAINER) -> list[dict]:
    if kind not in {"metadata", "blocks"} or not (1 <= len(ids) <= 25):
        raise ValueError("Invalid bounded AWS query")
    params = base64.b64encode(json.dumps({"kind": kind, "ids": ids}).encode()).decode()
    program = REMOTE.replace("__ARGS__", params)
    encoded = base64.b64encode(program.encode()).decode()
    code = f"import base64;exec(base64.b64decode('{encoded}'))"
    cmd = "docker exec " + shlex.quote(container) + " python -c " + shlex.quote(code)
    resp = ssm.send_command(InstanceIds=[instance], DocumentName="AWS-RunShellScript",
                            Parameters={"commands": [cmd]}, TimeoutSeconds=45,
                            Comment="Read-only notice document extraction for offline ML corpus")
    ident = resp["Command"]["CommandId"]
    for _ in range(45):
        try:
            result = ssm.get_command_invocation(CommandId=ident, InstanceId=instance)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(1)
            continue
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"SSM query timeout: {ident}")
    if result["Status"] != "Success":
        raise RuntimeError(f"SSM read query {ident}: {result['Status']} {result['StandardErrorContent'][:900]}")
    try:
        if MARKER not in result["StandardOutputContent"]:
            raise ValueError("SSM marker absent")
        raw = result["StandardOutputContent"].split(MARKER, 1)[1].splitlines()[0]
        return json.loads(gzip.decompress(base64.b64decode(raw)))
    except (ValueError, EOFError, OSError, json.JSONDecodeError):
        # AWS SSM stdout is capped (~24 KiB). Split, never silently accept partial text.
        if len(ids) == 1:
            raise ValueError(f"Single document exceeded SSM output limit: {ident}")
        pivot = len(ids) // 2
        return fetch(ssm, kind, ids[:pivot], instance=instance, container=container) + fetch(
            ssm, kind, ids[pivot:], instance=instance, container=container)


def export(ssm, snapshot: dict, root: Path, *, batch_size=12, max_versions=0) -> dict:
    if not 1 <= batch_size <= 20:
        raise ValueError("Batch size must be in 1..20")
    versions = list(dict.fromkeys(n["notice_version_id"] for n in snapshot["notices"]))
    if max_versions:
        versions = versions[:max_versions]
    selected = set(versions)
    root.mkdir(parents=True, exist_ok=True)
    # Resume only on a full-success file for each independent batch.
    meta = []
    for start in range(0, len(versions), batch_size):
        file = root / f"meta_{start:04d}.json"
        if file.exists():
            rows = json.loads(file.read_text(encoding="utf-8"))
        else:
            rows = fetch(ssm, "metadata", versions[start:start+batch_size])
            file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        meta.extend(rows)
        print("META", start, "docs", len(rows), flush=True)
    candidates = {}
    for doc in meta:
        candidates.setdefault(doc["version_id"], []).append(doc)
    to_fetch = []
    for vid in versions:
        eligible = sorted(candidates.get(vid, []), key=document_priority)
        # Prioritize a clear task-named attachment; inspect a secondary if needed.
        to_fetch.extend(eligible[:2])
    excerpts = []
    ids = list(dict.fromkeys(d["document_id"] for d in to_fetch))
    for start in range(0, len(ids), 6):
        file = root / f"blocks_{start:04d}.json"
        if file.exists():
            rows = json.loads(file.read_text(encoding="utf-8"))
        else:
            rows = fetch(ssm, "blocks", ids[start:start+6])
            file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        excerpts.extend(rows)
        print("BLOCKS", start, "docs", len(rows), flush=True)
    frozen = {"companies": snapshot.get("companies", []),
              "notices": [n for n in snapshot["notices"] if n["notice_version_id"] in selected]}
    report = save_corpus(frozen, meta, excerpts, root / "corpus.json")
    report["extracted_docs_fetched"] = len(meta)
    report["versions_metadata_fetched"] = len({m["version_id"] for m in meta})
    report["document_excerpts_selected"] = len(excerpts)
    report["notices_with_fallback"] = report["statuses"].get("TITLE_FALLBACK", 0)
    report["aws_mutations"] = 0
    (root/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--batch-size", type=int, default=12)
    p.add_argument("--max-versions", type=int, default=0)
    p.add_argument("--region", default="ap-northeast-2")
    args = p.parse_args()
    import boto3
    snap = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    print(json.dumps(export(boto3.client("ssm", region_name=args.region),snap,args.out,
                            batch_size=args.batch_size,max_versions=args.max_versions),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
