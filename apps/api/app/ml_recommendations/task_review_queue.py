"""Offline-only PR C: build provenance-backed, *unverified* task review queue.

Input: bounded, previously fetched AWS candidate drafts and confirmed relation audit.
No training labels, no model preference, no AWS writes, no automatic FULL_TASK approval.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime

from .relevance_eval_contract import SCHEMA, audit, sha, text_sha
from .relevance_eval_inventory import import_title_snapshot, _master_codes

_HEX = re.compile(r'^[a-f0-9]{64}$')


def _read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _check_datetime(value: str):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not d.utcoffset() and d.tzinfo is None:
        raise ValueError('Timezone-aware posted_at required')
    return value


def _doc_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9-]{32,40}', value):
        raise ValueError('Invalid source document identifier')
    return value


def checked_family_hints(rows: list[dict], relations: list[dict]):
    """Union CONFIRMED edges only; outside sample edges BLOCK closure."""
    ids={x['notice_id'] for x in rows}
    parents={x:x for x in ids}
    def find(a):
        while parents[a] != a:
            parents[a]=parents[parents[a]]
            a=parents[a]
        return a
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:parents[max(a,b)]=min(a,b)
    external=set();pending=set();edges=0
    for x in relations:
        a,b=x.get('notice_id'),x.get('previous_notice_id')
        if x.get('match_confidence')!='CONFIRMED':
            if a in ids:pending.add(a)
            if b in ids:pending.add(b)
            continue
        if a not in ids and b not in ids:continue
        if b and a in ids and b in ids:
            union(a,b);edges+=1
        elif b:
            if a in ids:external.add(a)
            if b in ids:external.add(b)
        else:
            if a in ids:pending.add(a)
    family={x:find(x) for x in ids}
    # A family is BLOCKED if any member points outside the sampled universe.
    blocked_families={family[x] for x in external | pending}
    return family,{'confirmed_internal_edges':edges,
                   'external_relation_notice_count':len(external),
                   'uncertain_relation_notice_count':len(pending),
                   'blocked_family_ids':sorted(blocked_families),
                   'status':'UNVERIFIED_CLOSURE',
                   'reason':'Single-hop sample cannot prove complete relation closure'}


def materialize_review_queue(snapshot: dict, drafts: list[dict], relations: list[dict],
                             industry_master: dict, out: Path):
    """Materialize immutable task *candidates*; no valid accuracy evaluation follows."""
    if not drafts or out.exists():
        raise ValueError('Nonempty input and new output directory required; never overwrite frozen outputs')
    versions=set();ordered=[]
    for x in drafts:
        version=x['notice_version_id']
        if version in versions:raise ValueError('Duplicate notice_version_id')
        versions.add(version);ordered.append(x)
    ordered.sort(key=lambda x:(x['posted_at'],x['notice_version_id']))
    families,lineage_report=checked_family_hints(ordered,relations)
    template=import_title_snapshot(snapshot,master_industries=industry_master,
                                  snapshot_sha256=sha(snapshot),collected_at='2026-10-13T00:00:00Z')
    corpus={"schema_version":SCHEMA,"collected_at":"2026-10-13T00:00:00Z",
            "family_linkage_status":"UNVERIFIED",
            "companies":template['companies'],"notices":[]}
    out.mkdir(parents=True)
    source_dir=out/'source_blocks';source_dir.mkdir()
    reviews=[];counts=Counter();dates=Counter();bad_hashes=0
    for entry in ordered:
        ver=entry['notice_version_id'];notice_id=entry['notice_id'];_check_datetime(entry['posted_at']);dates[entry['posted_at'][:7]]+=1
        body={"notice_id":notice_id,"notice_version_id":ver,
              "family_id":families[notice_id],"title":entry['title'],
              "business_type":entry['business_type'],"posted_at":entry['posted_at'],
              "task_text":"","body_status":"UNVERIFIED","task_evidence":[]}
        doc=entry.get('document');record={"notice_id":notice_id,"notice_version_id":ver,
               "title":entry['title'],"business_type":entry['business_type'],
               "posted_at":entry['posted_at'],"family_hint":families[notice_id],
               "relation_closure":"PENDING",
               "verification_status":"NO_TASK_CANDIDATE", "source_document":None,
               "candidate_text":"", "candidate_windows":[]}
        if doc:
            _doc_id(doc['doc_id'])
            if doc['version_id'] != ver:raise ValueError('RDS source belongs to another notice version')
            for key in ('file_sha256','extracted_text_sha256'):
                if doc.get(key) and not _HEX.fullmatch(doc[key]):
                    raise ValueError('Invalid RDS stored SHA256')
            seen={};windows=[]
            for window in doc.get('candidate_windows',[]):
                refs=[]
                for b in window.get('blocks',[]):
                    idx=b.get('block_index');t=b.get('text')
                    if type(idx) is not int or idx<0 or not isinstance(t,str):
                        raise ValueError('Invalid source block')
                    if idx in seen and seen[idx]!=t:raise ValueError('Block index reused with different text')
                    seen[idx]=t;refs.append(idx)
                if refs:windows.append({"block_refs":refs,"heuristic_score":window['score'],
                                      "start_index":window['start_index']})
            if seen:
                artifact=[{"block_index":i,"text":seen[i]} for i in sorted(seen)]
                raw=json.dumps(artifact,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
                file_name='source_blocks/'+doc['doc_id']+'.blocks.json'
                (out/file_name).write_bytes(raw)
                candidate='\n'.join(seen[i] for i in sorted(seen) if seen[i].strip())
                record.update(verification_status='AWAITING_TASK_REVIEW', candidate_text=candidate,
                              candidate_windows=windows)
                counts['has_source_block_candidates']+=1
                record['source_document']={"source_file":file_name,
                    "extracted_block_export_sha256":hashlib.sha256(raw).hexdigest(),
                    "original_file_sha256":doc.get('file_sha256'),
                    "extracted_text_sha256":doc.get('extracted_text_sha256'),
                    "document_id":doc['doc_id'],"file_name":doc.get('name'),
                    "notice_version_id":ver,"notice_id":notice_id,
                    "excerpt_sha256":text_sha(candidate),"selected_block_count":len(artifact)}
            else:counts['no_candidate_blocks']+=1
        else:counts['no_extracted_document_selected']+=1
        corpus['notices'].append(body)
        reviews.append(record)
    inventory=audit(corpus)
    if inventory['status']!='NOT_READY' or not any('relation closure' in x.lower() for x in inventory['errors']):
        raise AssertionError('No-label and incomplete-family corpus must remain blocked')
    (out/'corpus_unverified.json').write_text(json.dumps(corpus,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'task_review_queue.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in reviews),encoding='utf-8')
    manifest={'schema_version':SCHEMA,'review_status':'AWAITING_HUMAN_TASK_VERIFICATION',
         'accuracy_status':'NOT_EVALUATED','no_label_generation':True,
         'input_versions':len(ordered),'source_candidate_versions':counts['has_source_block_candidates'],
         'status_counts':dict(counts),'dates':dict(dates),
         'lineage':lineage_report,'source_sha256':{
            'task_review_queue.jsonl':hashlib.sha256((out/'task_review_queue.jsonl').read_bytes()).hexdigest(),
            'corpus_unverified.json':hashlib.sha256((out/'corpus_unverified.json').read_bytes()).hexdigest()},
         'audit':inventory}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--draft',action='append',type=Path,required=True)
    p.add_argument('--relations',type=Path,required=True)
    p.add_argument('--industry-master',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    data=[x for file in args.draft for x in _read(file)]
    result=materialize_review_queue(_read(args.snapshot),data,_read(args.relations)['relations'],
                                    _master_codes(args.industry_master),args.out)
    print(json.dumps({k:v for k,v in result.items() if k!='audit'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
