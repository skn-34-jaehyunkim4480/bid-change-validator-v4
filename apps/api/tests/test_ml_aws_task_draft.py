from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Bounded AWS draft export: strict no auto-approved tasks or training labels."""
import json
import pytest
from app.ml_recommendations.aws_task_draft import export, aws_fetch


def sample():
    companies=[{'company_id':'test'}]
    notices=[]
    for kind in ('CONSTRUCTION','GOODS','SERVICE','FOREIGN'):
        for i in range(4):
            notices.append({'notice_id':f'{kind}-{i}', 'notice_version_id':f'v-{kind}-{i}',
                            'bid_notice_no':f'R26BK{i}', 'business_type':kind,
                            'posted_at':f'2026-10-{10+i:02}T10:00:00Z',
                            'title':f'사업 {kind} {i}'})
    return {'companies':companies,'notices':notices}


def test_draft_stays_unverified(tmp_path, monkeypatch):
    calls=[]
    def fake_fetch(ssm, iid, ids, *, container):
        calls.extend(ids)
        return [{'version_id':x,'name':'과업지시서.hwp','candidate_windows':[
                 {'start_index':0,'blocks':[{'block_index':0,'text':'사업범위: 실제 자료'}]}]} for x in ids]
    monkeypatch.setattr('app.ml_recommendations.aws_task_draft.aws_fetch',fake_fetch)
    result=export(sample(),object(),tmp_path, max_notices=8,batch_size=3)
    assert result['selected']==8
    assert result['candidate_status']=={'UNVERIFIED_CANDIDATE':8}
    assert len(calls)==8
    rows=json.loads((tmp_path/'draft.json').read_text(encoding='utf-8'))
    assert all(x['status']=='UNVERIFIED_CANDIDATE' for x in rows)
    assert 'grade' not in json.dumps(rows)
    assert not any(x['document'].get('body_status')=='VERIFIED_TASK' for x in rows)


def test_export_bounds(tmp_path):
    with pytest.raises(ValueError,match='bounded'):
        export(sample(),object(),tmp_path,max_notices=201)
    with pytest.raises(ValueError,match='bounded'):
        export(sample(),object(),tmp_path,max_notices=20,batch_size=26)


def test_fetch_rejects_unbounded_sql():
    with pytest.raises(ValueError, match='1..25'):
        aws_fetch(object(),'i-deadbeef',[],container='c')
    with pytest.raises(ValueError, match='1..25'):
        aws_fetch(object(),'i-deadbeef',[str(i) for i in range(26)],container='c')
