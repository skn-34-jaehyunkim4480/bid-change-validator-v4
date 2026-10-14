"""Title-only GPT Teacher retrospective pilot; NOT full-task or model selection evidence."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
from .light_retrieval_eval import bm25_scores,rank


def evaluate_title_only(pairs,model):
    groups=defaultdict(list)
    for p in pairs:
        if p.get('split')=='test':
            if p.get('label_source')!='gpt_teacher' or not isinstance(p.get('label'),int):
                raise ValueError('Independent GPT Teacher labels only; no pseudo labels')
            groups[p['company_id']].append(p)
    if not groups:raise ValueError('No test split')
    def ndcg(order,grades):
        def dcg(ids):return sum((2**grades[i]-1)/math.log2(j+2) for j,i in enumerate(ids))
        ideal=dcg(sorted(grades,key=lambda x:-grades[x]))
        return dcg(order)/ideal if ideal else 0
    per=[]
    for cid, group in sorted(groups.items()):
        docs=[{'id':x['pair_id'],'text':x['notice_text']} for x in group]
        query={'id':cid,'text':group[0]['query_text']}
        bm=bm25_scores(docs,[query])[cid]
        bm_order=rank(docs,bm,top=len(docs))
        q_emb=model.encode(['query: '+query['text']],normalize_embeddings=True)
        passages=model.encode(['passage: '+d['text'] for d in docs],normalize_embeddings=True)
        e5_order=rank(docs,(passages @ q_emb[0]).tolist(),top=len(docs))
        labels={x['pair_id']:x['label'] for x in group}
        per.append({'company_id':cid,'judgments':len(group),'relevant':sum(x>=2 for x in labels.values()),
                    'bm25_ndcg10':round(ndcg(bm_order,labels),6),
                    'e5_ndcg10':round(ndcg(e5_order,labels),6)})
    return {'scope':'TITLE_ONLY_TWO_COMPANY_PILOT_NOT_FOR_MODEL_SELECTION',
            'company_count':len(groups),'pair_count':sum(len(g) for g in groups.values()),
            'bm25_ndcg10':round(statistics.mean(x['bm25_ndcg10'] for x in per),6),
            'e5_ndcg10':round(statistics.mean(x['e5_ndcg10'] for x in per),6),
            'full_task_accuracy':'NOT_RUN', 'real_company_generalization':'NOT_VALIDATED',
            'results':per}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairs',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer('intfloat/multilingual-e5-small',device='cpu',local_files_only=True)
    model.max_seq_length=256
    pairs=[json.loads(x) for x in args.pairs.read_text(encoding='utf-8').splitlines() if x]
    result=evaluate_title_only(pairs,model)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
