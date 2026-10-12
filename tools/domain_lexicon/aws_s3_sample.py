"""Bounded S3 PDF original audit. No raw documents, credentials, or user data written.

Original S3 bytes are not the RDS extraction. This run has MAX 3 GETs / 1.2MiB.
"""
from __future__ import annotations
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path

BUCKET = "bidcheck-dev-docs-226234259348-apne2"
PREFIX = "R26BK017"
MAX_BYTES = 400_000
MAX_GETS = 3


def run() -> dict:
    import boto3
    from pypdf import PdfReader
    root = Path(__file__).resolve().parents[2]
    forms = {x["surface"] for x in json.loads((root/"data/domain_lexicon/candidates-v0.1.json").read_text(encoding="utf8"))["expression_records"] if len(x["surface"])>=3}
    client = boto3.Session(region_name="ap-northeast-2").client("s3")
    page = client.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, MaxKeys=90)
    selected = []
    used_notices = set()
    for item in page.get("Contents",[]):
        key, size = item["Key"], item["Size"]
        notice = key.split('/')[0]
        if notice in used_notices or not key.lower().endswith('.pdf') or not 0<size<=MAX_BYTES:
            continue
        used_notices.add(notice)
        selected.append(item)
        if len(selected)==MAX_GETS:
            break
    rows = []
    for item in selected:
        blob = client.get_object(Bucket=BUCKET,Key=item["Key"])["Body"].read(MAX_BYTES+1)
        assert len(blob)==item["Size"] and len(blob)<=MAX_BYTES
        is_pdf = blob.startswith(b"%PDF-")
        text = ""
        if is_pdf:
            try:
                reader = PdfReader(io.BytesIO(blob),strict=False)
                text = "\n".join(page.extract_text() or "" for page in reader.pages[:6])[:25000]
            except Exception:
                pass
        hits = sorted(t for t in forms if t in text)
        rows.append({"notice_no":item["Key"].split('/')[0], "bytes":len(blob),
                    "file_sha256":hashlib.sha256(blob).hexdigest(),
                    "pdf_magic_valid":is_pdf,"extract_text_characters":len(text),
                    "known_lexicon_terms_detected":len(hits),"sample_terms":hits[:12]})
    return {"source":"LIVE_AWS_S3_ORIGINAL_OBJECTS_NOT_RDS_EXTRACTIONS",
            "read_only":True,"api_operations":{"list_objects_v2":1,"get_object":len(rows)},
            "max_gets":MAX_GETS,"max_bytes_each":MAX_BYTES,"total_bytes":sum(r["bytes"] for r in rows),
            "paid_openai_calls":0,"documents":rows}

if __name__ == "__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2))
