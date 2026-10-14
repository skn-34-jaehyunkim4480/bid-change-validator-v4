"""Run a strictly exploratory GPT-6 label pilot on locally reviewed excerpts.

Not a full-notice relevance benchmark, not a heldout test.
No paid API or model download; local E5-small must already be cached.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from .light_retrieval_eval import bm25_scores,rank

def _read_jsonl(p:Path):
    return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]

def _sha(path:Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check_private_annotation(root:Path, *, originals:Path):
    """Only verifies preserved extracted block excerpts, not original S3 bytes."""
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('full_task_golden_approved') is not False or manifest.get('human_approved') is not False:
        raise ValueError('Unexpected approval status')
    for name,digest in manifest['file_sha256'].items():
        if _sha(root/name)!=digest:raise ValueError('Teacher input file SHA mismatch')
    tasks=_read_jsonl(root/'task_review.jsonl')
    labels=_read_jsonl(root/'teacher_judgments.jsonl')
    by_version={t['notice_version_id']:t for t in tasks if t.get('teacher_review_status')=='REVIEWED_EXCERPT'}
    if not by_version or len(labels)!=manifest['judged_pair_count']:
        raise ValueError('Wrong review counts')
    checked=0
    for item in by_version.values():
        rel=Path(item['source_blocks_file'])
        if rel.is_absolute() or '..' in rel.parts or rel.parts[0]!='source_blocks':
            raise ValueError('Unsafe source path')
        full=(originals/rel).resolve()
        if not full.is_relative_to(originals.resolve()):
            raise ValueError('Source path escape')
        raw=full.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['cached_source_sha256']:
            raise ValueError('Source block snapshot mismatch')
        blocks={b['block_index']:b['text'] for b in json.loads(raw.decode('utf-8'))}
        text='\n'.join(blocks[i] for i in item['evidence_blocks'])
        if text!=item['excerpt_text'] or hashlib.sha256(text.encode()).hexdigest()!=item['excerpt_sha256']:
            raise ValueError('Excerpt evidence mismatch')
        checked+=1
    pairs=set()
    for x in labels:
        pair=x['company_id'],x['notice_version_id']
        if pair in pairs:raise ValueError('Duplicate firm/task judgment')
        pairs.add(pair)
        if x['notice_version_id'] not in by_version:raise ValueError('Unverified task labeled')
        item=by_version[x['notice_version_id']]
        if x['notice_id']!=item['notice_id'] or x['evidence_sha256']!=item['excerpt_sha256']:
            raise ValueError('Stale or cross-notice judgment')
        if x['label_source']!='gpt_teacher' or x['human_approved'] is not False:
            raise ValueError('Not a model-authored unapproved annotation')
        if x['annotation_basis']!='REVIEWED_SOURCE_EXCERPT':
            raise ValueError('Not full-task or original source review')
        if type(x['grade']) is not int or x['grade'] not in (0,1,2,3):
            raise ValueError('Invalid relevance grade')
        if len(x['rationale'])<35:raise ValueError('Missing rationale')
    return by_version,labels,{'checked_excerpts':checked,'grade_distribution':dict(Counter(x['grade'] for x in labels))}

def _ndcg(order,grades,k=10):
    def dcg(grade_list):
        return sum((2**g-1)/math.log2(i+2) for i,g in enumerate(grade_list[:k]))
    ideal=dcg(sorted(grades.values(),reverse=True))
    return dcg([grades[i] for i in order])/ideal if ideal else None

def compare_pilot(tasks,labels,model,profiles):
    """Rank the same small judged-only pool; no full-corpus retrieval recall claim."""
    selected=sorted(tasks.values(),key=lambda x:x['notice_version_id'])
    docs=[{'id':x['notice_version_id'],'text':x['title']+'\n'+x['excerpt_text']}
          for x in selected]
    groups=defaultdict(list)
    for x in labels:groups[x['company_id']].append(x)
    names={c['company_id']:c for c in profiles['companies']}
    company_queries=[]
    for cid in sorted(groups):
        if cid not in names:raise ValueError('Missing firm in profile snapshot')
        c=names[cid]
        terms=[i.get('name','') for i in c.get('industries',[])]
        terms.extend(c.get('performances',[]))
        terms.extend(i.get('role','') for i in c.get('staff_roles',[]))
        terms.extend(c.get('certifications',[]))
        q=' '.join(str(x) for x in terms if x).strip()
        if not q:raise ValueError('Empty firm capabilities')
        if len(groups[cid])!=len(docs):raise ValueError('Incomplete judged candidate matrix')
        company_queries.append({'id':cid,'text':q})
    bm=bm25_scores(docs,company_queries)
    encode_start=time.perf_counter()
    passage_vec=model.encode(['passage: '+x['text'] for x in docs],
             batch_size=12,normalize_embeddings=True,show_progress_bar=False)
    query_vec=model.encode(['query: '+x['text'] for x in company_queries],
             normalize_embeddings=True,show_progress_bar=False)
    runtime=time.perf_counter()-encode_start
    byq={}
    for index,query in enumerate(company_queries):
        cid=query['id']
        labels_by_doc={x['notice_version_id']:x['grade'] for x in groups[cid]}
        a=rank(docs,bm[cid],len(docs))
        b=rank(docs,(passage_vec@query_vec[index]).tolist(),len(docs))
        rrf=defaultdict(float)
        for order in (a,b):
            for pos,vid in enumerate(order,1):rrf[vid]+=1/(60+pos)
        c=sorted(rrf,key=lambda v:(-rrf[v],v))
        byq[cid]={'company_name':names[cid]['name'],
                  'positive_judgments':sum(x>=2 for x in labels_by_doc.values()),
                  'bm25_ndcg10':_ndcg(a,labels_by_doc),
                  'e5_ndcg10':_ndcg(b,labels_by_doc),
                  'hybrid_rrf_ndcg10':_ndcg(c,labels_by_doc),
                  'ranking_top3_grades':{name:[labels_by_doc[x] for x in rankings[:3]]
                      for name,rankings in [('bm25',a),('e5',b),('rrf',c)]}}
    valid=[r for r in byq.values() if r['positive_judgments']>0]
    return {'status':'EXPLORATORY_MODEL_AUTHORED_EXCERPT_PILOT_ONLY',
        'notice_count':len(docs),'company_count':len(byq),
        'companies_with_grade2plus':len(valid),'judgment_count':len(labels),
        'original_s3_sha_verified':False,'temporal_holdout':False,
        'family_closure_verified':False,'human_approved':False,
        'blind_to_search_rankings_when_judging':True,
        'full_task_benchmark':'NOT_RUN','full_corpus_recall':'NOT_RUN',
        'e5_cpu_embedding_seconds':round(runtime,3),
        'nDCG10_mean_across_firms_with_positive':{
           name:round(statistics.mean(x[name+'_ndcg10'] for x in valid),5)
           if valid else None for name in ('bm25','e5','hybrid_rrf')},
        'per_company':byq}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--annotations',required=True,type=Path)
    p.add_argument('--source-root',required=True,type=Path)
    p.add_argument('--profiles',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    tasks,labels,checks=check_private_annotation(args.annotations,originals=args.source_root)
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(min(torch.get_num_threads(),6))
    m=SentenceTransformer('intfloat/multilingual-e5-small',device='cpu',trust_remote_code=False,local_files_only=True)
    m.max_seq_length=256
    profile=json.loads(args.profiles.read_text(encoding='utf-8-sig'))
    result=compare_pilot(tasks,labels,m,profile)
    result['annotation_integrity']=checks
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
