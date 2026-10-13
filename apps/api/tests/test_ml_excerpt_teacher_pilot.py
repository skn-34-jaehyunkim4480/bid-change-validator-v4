"""Tests for explicitly *unapproved* GPT-6 excerpt pilot; no model download."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import json

import numpy as np
import pytest
from app.ml_recommendations.excerpt_teacher_pilot import (
    check_private_annotation,compare_pilot,_ndcg,
)

V='f'*8+'-ffff-4fff-8fff-'+'f'*12
N='a'*8+'-aaaa-4aaa-8aaa-'+'a'*12
D='b'*8+'-bbbb-4bbb-8bbb-'+'b'*12

def setup_fake_files(tmp_path):
    source=tmp_path/'source';p=source/'source_blocks'
    p.mkdir(parents=True)
    blocks=[{'block_index':1,'text':'시장 홈페이지 제작 및 관리자 기능 구축'}]
    raw=json.dumps(blocks,ensure_ascii=False).encode('utf-8')
    (p/(D+'.blocks.json')).write_bytes(raw)
    review=tmp_path/'pilot';review.mkdir()
    excerpt=blocks[0]['text']
    task={'notice_id':N,'notice_version_id':V,'title':'시장 홈페이지 구축',
          'teacher_review_status':'REVIEWED_EXCERPT','evidence_type':'DIRECT',
          'source_blocks_file':'source_blocks/'+D+'.blocks.json',
          'cached_source_sha256':hashlib.sha256(raw).hexdigest(),'evidence_blocks':[1],
          'excerpt_text':excerpt,'excerpt_sha256':hashlib.sha256(excerpt.encode()).hexdigest()}
    label={'company_id':'c1','company_name':'합성 IT','notice_id':N,'notice_version_id':V,
           'grade':2,'label_source':'gpt_teacher','human_approved':False,
           'annotation_basis':'REVIEWED_SOURCE_EXCERPT',
           'evidence_sha256':task['excerpt_sha256'],
           'rationale':'웹사이트 구축이라는 기업 역량이 과업에 부합하지만 홍보 영상제작 등 부차 기능은 확인되지 않습니다.'}
    for name,obj in [('task_review.jsonl',task),('teacher_judgments.jsonl',label)]:
        (review/name).write_text(json.dumps(obj,ensure_ascii=False)+'\n',encoding='utf-8')
    manifests={'judged_pair_count':1,'human_approved':False,'full_task_golden_approved':False,
       'file_sha256':{name:hashlib.sha256((review/name).read_bytes()).hexdigest()
           for name in ('task_review.jsonl','teacher_judgments.jsonl')}}
    (review/'manifest.json').write_text(json.dumps(manifests),encoding='utf-8')
    return review,source

class FakeEncoder:
    def encode(self, texts, **kwargs):
        vectors=np.zeros((len(texts),3),dtype=np.float32)
        for i,s in enumerate(texts):
            vectors[i,:]=[float('웹' in s),float('관리자' in s),float('시장' in s)]
        return vectors

def test_private_annotation_provenance(tmp_path):
    p,source=setup_fake_files(tmp_path)
    task,labels,checks=check_private_annotation(p,originals=source)
    assert checks['checked_excerpts']==1
    assert labels[0]['human_approved'] is False
    assert task[V]['evidence_type']=='DIRECT'

def test_original_excerpt_tamper_rejected(tmp_path):
    p,source=setup_fake_files(tmp_path)
    file=source/'source_blocks'/(D+'.blocks.json')
    file.write_text(file.read_text(encoding='utf-8').replace('시장','교육'),encoding='utf-8')
    with pytest.raises(ValueError,match='snapshot mismatch'):
        check_private_annotation(p,originals=source)

def test_fake_human_approval_rejected(tmp_path):
    p,source=setup_fake_files(tmp_path)
    manifest=json.loads((p/'manifest.json').read_text())
    manifest['human_approved']=True
    (p/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='approval'):
        check_private_annotation(p,originals=source)

def test_unapproved_pilot_never_looks_like_real_benchmark(tmp_path):
    p,source=setup_fake_files(tmp_path)
    task,labels,_=check_private_annotation(p,originals=source)
    profiles={'companies':[{'company_id':'c1','name':'합성 IT',
               'industries':[{'name':'웹페이지 소프트웨어 개발'}],
               'performances':['관리자 페이지 구축'],'certifications':[],'staff_roles':[]}]}
    result=compare_pilot(task,labels,FakeEncoder(),profiles)
    assert result['judgment_count']==1
    assert result['full_task_benchmark']=='NOT_RUN'
    assert result['full_corpus_recall']=='NOT_RUN'
    assert result['human_approved'] is False
    assert result['nDCG10_mean_across_firms_with_positive']['bm25']==1.0

def test_ndcg_undefined_without_any_relevance():
    assert _ndcg(['b'],{'b':0}) is None
