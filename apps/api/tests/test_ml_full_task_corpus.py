from __future__ import annotations

import pytest

from app.ml_recommendations.full_task_corpus import (
    build_corpus, document_priority, select_scope_blocks,
)


def notice(version="v1"):
    return {"notice_id": "n1", "notice_version_id": version,
            "title": "공공 데이터 플랫폼 구축", "business_type": "SERVICE"}


def document(version="v1", document_id="d1", name="과업지시서"):
    return {"version_id": version, "document_id": document_id,
            "name": name, "file_sha256": "a"*64,
            "extracted_text_sha256": "b"*64, "extracted_char_count": 2000}


def blocks(version="v1", document_id="d1", scope="사업 개요: 데이터 분석 플랫폼을 구축하고 통합 검색 기능을 개발한다."):
    return {"version_id": version, "document_id": document_id,
            "extracted_blocks": [{"block_index": 4, "text": scope}]}


def test_task_named_document_creates_unverified_candidate():
    rows, stats = build_corpus({"notices": [notice()]}, [document()], [blocks()])
    assert stats["statuses"]["TASK_CANDIDATE_UNVERIFIED"] == 1
    assert rows[0]["selected_document"]["document_id"] == "d1"
    assert rows[0]["label_status"] == "NO_INDEPENDENT_TASK_REVIEW"
    assert rows[0]["passages"][0].startswith("passage: ")
    assert "데이터 분석 플랫폼" in rows[0]["search_text"]


def test_title_fallback_without_document():
    rows, stats = build_corpus({"notices": [notice()]}, [], [])
    assert rows[0]["source_status"] == "TITLE_FALLBACK"
    assert rows[0]["search_text"] == notice()["title"]
    assert stats["source_file_hashes"] == "RDS_METADATA_ONLY_UNVERIFIED"


def test_boiler_attachment_deprioritized():
    task = document(document_id="d2")
    boiler = document(document_id="d1", name="계약일반조건 및 입찰유의서")
    rows, _ = build_corpus({"notices": [notice()]},
                           [boiler, task],
                           [blocks(document_id="d1"), blocks(document_id="d2")])
    assert rows[0]["selected_document"]["document_id"] == "d2"
    assert document_priority(boiler)[0] > document_priority(task)[0]


def test_metadata_source_cross_version_rejected():
    with pytest.raises(ValueError, match="unknown excerpt"):
        build_corpus({"notices": [notice()]}, [document()],
                     [blocks(version="v2")])


def test_duplicate_document_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        build_corpus({"notices": [notice()]},
                     [document(), document()], [])


def test_no_false_human_verification_from_selected_text():
    good = select_scope_blocks({**document(), "extracted_blocks": blocks()["extracted_blocks"]})
    assert good["status"] == "TASK_CANDIDATE_UNVERIFIED"
    assert good["excerpt_sha256"] is not None


def test_eligibility_boiler_not_selected_as_scope():
    d = document(name="계약일반조건")
    source = blocks(scope="입찰참가자격 및 계약보증금에 대한 규정은 계약일반조건을 따른다.")
    row, _ = build_corpus({"notices": [notice()]}, [d], [source])
    assert row[0]["source_status"] == "TITLE_FALLBACK"


def test_boiler_name_rejected_even_if_body_mentions_scope():
    d = document(name="\uacc4\uc57d\uc77c\ubc18\uc870\uac74")
    row, _ = build_corpus(
        {"notices": [notice()]}, [d], [blocks()])
    assert row[0]["source_status"] == "TITLE_FALLBACK"
