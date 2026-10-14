"""PR C: audited blind-pool ranking metrics, only after verified FULL_TASK labels.

All unreviewed notices are *excluded*, never imputed grade=0.
Metrics are judged-pool lower-information diagnostics, NOT full-universe recall.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

from .relevance_eval_contract import audit, audit_pool, make_blind_pool, read_json


def _dcg(grades):
    return sum((2**g-1)/math.log2(i+2) for i,g in enumerate(grades))


def _rrf(ranked, k=60):
    scores=defaultdict(float)
    for order in ranked:
        for rank,item in enumerate(order,1): scores[item]+=1/(k+rank)
    return [x for x,_ in sorted(scores.items(),key=lambda kv:(-kv[1],kv[0]))]


def compare_independent_runs(corpus:dict,labels:dict,pool:dict,*,source_root:Path|str):
    gate=audit(corpus,labels,pool,source_root=source_root)
    if gate['status']!='READY_FOR_OFFLINE_EVALUATION':
        raise ValueError('Independent full-task evaluation is BLOCKED: '+ '; '.join(gate['errors'][:6]))
    pool_gate=audit_pool(pool,corpus)
    if pool_gate['errors']:
        raise ValueError('Independent full-universe retrieval gate failed')
    run_names=[r['model'] for r in pool['runs']]
    if len(run_names)<2:
        raise ValueError('Independent retrievers required')
    judgments=defaultdict(dict)
    for row in labels['reviews']:
        if row['split']=='test':judgments[row['company_id']][row['notice_version_id']]=row['grade']
    # Pool coverage measured, not assumed: test review versions must be in actual blind pool.
    blind=make_blind_pool(pool,corpus)['candidates']
    results={x:[] for x in run_names+['hybrid_rrf']}
    for cid,grades in judgments.items():
        if cid not in blind:raise ValueError('Missing pooled retrieval for test company '+cid)
        blind_ids={x['notice_version_id'] for x in blind[cid]}
        if not set(grades).issubset(blind_ids):
            raise ValueError('Reviews include notice not found by any independent retriever')
        actual={r['model']:r['rankings'].get(cid,[]) for r in pool['runs']}
        actual['hybrid_rrf']=_rrf(list(actual.values()))
        ideal=_dcg(sorted(grades.values(),reverse=True)[:10])
        positives={v for v,g in grades.items() if g>=2}
        for name,ranks in actual.items():
            # Caution: judged-only metric compresses unjudged ranks, not full-list nDCG.
            judged=[v for v in ranks if v in grades]
            n=(_dcg([grades[v] for v in judged[:10]])/ideal) if ideal else None
            # Denominator is pooled *judged* relevant documents, not all relevant.
            rec=len(positives.intersection(ranks[:50]))/len(positives) if positives else None
            cover=len([v for v in ranks[:10] if v in grades])/max(1,min(10,len(ranks)))
            results[name].append({'company_id':cid,'judged_ndcg_at10':n,
                                  'pooled_judged_recall_at50':rec,
                                  'observed_rank10_judgment_coverage':cover})
    output={}
    for model, rows in results.items():
        output[model]={metric:round(statistics.mean(x[metric] for x in rows if x[metric] is not None),6)
                       if any(x[metric] is not None for x in rows) else None
                       for metric in ('judged_ndcg_at10','pooled_judged_recall_at50','observed_rank10_judgment_coverage')}
    return {'status':'JUDGED_POOL_METRICS_NOT_FULL_CORPUS_ACCURACY',
            'metrics':output,'test_company_count':len(judgments),
            'coverage_limitation':'Unjudged candidates excluded; judged-only nDCG compresses unjudged ranks',
            'recall_limitation':'Recall@50 denominator is independently pooled judged relevant set, not the full notice universe',
            'accuracy_claim':'NONE_FOR_REAL_COMPANIES' if all(c['profile_origin']=='synthetic' for c in corpus['companies']) else 'HOLDOUT_ONLY',
            'corpus_sha256':gate['corpus_sha256']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--labels',type=Path,required=True)
    p.add_argument('--pool',type=Path,required=True)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=compare_independent_runs(read_json(args.corpus),read_json(args.labels),read_json(args.pool),source_root=args.source_root)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
