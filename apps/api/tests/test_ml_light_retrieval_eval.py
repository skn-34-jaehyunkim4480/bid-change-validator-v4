from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Independent CPU retrieval smoke. Synthetic only: never an accuracy benchmark."""
from pathlib import Path
import json
import numpy as np
from app.ml_recommendations.light_retrieval_eval import (
    bm25_scores,build_records,companies,dense_scores,evaluate_unlabeled,rank,tokens,
)


class FakeModel:
    def encode(self, texts, **kwargs):
        # The projection intentionally differs from BM25.
        rows=[]
        for x in texts:
            rows.append([float('시스템' in x), float('인쇄' in x),float('건설' in x)])
        values=np.array(rows,dtype=np.float32)
        norms=np.linalg.norm(values,axis=1,keepdims=True)
        return values/np.where(norms==0,1,norms)


def snapshot():
    return {'companies':[
        {'company_id':'q1','name':'합성기업', 'industries':[{'name':'정보시스템 소프트웨어'}],
         'certifications':[],'performances':[],'staff_roles':[]},
        {'company_id':'q2','name':'역량 없음', 'industries':[],
         'certifications':[],'performances':[],'staff_roles':[]},
    ],'notices':[
        {'notice_version_id':'v1','title':'정보시스템 유지보수'},
        {'notice_version_id':'v2','title':'건설공사 납품'},
        {'notice_version_id':'v3','title':'책자 인쇄 제작'},
        {'notice_version_id':'v4','title':'컴퓨터 시스템 개발'},
    ]}


def test_corpus_never_prefilters_by_bm25():
    s=snapshot();docs=build_records(s);q=companies(s)
    assert len(docs)==4
    assert len(q)==1
    bm=bm25_scores(docs,q)
    assert len(bm['q1'])==4
    dense,lat=dense_scores(docs,q,model=FakeModel())
    assert len(dense['q1'])==4
    assert len(lat)==1
    assert rank(docs,bm['q1'],2)[0] in {'v1','v4'}


def test_unverified_draft_is_diagnostic_not_approved():
    s=snapshot();unverified=[
        {'notice_version_id':'v2','status':'UNVERIFIED_CANDIDATE',
         'document':{'candidate_windows':[{'blocks':[{'text':'정보시스템 관리'}]}]}},
        {'notice_version_id':'v3','status':'NO_CANDIDATE',
         'document':{'candidate_windows':[{'blocks':[{'text':'정보시스템 관리'}]}]}},
    ]
    docs=build_records(s,draft=unverified)
    assert docs[1]['task_candidate'] is True
    assert '정보시스템 관리' in docs[1]['text']
    assert docs[2]['task_candidate'] is False
    assert docs[2]['text']=='책자 인쇄 제작'


def test_no_accuracy_claims_when_labels_absent():
    r=evaluate_unlabeled(snapshot(),model=FakeModel(),top=3)
    assert r['metrics']['ndcg_at_10']=='NOT_RUN'
    assert r['metrics']['pooled_recall_at_50']=='NOT_RUN'
    assert r['independent_full_universe'] is True
    assert r['shared_bm25_prefilter'] is False
    assert set(r['rankings']['q1'])=={'bm25','e5_small','hybrid_rrf'}
    assert len(r['rankings']['q1']['bm25'])==3
    assert len(r['rankings']['q1']['e5_small'])==3


def test_korean_character_bigrams_available():
    assert '유지' in tokens('유지보수')
    assert '보수' in tokens('유지보수')
