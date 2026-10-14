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


def test_real_extracted_tender_score_variants():
    # Frozen real G2B extraction blocks; these are NOT generated example texts.
    # Each contains an explicit scored evaluation table with performance wording.
    import json
    import re
    from pathlib import Path
    from bidengine.document.chunking import chunk_source_blocks

    golden_root = Path(__file__).resolve().parents[2] / "eval" / "golden"
    cases = [
        ("R26BK01739452", r"정량적\s*평가\s*\(20점\)"),
        ("R26BK01736838", r"사업수행실적\s*평가기준\s*\(10점\)"),
        ("R26BK01723179", r"주요사업\s*수행\s*실적"),
        ("R26BK01741346", r"적격업체\s*선정\s*평가표"),
        ("R26BK01675774", r"제안서\s*평가기준"),
        ("R26BK01688607", r"평가항목\s*및\s*배점"),
    ]
    for number, heading in cases:
        matched = []
        for file in golden_root.rglob(f"*{number}*"):
            if not file.is_dir():
                continue
            for blocks_file in file.glob("*.blocks.json"):
                blocks = json.loads(blocks_file.read_text(encoding="utf-8-sig"))
                for chunk in chunk_source_blocks(blocks, max_chars=1800):
                    content = chunk["text"]
                    match = re.search(heading, content)
                    if (
                        match
                        and match.start() < 350
                        and "실적" in content.replace(" ", "")
                        and ("점" in content or "배점" in content)
                        and "입찰참가자격" not in content.replace(" ", "")
                    ):
                        matched.append(content)
        assert matched, f"No real source for {number}: {heading}"
        assert any(
            guard_scoring_only_performance(
                [_requirement("q", "PERFORMANCE_AMOUNT", "실적", ["ev"])],
                [_evidence("ev", "real")],
                [{"chunk_id": "real", "text": content}],
            )[0][0].requirement_role == "informational" for content in matched
        ), f"Scored performance falsely remains mandatory: {number}"



def test_real_extracted_overlap_does_not_downgrade_eligibility():
    # Real school-uniform document: one large extracted page contains both a
    # scoring table and a bidder-eligibility heading later in the same chunk.
    import json
    from pathlib import Path
    from bidengine.document.chunking import chunk_source_blocks

    root = Path(__file__).resolve().parents[2] / "eval" / "golden"
    file = next(root.rglob("609509c84e6cd4f2.blocks.json"))
    chunks = chunk_source_blocks(json.loads(file.read_text(encoding="utf-8-sig")), max_chars=1800)
    score_chunks = [
        c for c in chunks
        if c["text"].startswith("- 22 -")
        and "선정평가표" in c["text"].replace(" ", "")
        and "입찰참가자격" in c["text"].replace(" ", "")
    ]
    assert score_chunks
    q = _requirement("q", "PERFORMANCE_AMOUNT", "납품실적", ["ev"])
    result, diagnostics = guard_scoring_only_performance(
        [q], [_evidence("ev", "source")],
        [{"chunk_id": "source", "text": score_chunks[0]["text"]}],
    )
    assert result == [q] and diagnostics == []


def test_mentioning_score_table_inside_requirement_paragraph_is_not_a_heading():
    from bidengine.pipeline.evaluation_role_guard import _is_scoring_only_chunk
    statement = (
        "라. 납품실적이 있는 업체만 참가할 수 있습니다. "
        "학교주관구매 교복 적격업체 선정 평가표에 실적 배점이 있습니다."
    )
    assert not _is_scoring_only_chunk(statement)
