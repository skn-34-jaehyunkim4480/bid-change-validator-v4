"""PR C offline contract tests: fabricated fixtures, never real ranking scores."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import pytest
from app.ml_recommendations.task_review_queue import materialize_review_queue,checked_family_hints
from app.ml_recommendations.source_audit import verify_frozen_review_queue
from app.ml_recommendations.validated_eval import compare_independent_runs,_rrf

A='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
B='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
C='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
V1='11111111-1111-4111-8111-111111111111'
V2='22222222-2222-4222-8222-222222222222'
DOC='dddddddd-dddd-4ddd-8ddd-dddddddddddd'

def fixture():
    snap={'companies':[{'company_id':'synthetic-1','industries':[{'code':'1','name':'소프트웨어 개발'}],
           'performances':[],'staff_roles':[]}],
          'notices':[{'notice_id':A,'notice_version_id':V1,'bid_notice_no':'N001',
                      'title':'정보시스템 구축','posted_at':'2026-09-01T00:00:00Z','business_type':'SERVICE'},
                     {'notice_id':B,'notice_version_id':V2,'bid_notice_no':'N002',
                      'title':'IT 관리','posted_at':'2026-10-01T00:00:00Z','business_type':'SERVICE'}]}
    doc={'doc_id':DOC,'version_id':V1,'name':'과업지시서.pdf',
         'file_sha256':'a'*64,'extracted_text_sha256':'b'*64,
         'candidate_windows':[{'start_index':12,'score':9,'blocks':[{'block_index':12,
              'text':'사업 목적은 공공 정보시스템 신규 구축과 장기 유지보수를 위한 것입니다.'}]}]}
    drafts=[{**snap['notices'][0], 'document':doc},
            {**snap['notices'][1], 'document':None}]
    return snap,drafts

def test_source_queue_never_auto_approves_or_labels(tmp_path):
    snap,draft=fixture()
    r=materialize_review_queue(snap,draft,[],{'1':'소프트웨어 개발'},tmp_path/'output')
    assert r['input_versions']==2
    assert r['source_candidate_versions']==1
    assert r['accuracy_status']=='NOT_EVALUATED'
    assert r['audit']['status']=='NOT_READY'
    corpus=json.loads((tmp_path/'output'/'corpus_unverified.json').read_text(encoding='utf-8'))
    assert all(n['body_status']=='UNVERIFIED' and not n['task_text'] and not n['task_evidence']
               for n in corpus['notices'])
    review=json.loads((tmp_path/'output'/'task_review_queue.jsonl').read_text(encoding='utf-8').splitlines()[0])
    assert 'grade' not in review
    assert 'file_sha256' not in snap['notices'][0]
    assert verify_frozen_review_queue(tmp_path/'output')['candidate_count']==1

def test_tampering_selected_block_is_detected(tmp_path):
    snap,draft=fixture()
    out=tmp_path/'draft'
    materialize_review_queue(snap,draft,[],{},out)
    source=out/'source_blocks'/(DOC+'.blocks.json')
    source.write_text(source.read_text(encoding='utf-8').replace('정보시스템','계약조건'),encoding='utf-8')
    with pytest.raises(ValueError,match='SHA mismatch'):
        verify_frozen_review_queue(out)

def test_mismatched_version_is_rejected(tmp_path):
    snap,draft=fixture()
    draft[0]['document']['version_id']=V2
    with pytest.raises(ValueError,match='another notice'):
        materialize_review_queue(snap,draft,[],{},tmp_path/'bad')

def test_duplicate_version_is_rejected(tmp_path):
    snap,draft=fixture()
    with pytest.raises(ValueError,match='Duplicate'):
        materialize_review_queue(snap,draft+[draft[0]],[],{},tmp_path/'duplicate')

def test_outside_confirmed_relation_blocks_family_closure():
    snap,draft=fixture()
    families,info=checked_family_hints(draft,[{'notice_id':A,'previous_notice_id':C,
          'match_confidence':'CONFIRMED','match_method':'API_FIELD'}])
    assert info['status']=='UNVERIFIED_CLOSURE'
    assert info['external_relation_notice_count']==1
    assert families[A] in info['blocked_family_ids']

def test_only_confirmed_edges_union():
    snap,draft=fixture()
    x=[{'notice_id':A,'previous_notice_id':B,'match_confidence':'SUGGESTED'},
       {'notice_id':B,'previous_notice_id':C,'match_confidence':'CONFIRMED'}]
    fam,info=checked_family_hints(draft,x)
    assert fam[A]!=fam[B]
    assert info['uncertain_relation_notice_count']==2
    assert info['external_relation_notice_count']==1

def test_unapproved_input_blocks_ranking(tmp_path):
    corpus={'schema_version':'bad'}
    with pytest.raises(Exception):
        compare_independent_runs(corpus,{'reviews':[]},{'runs':[]},source_root=tmp_path)

def test_rrf_order_is_deterministic_and_unlabeled_is_not_negative():
    assert _rrf([['a','b'],['b','c']])==['b','a','c']
    assert _rrf([['b','a'],['c','b']])[0]=='b'
