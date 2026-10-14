from app.ml_recommendations.task_excerpt_risk_audit import audit, risk_flags


def item(texts, *, name="TASK_REQUIREMENTS", version="v1"):
    return {
        "notice_version_id": version,
        "source_status": "TASK_CANDIDATE_UNVERIFIED",
        "selected_document": {
            "name": name, "document_id": "d1",
            "excerpt_sha256": "a"*64,
            "excerpts": [{"text": t} for t in texts],
        },
    }


def test_contract_dominance_never_auto_rejects():
    row = item([
        "계약상대자는 계약조건과 관련 법령을 준수하며 계약상대자 책임으로 처리한다.",
        "입찰참가자격을 확인하고 계약보증금 및 평가위원 안내를 따른다.",
    ])
    assert "CONTRACT_LANGUAGE_DOMINANT" in risk_flags(row)
    result = audit([row], private_corpus_sha256="x")
    assert result["automatically_rejected"] == 0
    assert result["human_review_count"] == 0


def test_task_scope_keeps_no_contract_flag():
    row = item(["사업 내용: 10Gbps 네트워크 시스템을 구축하고 API 연계 기능을 개발한다."])
    assert "CONTRACT_LANGUAGE_DOMINANT" not in risk_flags(row)


def test_no_source_title_fallback_not_flagged():
    row = {"notice_version_id": "v1", "source_status": "TITLE_FALLBACK",
           "selected_document": None}
    result = audit([row], private_corpus_sha256="digest")
    assert result["counts"]["TITLE_ONLY_OR_OTHER"] == 1
    assert not result["items"]


def test_duplicate_version_rejected():
    row = item(["사업 내용: 1TB 저장소 시스템 구축"])
    try:
        audit([row, row], private_corpus_sha256="digest")
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("Duplicate version accepted")
