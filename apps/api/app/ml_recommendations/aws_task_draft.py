"""Bounded read-only AWS current-notice document candidate extraction.

The output is a LOCAL draft requiring explicit relevance-task content review.
Never promotes a document to VERIFIED_TASK or creates labels automatically.
"""
from __future__ import annotations
import argparse
import base64
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import time

NAME_PREFER = re.compile(r"과업지시서|과업내용서|제안요청서|시방서|규격서|설계서|납품사양서|사양서|요구사항|구매규격|사업계획서|내역서", re.I)
NAME_BOILER = re.compile(r"계약집행기준|입찰유의서|계약일반조건|입찰특별유의서|계약예규|공동계약운용|공고문|개정전문|입찰공고", re.I)
HEADING = re.compile(r"(사업\s*(?:목적|개요|범위|내용)|과업\s*(?:내용|범위|목적|개요)|구축\s*(?:범위|내용)|요구\s*(?:사항|기능)|수행\s*(?:범위|내용)|사업의\s*필요성|납품\s*(?:규격|범위)|물품\s*(?:규격|사양)|사업\s*추진\s*배경)")
GARBAGE = re.compile(r"^(?:목\s*차|붙임|첨부|제\s*\d+\s*장|규정|법령|제출서류|입찰|계약)\s*(?:$|[:：])")
REMOTE = r'''
import base64,gzip,json,re
from sqlalchemy import text
from app.database import engine
version_ids=json.loads(base64.b64decode("__IDS__"))
lookup_sql="""
WITH docs AS (
 SELECT d.id,d.notice_version_id,d.name,d.file_sha256,d.extracted_text_sha256,d.extracted_char_count,d.extracted_blocks,
 ROW_NUMBER() OVER (PARTITION BY d.notice_version_id ORDER BY
 CASE WHEN d.name ~* '과업지시서|과업내용서|제안요청서|시방서|규격서|설계서|납품사양서|사양서|요구사항|구매규격|사업계획서|내역서' THEN 0
 WHEN d.name ~* '계약집행기준|입찰유의서|계약일반조건|입찰특별유의서|계약예규|공동계약운용|개정전문' THEN 3 ELSE 1 END,
 CASE WHEN d.extracted_char_count>100000 THEN 1 ELSE 0 END, d.extracted_char_count DESC NULLS LAST, d.id) rn
 FROM notice_documents d WHERE d.notice_version_id=ANY(CAST(:ids AS uuid[])) AND d.extraction_status='EXTRACTED'
 AND d.extracted_char_count >= 180 AND d.extracted_blocks IS NOT NULL
)
SELECT id::text AS doc_id, notice_version_id::text AS version_id,name,file_sha256,extracted_text_sha256,extracted_char_count,extracted_blocks
FROM docs WHERE rn=1 ORDER BY version_id
"""
with engine.connect() as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 c.execute(text('SET LOCAL statement_timeout = 11000'))
 rows=[dict(r) for r in c.execute(text(lookup_sql),{'ids':version_ids}).mappings()]
output=[]
heading=re.compile(r'(사업\s*(?:목적|개요|범위|내용)|과업\s*(?:내용|범위|목적|개요)|구축\s*(?:범위|내용)|요구\s*(?:사항|기능)|수행\s*(?:범위|내용)|사업의\s*필요성|납품\s*(?:규격|범위)|물품\s*(?:규격|사양)|사업\s*추진\s*배경)')
boiler=re.compile(r'(입찰참가자격|입찰공고|공고문|계약예규|평가기준|목\s*차|서식\s*\d+|제출서류)')
for d in rows:
 blocks=d.pop('extracted_blocks')
 scored=[]
 for i,b in enumerate(blocks):
  value=(b.get('text') or '').strip()
  if not value or not heading.search(value[:145]):continue
  if len(value)<7:continue
  if boiler.search(value[:90]):continue
  if len(value)>2000 and value.count('목 차')>1:continue
  sample=[]
  # Up to next 5 blocks within 2500 characters; preserve exact source block text.
  for nextb in blocks[i:i+6]:
   t=(nextb.get('text') or '').strip()
   if t and sum(len(x['text']) for x in sample)<2400:
    sample.append({'block_index':nextb.get('block_index'),'text':t[:850]})
  if not sample:continue
  nonboiler=sum(1 for x in sample if len(x['text'])>25 and not boiler.search(x['text'][:120]))
  score=nonboiler*3+min(len(' '.join(x['text'] for x in sample)),900)//150 - (i<60)*2
  scored.append((score,i,sample))
 scored.sort(key=lambda x:(-x[0],x[1]))
 selected=[]
 for score,i,sample in scored:
  if any(abs(i-p['start_index'])<5 for p in selected):continue
  selected.append({'start_index':i,'score':score,'blocks':sample})
  if len(selected)==3:break
 d['candidate_windows']=selected
 d['total_blocks']=len(blocks)
 output.append(d)
print('BCV4_TASK_DRAFT:'+base64.b64encode(gzip.compress(json.dumps(output,ensure_ascii=False,default=str,separators=(',',':')).encode())).decode())
'''


