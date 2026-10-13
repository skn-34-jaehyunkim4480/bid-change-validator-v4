"""Regression tests for the 442-notice *development* known-positive retrieval diagnostic."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import numpy as np
import pytest
from app.ml_recommendations.known_positive_diagnostic import (
    compare_positives, read_dev_positive_labels, source_backed_documents, _rrf,
)

class FakeEncoder:
    def encode(self,texts,**kwargs):
        result=np.zeros((len(texts),3),dtype=np.float32)
        for i,t in enumerate(texts):
            result[i,0]=float('signal' in t)
            result[i,1]=float('x' in t)
            result[i,2]=1.0
        result/=np.linalg.norm(result,axis=1,keepdims=True)
        return result

def _fixture():
    docs=[{'id':f'v{i:03d}','notice_id':f'n{i:03d}',
           'title':'signal python platform' if i==0 else f'unrelated product stock {i}',
           'text':'signal python platform' if i==0 else f'unrelated product stock {i}',
           'source_type':'TITLE_ONLY'} for i in range(101)]
    queries=[{'id':'firm-x','name':'Synthetic company','text':'signal python service'},
             {'id':'firm-y','name':'Unlabeled synthetic','text':'chemicals packaging'}]
    return docs,queries,{'firm-x':{'v000'}}

def test_known_positive_coverage_with_unlabeled_candidates_not_accuracy():
    docs,queries,positive=_fixture()
    result=compare_positives(docs,queries,positive,FakeEncoder(),top=100)
    assert result['status']=='POSITIVE_ENRICHED_GPT_DEV_DIAGNOSTIC_NOT_INDEPENDENT_ACCURACY'
    assert result['candidate_versions']==101
    assert result['known_positive_pairs']==1
    assert result['company_queries']==2
    assert result['untouched_test_set'] is False
    assert result['real_business_accuracy']=='NOT_MEASURED'
    assert result['metrics']['bm25']['micro_known_positive_coverage_at_100']==1.0

def test_known_positive_must_be_in_the_same_universe():
    docs,queries,_=_fixture()
    with pytest.raises(ValueError,match='outside'):
        compare_positives(docs,queries,{'firm-x':{'missing'}},FakeEncoder(),top=100)
    with pytest.raises(ValueError,match='outside'):
        compare_positives(docs,queries,{'firm-unknown':{'v000'}},FakeEncoder(),top=100)

def test_rrf_is_symmetric_and_respects_rank():
    assert _rrf(['a','b','c'],['b','a','c'],top=3)==_rrf(['b','a','c'],['a','b','c'],top=3)
    assert _rrf(['a','c'],['a','b'],top=3)[0]=='a'

def test_duplicate_gpt_teacher_pairs_rejected(tmp_path):
    root=tmp_path
    files=[
        root/'gpt6_reviewed_excerpt_pilot_v1'/'teacher_judgments.jsonl',
        root/'gpt6_reviewed_excerpt_pilot_v2'/'targeted_dev_pairs.jsonl',
        root/'alternate_preview_dev_v1'/'alternate_preview_dev_labels.jsonl']
    for f in files:
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({'company_id':'c','notice_version_id':'v',
            'grade':2,'human_approved':False})+'\n',encoding='utf-8')
    with pytest.raises(ValueError,match='Duplicate'):
        read_dev_positive_labels(root)

def test_human_approved_judgments_rejected(tmp_path):
    root=tmp_path
    files=[
        root/'gpt6_reviewed_excerpt_pilot_v1'/'teacher_judgments.jsonl',
        root/'gpt6_reviewed_excerpt_pilot_v2'/'targeted_dev_pairs.jsonl',
        root/'alternate_preview_dev_v1'/'alternate_preview_dev_labels.jsonl']
    for i,f in enumerate(files):
        f.parent.mkdir(parents=True)
        f.write_text((json.dumps({'company_id':f'c{i}','notice_version_id':f'v{i}',
             'grade':2,'human_approved':i==0})+'\n'),encoding='utf-8')
    with pytest.raises(ValueError,match='Invalid GPT'):
        read_dev_positive_labels(root)
