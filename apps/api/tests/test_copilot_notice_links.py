"""일반 도우미가 공고를 찾아 판정 화면으로 이어 주는 요청을 알아본다(2026-10-13)."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.copilot.notice_links import search_terms, wants_recommended
from apps.api.app.database import SessionLocal
from apps.api.app.main import app
from apps.api.app.models import BidNotice
from apps.api.app.schemas import BusinessType
from apps.api.app.services.notices import save_notice_snapshot

client = TestClient(app)


@pytest.mark.parametrize(("message", "terms"), [
    ("보안관제 공고 찾아줘", "보안관제"),
    ("구미 교복 관련 공고 좀 검색해 주세요.", "구미 교복"),
    ("정보시스템 유지관리 입찰 공고 있어?", "정보시스템 유지관리"),
    ("R26BK01763425 공고 찾아줘", "R26BK01763425"),
    ("r26bk01763425 보여줘", "R26BK01763425"),
    ("소프트웨어 개발 공고를 찾아서 판정 화면까지 보여줘", "소프트웨어 개발"),
])
def test_search_requests_yield_the_words_to_look_for(message: str, terms: str) -> None:
    assert search_terms(message) == terms


@pytest.mark.parametrize("message", [
    "공고 찾아줘",                          # 찾을 낱말이 없다
    "확인 필요는 무슨 뜻이야?",
    "공고가 바뀌면 어떻게 돼?",              # 찾아 달라는 말이 아니다
    "회사 프로필은 어디서 고쳐?",
])
def test_other_questions_are_left_to_the_model(message: str) -> None:
    assert search_terms(message) is None and not wants_recommended(message)


@pytest.mark.parametrize("message", [
    "AI 추천으로 뜬 공고 판정해줘", "ai추천 공고들 검토해 줘", "추천된 공고 자격 확인해줘", "AI 추천에 뜬 공고 보여줘",
])
def test_recommended_notice_requests_are_recognised(message: str) -> None:
    assert wants_recommended(message)


def test_general_helper_returns_notice_links_without_calling_the_model(monkeypatch) -> None:
    from apps.api.app.copilot import router as copilot_router

    def no_model(*_args, **_kwargs):
        raise AssertionError("공고 찾기 요청은 모델을 부르지 않는다")
    monkeypatch.setattr(copilot_router, "general_chat_response", no_model)
    db = SessionLocal()
    word = f"링크확인{uuid4().hex[:6]}"
    notice_no = f"R26LK{uuid4().hex[:8].upper()}"
    notice_id = None
    try:
        _, notice, _ = save_notice_snapshot(db, item={
            "bidNtceNo": notice_no, "bidNtceOrd": "000", "bidNtceNm": f"{word} 통합 유지관리 용역",
            "ntceInsttNm": "테스트 기관", "dminsttNm": "테스트 기관", "bidNtceDt": "2026-09-01 10:00:00",
            "bidClseDt": "2026-09-10 10:00:00", "ntceKindNm": "등록공고",
        }, business_type=BusinessType.SERVICE, source_endpoint="getBidPblancListInfoServc")
        db.commit()
        notice_id = notice.id
        response = client.post("/api/v1/copilot/general-chat", json={"message": f"{word} 공고 찾아줘"},
                               headers={"X-Copilot-Semantic-Processing": "true"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert [(item["notice_id"], item["bid_notice_no"], item["action"]) for item in body["notice_links"]] == [(str(notice_id), notice_no, "OPEN")]
        assert body["notice_links"][0]["expired"] is True and word in body["answer"]

        nothing = client.post("/api/v1/copilot/general-chat", json={"message": f"없는낱말{uuid4().hex[:8]} 공고 찾아줘"})
        assert nothing.status_code == 200 and nothing.json()["notice_links"] == [] and "찾지 못했습니다" in nothing.json()["answer"]
    finally:
        if notice_id is not None:
            found = db.get(BidNotice, notice_id)
            if found is not None:
                db.delete(found)
                db.commit()
        db.close()
