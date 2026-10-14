"""Regression guard for J22 scoring-table/mandatory-qualification confusion."""

from bidengine.contracts import Evidence, EvidenceLocation, QualificationRequirement
from bidengine.pipeline.evaluation_role_guard import guard_scoring_only_performance


def _requirement(key: str, type_: str, quote: str, citations: list[str]):
    return QualificationRequirement(
        requirement_key=key,
        notice_version_id="notice-version",
        type=type_,
        operator=">=" if type_ == "PERFORMANCE_AMOUNT" else "MATCH",
        value=50000000 if type_ == "PERFORMANCE_AMOUNT" else quote,
        raw=quote,
        evidence_keys=citations,
    )


def _evidence(key: str, chunk: str):
    return Evidence(
        evidence_key=key, source_type="NOTICE_DOCUMENT", document_id="proposal-hwpx",
        chunk_id=chunk, location=EvidenceLocation(), quote="5천만원 이상 실적",
    )


def test_j22_scoring_table_performance_is_informational_only():
    chunks = [
        {"chunk_id": "CHUNK-0421", "text": "1) 정량평가(20점)\n사업수행 / 실 적 / (6) | 100% 이상 | 최근 3년 이내 학생 해외어학연수 등 사업이행 5천만원 이상 실적"},
        {"chunk_id": "CHUNK-0439", "text": "2) 평가항목별 점수기준(정성평가 70점)\n- 사업실적 / 최근 3년간 실적(단일규모 5천만원 이상) | 6점"},
    ]
    q = [
        _requirement("q1", "PERFORMANCE_AMOUNT", "최근 3년 이내 학생 해외어학연수 등 사업이행 5천만원 이상 실적", ["e1"]),
        _requirement("q2", "EXPERIENCE_FIELD", "최근 3년간 실적(단일규모 5천만원 이상)", ["e2"]),
    ]
    output, diagnostics = guard_scoring_only_performance(
        q, [_evidence("e1", "CHUNK-0421"), _evidence("e2", "CHUNK-0439")], chunks,
    )
    assert all(row.requirement_role == "informational" and not row.required for row in output)
    assert all(row.scope["non_eligibility_reason"] == "EVALUATION_SCORE_TABLE" for row in output)
    assert len(diagnostics) == 2
    assert all(row["reason"] == "EVALUATION_SCORE_TABLE" for row in diagnostics)


def test_real_eligibility_performance_is_not_downgraded():
    q = _requirement("q1", "PERFORMANCE_AMOUNT", "최근 3년 이내 실적 5천만원 이상을 충족한 자", ["e1"])
    chunks = [{"chunk_id": "eligibility", "text": "3. 입찰 참가자격\n최근 3년 이내 실적 5천만원 이상을 충족한 자"}]
    result, diagnostics = guard_scoring_only_performance([q], [_evidence("e1", "eligibility")], chunks)
    assert result == [q]
    assert diagnostics == []


def test_mixed_and_missing_evidence_never_trigger_a_downgrade():
    q = _requirement("q1", "PERFORMANCE_AMOUNT", "5천만원 실적", ["score", "eligibility"])
    chunks = [
        {"chunk_id": "score", "text": "1) 정량평가(20점)\n사업수행 실적(6점)"},
        {"chunk_id": "eligibility", "text": "3. 입찰 참가자격\n5천만원 실적"},
    ]
    all_refs = [_evidence("score", "score"), _evidence("eligibility", "eligibility")]
    for refs in (all_refs, all_refs[:1], []):
        result, diagnostics = guard_scoring_only_performance([q], refs, chunks)
        assert result == [q]
        assert diagnostics == []


def test_non_performance_requirement_in_score_table_remains_unmodified():
    q = _requirement("q1", "INDUSTRY", "업종 1262", ["e1"])
    result, diagnostics = guard_scoring_only_performance(
        [q], [_evidence("e1", "score")],
        [{"chunk_id": "score", "text": "1) 정량평가(20점)\n업종 관련 평가"}],
    )
    assert result == [q]
    assert diagnostics == []


def test_shared_chunk_containing_eligibility_heading_is_not_auto_downgraded():
    q = _requirement("q1", "PERFORMANCE_AMOUNT", "5천만원 실적", ["score"])
    chunks = [{
        "chunk_id": "score",
        "text": "1) 정량평가(20점)\n사업수행 실적 6점\n3. 입찰 참가자격\n실적 5천만원 필수",
    }]
    output, diagnostics = guard_scoring_only_performance([q], [_evidence("score", "score")], chunks)
    assert output == [q]
    assert diagnostics == []