def aws_fetch(ssm, instance_id: str, version_ids: list[str], *, container: str):
    if not 1 <= len(version_ids) <= 25:
        raise ValueError('Restrict each AWS query to 1..25 versions')
    encoded_ids = base64.b64encode(json.dumps(version_ids).encode()).decode()
    program = REMOTE.replace('__IDS__', encoded_ids)
    script = 'import base64;exec(base64.b64decode(\'' + base64.b64encode(program.encode()).decode() + '\'))'
    command = 'docker exec ' + container + ' python -c ' + shlex.quote(script)
    response = ssm.send_command(InstanceIds=[instance_id], DocumentName='AWS-RunShellScript',
                                Parameters={'commands':[command]}, TimeoutSeconds=35)
    command_id = response['Command']['CommandId']
    for _ in range(35):
        try:
            r=ssm.get_command_invocation(CommandId=command_id,InstanceId=instance_id)
            if r['Status'] in ('Success','Failed','Cancelled','TimedOut'):break
        except ssm.exceptions.InvocationDoesNotExist:
            pass
        time.sleep(1)
    else:raise TimeoutError('SSM bounded query timed out')
    if r['Status'] != 'Success':
        raise RuntimeError('SSM bounded SQL query failed (no retry): '+r['Status']+' '+r.get('StandardErrorContent','')[:500])
    marker='BCV4_TASK_DRAFT:'
    raw=r['StandardOutputContent']
    if marker not in raw: raise RuntimeError('SSM output truncated or missing bounded payload')
    return json.loads(gzip.decompress(base64.b64decode(raw.split(marker,1)[1].splitlines()[0])))


def export(snapshot: dict, ssm, out: Path, *, max_notices=100, batch_size=15,
           instance_id='i-080c0feecbcfb9826', container='bidcheck-v4-aws-api-1'):
    if not 1<=max_notices<=200 or not 1<=batch_size<=25:
        raise ValueError('bounded export only')
    # Sample across posting dates and business types, not all latest 2026-10-12.
    notices=snapshot['notices']
    by_type = {}
    for n in sorted(notices,key=lambda x:(x.get('posted_at') or '',x['notice_version_id'])):
        by_type.setdefault(n['business_type'],[]).append(n)
    selected=[]
    for kind in sorted(by_type):
        batch=by_type[kind]
        selected.extend(batch[:max(1,max_notices//(2*len(by_type)))])
        selected.extend(batch[-max(1,max_notices//(2*len(by_type))):])
    selected=list({x['notice_version_id']:x for x in selected}.values())[:max_notices]
    out.mkdir(parents=True,exist_ok=True)
    gathered=[]
    for start in range(0,len(selected),batch_size):
        chunk=selected[start:start+batch_size]
        rows=aws_fetch(ssm,instance_id,[x['notice_version_id'] for x in chunk],container=container)
        gathered.extend(rows)
        (out/f'batch_{start//batch_size:03}.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print('BATCH',start//batch_size,'returned_documents',len(rows),flush=True)
    by_version={x['version_id']:x for x in gathered}
    draft=[]
    for n in selected:
        doc=by_version.get(n['notice_version_id'])
        draft.append({'notice_id':n['notice_id'],'notice_version_id':n['notice_version_id'],
                      'family_hint':n['bid_notice_no'].split('-')[0],
                      'posted_at':n['posted_at'],'business_type':n['business_type'],
                      'title':n['title'],'document':doc,
                      'status':'UNVERIFIED_CANDIDATE' if doc and doc['candidate_windows'] else 'NO_CANDIDATE'})
    (out/'draft.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
    counts=Counter(x['status'] for x in draft)
    return {'selected':len(selected),'source_docs':len(gathered),'candidate_status':dict(counts),
            'draft_path':str(out/'draft.json'), 'accuracy':'NOT_EVALUATED'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--max-notices',type=int,default=100)
    p.add_argument('--batch-size',type=int,default=15)
    args=p.parse_args()
    import boto3
    data=json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    print(json.dumps(export(data,boto3.client('ssm',region_name='ap-northeast-2'),args.out,
                            max_notices=args.max_notices,batch_size=args.batch_size),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
