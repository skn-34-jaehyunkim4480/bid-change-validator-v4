"""Bounded read-only AWS snapshot for an isolated synthetic-company experiment.

Only seeded Golden profiles and public notice metadata leave RDS. SSM executes
SELECT in a read-only transaction; this module never writes to AWS or invokes
the application's LLM/RAG paths. Output is local and must not be committed.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path


REGION = "ap-northeast-2"

REMOTE_QUERY = r'''
import base64, gzip, json
from sqlalchemy import text
from app.database import engine

params = json.loads(base64.b64decode("__PARAMS__"))
COMPANIES = """
SELECT c.id::text AS company_id, c.name, c.region_name, c.company_size,
  COALESCE((SELECT json_agg(json_build_object('code',ci.industry_code,'name',ic.name))
    FROM company_industries ci LEFT JOIN industry_codes ic ON ic.code=ci.industry_code
    WHERE ci.company_id=c.id),'[]'::json) AS industries,
  COALESCE((SELECT json_agg(cc.name) FROM company_certifications cc
    WHERE cc.company_id=c.id),'[]'::json) AS certifications,
  COALESCE((SELECT json_agg(json_build_object('role',sr.role_name,'headcount',sr.headcount))
    FROM company_staff_roles sr WHERE sr.company_id=c.id),'[]'::json) AS staff_roles,
  COALESCE((SELECT json_agg(cp.name) FROM company_performances cp
    WHERE cp.company_id=c.id),'[]'::json) AS performances
FROM app_users u JOIN companies c ON c.id=u.company_id
WHERE u.username ~ '^golden-j(0[1-9]|[12][0-9]|3[0-2])$'
  AND c.business_registration_number = '9902' || lpad(substring(u.username from 9),6,'0')
ORDER BY u.username
"""
NOTICES = """
WITH active AS (
  SELECT n.id::text AS notice_id, n.bid_notice_no, n.title,
    n.business_type, n.announcing_institution_name AS institution,
    v.id::text AS notice_version_id, v.version_number,
    v.posted_at::text AS posted_at, v.bid_closed_at::text AS bid_closed_at,
    v.contract_method,
    COALESCE((SELECT json_agg(nr.previous_notice_id::text)
      FROM notice_relations nr WHERE nr.notice_id=n.id
        AND nr.match_confidence='CONFIRMED'),'[]'::json) AS previous_notice_ids,
    row_number() OVER (PARTITION BY n.business_type
      ORDER BY v.posted_at DESC NULLS LAST,n.id) AS type_rank
  FROM bid_notices n JOIN bid_notice_versions v
    ON v.notice_id=n.id AND v.is_current=true
  WHERE v.collected_at <= CAST(:as_of AS timestamptz)
    AND (v.bid_closed_at > CAST(:as_of AS timestamptz)
      OR (v.bid_closed_at IS NULL AND v.posted_at IS NOT NULL
        AND v.posted_at <= CAST(:as_of AS timestamptz)
        AND v.posted_at > CAST(:as_of AS timestamptz) - interval '40 days'))
    AND lower(coalesce(v.notice_kind,n.notice_kind,'')) NOT LIKE '%취소%'
    AND lower(coalesce(v.notice_kind,n.notice_kind,'')) NOT LIKE '%cancel%'
    AND lower(coalesce(v.notice_kind,n.notice_kind,'')) NOT LIKE '%무효%'
)
SELECT notice_id,bid_notice_no,title,business_type,institution,
  notice_version_id,version_number,posted_at,bid_closed_at,contract_method,
  previous_notice_ids
FROM active WHERE type_rank <= :per_type
ORDER BY business_type,posted_at DESC NULLS LAST,notice_id
LIMIT :page_size OFFSET :offset
"""
with engine.connect() as conn:
    conn.execute(text("SET TRANSACTION READ ONLY"))
    if params["kind"] == "companies":
        rows = [dict(r) for r in conn.execute(text(COMPANIES)).mappings()]
    else:
        rows = [dict(r) for r in conn.execute(text(NOTICES), params).mappings()]
raw = json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":")).encode()
print("BCV4_SNAPSHOT:" + base64.b64encode(gzip.compress(raw)).decode())
'''


def _remote_command(params: dict, container: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", container):
        raise ValueError("Invalid Docker container name")
    param_data = base64.b64encode(json.dumps(params).encode()).decode()
    source = REMOTE_QUERY.replace("__PARAMS__", param_data)
    encoded = base64.b64encode(source.encode()).decode()
    python_call = f"import base64;exec(base64.b64decode('{encoded}'))"
    return f"docker exec {container} python -c {shlex.quote(python_call)}"


def _fetch(ssm, instance_id: str, container: str, params: dict) -> list[dict]:
    sent = ssm.send_command(
        InstanceIds=[instance_id], DocumentName="AWS-RunShellScript",
        Parameters={"commands": [_remote_command(params, container)]}, TimeoutSeconds=60,
    )
    command_id = sent["Command"]["CommandId"]
    for _ in range(45):
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(1)
            continue
        if result["Status"] in {"Success", "Failed", "Cancelled", "TimedOut"}:
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"Read-only SSM query did not finish: {command_id}")
    if result["Status"] != "Success":
        raise RuntimeError(f"Read-only SSM query failed ({result['Status']}): {command_id}")
    marker = "BCV4_SNAPSHOT:"
    output = result["StandardOutputContent"]
    if marker not in output:
        raise ValueError(f"Missing bounded snapshot output: {command_id}")
    encoded = output.split(marker, 1)[1].splitlines()[0]
    return json.loads(gzip.decompress(base64.b64decode(encoded)))


def export(ssm, out: Path, *, instance_id: str, container: str,
           per_type: int = 100, page_size: int = 40) -> dict:
    if not 1 <= per_type <= 125 or not 1 <= page_size <= 50:
        raise ValueError("AWS sample must remain bounded to 500 public notices")
    if not re.fullmatch(r"i-[a-f0-9]{8,17}", instance_id):
        raise ValueError("Invalid EC2 instance ID")
    as_of = datetime.now(timezone.utc).isoformat()
    companies = _fetch(ssm, instance_id, container, {"kind": "companies"})
    if len(companies) != 32:
        raise ValueError(f"Expected 32 seeded synthetic companies, found {len(companies)}")
    notices = []
    for offset in range(0, per_type * 4, page_size):
        batch = _fetch(ssm, instance_id, container, {"kind": "notices", "as_of": as_of,
                             "per_type": per_type, "page_size": page_size,
                             "offset": offset})
        notices.extend(batch)
        if len(batch) < page_size:
            break
    if len({n["notice_version_id"] for n in notices}) != len(notices):
        raise ValueError("Snapshot contains duplicate current notice versions")
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "snapshot.json"
    snapshot.write_text(json.dumps({"companies": companies, "notices": notices},
                                   ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    manifest = {
        "schema": "bidcheck-ml-synthetic-aws-sample-v1",
        "as_of_utc": as_of, "source": "AWS RDS read-only via SSM",
        "companies": len(companies), "notices": len(notices),
        "business_types": {kind: sum(n["business_type"] == kind for n in notices)
                           for kind in sorted({n["business_type"] for n in notices})},
        "data_scope": "seeded synthetic company profiles + public notice metadata only",
        "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "paid_llm_calls": 0,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--per-type", type=int, default=100)
    args = parser.parse_args()
    import boto3
    result = export(boto3.client("ssm", region_name=args.region), args.out,
                    instance_id=args.instance_id, container=args.container,
                    per_type=args.per_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
