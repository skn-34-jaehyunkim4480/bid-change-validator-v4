from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pytest
from app.ml_recommendations.title_only_teacher_pilot import evaluate_title_only

class MockModel:
    def encode(self,words,**kwargs):
        z=[]
        for text in words:z.append([float('네트워크' in text),float('조경' in text)])
        arr=np.asarray(z,dtype=np.float32)
        n=np.linalg.norm(arr,axis=1,keepdims=True)
        return arr/np.where(n==0,1,n)

def test_teacher_title_only_pilot_does_not_claim_accuracy():
    test=[{'split':'test','label_source':'gpt_teacher','label':3,'company_id':'c',
           'pair_id':'p1','notice_text':'네트워크 구축 사업','query_text':'네트워크 사업'},
          {'split':'test','label_source':'gpt_teacher','label':0,'company_id':'c',
           'pair_id':'p2','notice_text':'조경 공사','query_text':'네트워크 사업'}]
    result=evaluate_title_only(test,MockModel())
    assert result['company_count']==1
    assert result['full_task_accuracy']=='NOT_RUN'
    assert result['real_company_generalization']=='NOT_VALIDATED'
    assert 0<=result['e5_ndcg10']<=1

def test_pseudo_teacher_rejected():
    with pytest.raises(ValueError,match='no pseudo'):
        evaluate_title_only([{'split':'test','label_source':'pseudo','label':3}],MockModel())
