"""CPU-only independent BM25 vs pretrained E5-small retrieval smoke/evaluation.

Never claims recommendation accuracy without independent verified FULL_TASK judgments.
The title-only frozen snapshot and UNVERIFIED task drafts are exploratory ONLY.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time

TOKEN=re.compile(r"[가-힣A-Za-z0-9]+")


def tokens(value: str):
    """No extra tokenizer dependency; supports Korean character bigrams as well as words."""
    parts=TOKEN.findall(value.lower())
    terms=[]
    for part in parts:
        terms.append(part)
        if re.search(r'[가-힣]',part) and len(part)>=2:
            terms.extend(part[i:i+2] for i in range(len(part)-1))
    return terms


def build_records(snapshot:dict, *, draft:list[dict]|None=None):
    """One document per version; draft text stays UNVERIFIED and cannot train a model."""
    draft_by_version={row['notice_version_id']:row for row in draft or []}
    docs=[]
    for n in snapshot['notices']:
        version=n['notice_version_id']
        row=draft_by_version.get(version)
        snippets=[]
        if row and row.get('status')=='UNVERIFIED_CANDIDATE':
            for window in (row.get('document') or {}).get('candidate_windows',[])[:1]:
                snippets.extend(b.get('text','') for b in window.get('blocks',[])[:5])
        task=' '.join(snippets).strip()
        docs.append({'id':version, 'title':n['title'], 'text':n['title']+ ('\n'+task if task else ''),
                     'task_candidate':bool(task), 'title_only':not bool(task)})
    if len({d['id'] for d in docs})!=len(docs):raise ValueError('Repeated current notice version')
    return docs


def companies(snapshot:dict):
    rows=[]
    for c in snapshot['companies']:
        parts=[x.get('name','') for x in c.get('industries',[])]
        parts.extend(c.get('performances',[]))
        parts.extend(c.get('certifications',[]))
        parts.extend(x.get('role','') for x in c.get('staff_roles',[]))
        text=' '.join(dict.fromkeys(str(p) for p in parts if p)).strip()
        if not text:continue # Can't infer relevance for capability-unknown firms.
        rows.append({'id':c['company_id'], 'name':c['name'], 'text':text})
    return rows


def bm25_scores(docs:list[dict],queries:list[dict]):
    doc_terms=[tokens(row['text']) for row in docs]
    counts=[Counter(d) for d in doc_terms]
    doc_freq=Counter(t for c in counts for t in c)
    n=len(docs);avg=sum(sum(c.values()) for c in counts)/max(1,n)
    results={}
    for q in queries:
        qt=set(tokens(q['text']))
        scores=[]
        for c in counts:
            dl=sum(c.values());value=0.0
            for term in qt:
                f=c[term]
                if not f:continue
                df=doc_freq[term]
                idf=math.log(1+(n-df+.5)/(df+.5))
                value+=idf*f*2.2/(f+1.2*(.25+.75*dl/max(1,avg)))
            scores.append(value)
        results[q['id']]=scores
    return results


def dense_scores(docs:list[dict],queries:list[dict], *, model):
    import numpy as np
    docs_np=model.encode(['passage: '+d['text'] for d in docs],batch_size=16,
                         normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    result={};latencies=[]
    for q in queries:
        started=time.perf_counter()
        q_emb=model.encode(['query: '+q['text']],normalize_embeddings=True,
                           convert_to_numpy=True,show_progress_bar=False)
        value=(docs_np @ q_emb[0]).tolist()
        latencies.append((time.perf_counter()-started)*1000)
        result[q['id']]=value
    return result,latencies


def rank(docs,scores,top=100):
    return [docs[i]['id'] for i in sorted(range(len(docs)),key=lambda i:(-scores[i],docs[i]['id']))[:top]]


def evaluate_unlabeled(snapshot,*,draft=None,model,top=100):
    docs=build_records(snapshot,draft=draft);queries=companies(snapshot)
    start=time.perf_counter();bm=bm25_scores(docs,queries);bm_time=time.perf_counter()-start
    start=time.perf_counter();dense,latencies=dense_scores(docs,queries,model=model)
    dense_time=time.perf_counter()-start
    measurements=[];rankings={}
    for q in queries:
        key=q['id'];a=rank(docs,bm[key],top);b=rank(docs,dense[key],top)
        rrf=defaultdict(float)
        for order in (a,b):
            for idx,item in enumerate(order,1):rrf[item]+=1/(60+idx)
        union=sorted(set(a)|set(b),key=lambda i:(-rrf[i],i))
        rankings[key]={'bm25':a,'e5_small':b,'hybrid_rrf':union}
        measurements.append({'company_id':key,'name':q['name'],
                             'bm25_e5_overlap_top10':len(set(a[:10])&set(b[:10])),
                             'bm25_e5_overlap_top50':len(set(a[:50])&set(b[:50])),
                             'union_top100':len(set(a)|set(b))})
    return {'status':'RETRIEVAL_SMOKE_NO_ACCURACY_LABELS',
            'evaluation_scope':'UNREVIEWED_CURRENT_SNAPSHOT_DO_NOT_PROMOTE',
            'query_count':len(queries),'notice_count':len(docs),
            'task_candidate_count':sum(x['task_candidate'] for x in docs),
            'independent_full_universe':True, 'shared_bm25_prefilter':False,
            'top_n':top,'metrics':{'ndcg_at_10':'NOT_RUN','pooled_recall_at_50':'NOT_RUN',
                      'reason':'Independent company/full-task relevance judgment absent'},
            'speed':{'bm25_all_queries_seconds':round(bm_time,3),
                     'e5_corpus_plus_queries_seconds':round(dense_time,3),
                     'e5_query_latency_p50_ms':round(statistics.median(latencies),2),
                     'e5_query_latency_p95_ms':round(sorted(latencies)[min(len(latencies)-1,math.ceil(.95*len(latencies))-1)],2)},
            'sampled_candidate_diversity':measurements,'rankings':rankings}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--draft',type=Path,help='UNVERIFIED source snippets; diagnostic ablation only')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--model',default='intfloat/multilingual-e5-small')
    p.add_argument('--top',type=int,default=100)
    args=p.parse_args()
    if not 1<=args.top<=100:raise ValueError('Top N capped at 100')
    snapshot=json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    draft=json.loads(args.draft.read_text(encoding='utf-8-sig')) if args.draft else None
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(min(6,torch.get_num_threads()))
    model=SentenceTransformer(args.model,device='cpu',local_files_only=True,trust_remote_code=False)
    model.max_seq_length=256
    result=evaluate_unlabeled(snapshot,draft=draft,model=model,top=args.top)
    result['retrieval_input_sha256']=hashlib.sha256(json.dumps(build_records(snapshot,draft=draft),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    small={k:v for k,v in result.items() if k not in ('rankings','sampled_candidate_diversity')}
    small['candidate_overlap_top10_mean']=round(statistics.mean(x['bm25_e5_overlap_top10'] for x in result['sampled_candidate_diversity']),2)
    small['candidate_union_top100_mean']=round(statistics.mean(x['union_top100'] for x in result['sampled_candidate_diversity']),2)
    print(json.dumps(small,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
