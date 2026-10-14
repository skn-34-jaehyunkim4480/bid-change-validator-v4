"""Verify private offline source-block snapshots without trusting heuristic labels."""
from __future__ import annotations
import hashlib,json
from pathlib import Path

def verify_frozen_review_queue(out:Path)->dict:
    out=out.resolve()
    rows=[json.loads(x) for x in (out/'task_review_queue.jsonl').read_text(encoding='utf-8').splitlines() if x]
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    accepted=0
    for r in rows:
        s=r.get('source_document')
        if s is None:
            if r['verification_status']=='AWAITING_TASK_REVIEW':
                raise ValueError('Candidate without source evidence')
            continue
        relative=Path(s['source_file'])
        if relative.is_absolute() or '..' in relative.parts or not s['source_file'].startswith('source_blocks/'):
            raise ValueError('Unsafe evidence file path')
        file=(out/relative).resolve()
        if not file.is_relative_to(out):raise ValueError('Evidence path outside review root')
        raw=file.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=s['extracted_block_export_sha256']:
            raise ValueError('Cached source SHA mismatch')
        blocks=json.loads(raw.decode('utf-8'))
        mapping={b['block_index']:b['text'] for b in blocks}
        if len(mapping)!=len(blocks) or len(blocks)!=s['selected_block_count']:
            raise ValueError('Wrong block inventory')
        if any(ref not in mapping for w in r['candidate_windows'] for ref in w['block_refs']):
            raise ValueError('Referenced block missing')
        combined='\n'.join(mapping[i] for i in sorted(mapping) if mapping[i].strip())
        if combined!=r['candidate_text'] or hashlib.sha256(combined.encode()).hexdigest()!=s['excerpt_sha256']:
            raise ValueError('Excerpt content changed')
        if s['notice_version_id']!=r['notice_version_id'] or s['notice_id']!=r['notice_id']:
            raise ValueError('Cross-notice provenance mismatch')
        accepted+=1
    if len(rows)!=manifest['input_versions'] or accepted!=manifest['source_candidate_versions']:
        raise ValueError('Manifest size mismatch')
    for name,digest in manifest['source_sha256'].items():
        if hashlib.sha256((out/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Manifest digest mismatch')
    return {'status':'EXTRACTED_CACHE_SHA_VERIFIED_NOT_TASK_REVIEWED','candidate_count':accepted,
            'accuracy':'NOT_EVALUATED','S3_original_bytes_verified':False}
