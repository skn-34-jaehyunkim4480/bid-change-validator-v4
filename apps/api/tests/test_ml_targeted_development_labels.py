"""Strict review gates for targeted, model-authored development data."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from app.ml_recommendations.targeted_development_labels import (
    build_reviewed_map,check_targeted_pairs,make_pairs,
)

def samples():
    profiles={"companies":[{"company_id":"f1","name":"테스트","industries":[{"name":"의료기기 판매"}]}]}
    queue=[{"notice_id":"n1","notice_version_id":"v1","title":"의료기기 구매"}]
    old=[{"teacher_review_status":"REVIEWED_EXCERPT","evidence_type":"DIRECT",
          "notice_version_id":"v1","evidence_blocks":[3],
          "excerpt_text":"분석기 공급","excerpt_sha256":"SHA_PLACEHOLDER"}]
    import hashlib
    old[0]["excerpt_sha256"]=hashlib.sha256(old[0]["excerpt_text"].encode()).hexdigest()
    seed=[{"company_index":1,"source_index":0,"grade":2,
           "rationale":"의료기기 판매 분야가 분석기 납품과 관련되지만 특정 제품의 공급권한은 확인하지 못했습니다."}]
    return profiles,queue,old,seed

def test_model_judgments_must_be_dev_only():
    p,q,old,seed=samples()
    pairs,summary=make_pairs(p,q,old,[],[],seed)
    assert summary["new_pairs"]==1 and summary["positive_2plus"]==1
    assert summary["ready_for_independent_evaluation"] is False
    assert pairs[0]["human_approved"] is False
    assert pairs[0]["split"]=="targeted_development"

def test_old_pair_cannot_be_reused():
    p,q,old,seed=samples()
    original=[{"company_id":"f1","notice_version_id":"v1"}]
    with pytest.raises(ValueError,match="Previously labeled"):
        make_pairs(p,q,old,[],original,seed)

def test_unverified_excerpt_disallowed():
    p,q,old,seed=samples()
    old[0]["evidence_type"]="INDIRECT"
    with pytest.raises(KeyError):
        make_pairs(p,q,old,[],[],seed)

def test_excerpt_sha_integrity():
    p,q,old,seed=samples()
    old[0]["excerpt_text"]="임의 수정"
    with pytest.raises(ValueError,match="SHA"):
        make_pairs(p,q,old,[],[],seed)

def test_cannot_claim_human_approval_or_final_split():
    p,q,old,seed=samples()
    pairs,_=make_pairs(p,q,old,[],[],seed)
    verified=build_reviewed_map(old,[],q)
    pairs[0]["human_approved"]=True
    with pytest.raises(ValueError,match="Not model-authored"):
        check_targeted_pairs(pairs,p,q,verified,[])
    pairs[0]["human_approved"]=False
    pairs[0]["split"]="test"
    with pytest.raises(ValueError,match="holdout"):
        check_targeted_pairs(pairs,p,q,verified,[])
