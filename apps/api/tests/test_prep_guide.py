"""입찰 준비 지침서의 조립 규칙. DB·모델을 쓰지 않는다."""
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.api.app.services import prep_guide

NOTICE = SimpleNamespace(bid_notice_no="R26BK00000001", title="학사정보 통합 고도화", demanding_institution_name="시험대학교")
VERSION = SimpleNamespace(
    bid_started_at=datetime(2026, 11, 1, 1, tzinfo=timezone.utc), bid_closed_at=datetime(2026, 11, 10, 1, tzinfo=timezone.utc), opened_at=None,
)
FACTS = [{"id": "C1", "kind": "실적", "text": "민원 포털 유지관리, 계약금액 120,000,000원"}, {"id": "C2", "kind": "인증", "text": "ISO 27001"}]
RFP = (
    "제1장 사업 개요. 사업목적은 학사정보 시스템의 사용자 환경을 개선하는 것이다.\n"
    "제5장 제안서 평가. 평가항목 및 배점은 다음과 같다. 전략 및 방법론 20점, 수행계획 15점, 입찰가격 평가 10점.\n"
    "제6장 제출서류. 제안서 원본 8부와 USB 1개를 방문 제출한다. 신용평가등급확인서를 첨부한다.\n"
    "질의 마감은 2026. 11. 3.(화) 18:00 까지이다.\n"
)


def caller(extracted: dict, drafted: dict):
    calls = []

    def call(system: str, user: str) -> dict:
        calls.append((system, user))
        return extracted if system == prep_guide.EXTRACT_SYSTEM else drafted

    call.calls = calls
    return call


EXTRACTED = {
    "evaluation_items": [
        {"name": "수행계획", "points": 15, "kind": "기술", "quote": "수행계획 15점"},
        {"name": "입찰가격 평가", "points": 10, "kind": "가격", "quote": "입찰가격 평가 10점"},
        {"name": "전략 및 방법론", "points": 20, "kind": "기술", "quote": "전략 및 방법론 20점"},
        {"name": "지어낸 항목", "points": 30, "kind": "기술", "quote": "문서에 없는 문장입니다 30점"},
    ],
    "submission_documents": [{"text": "신용평가등급확인서", "quote": "신용평가등급확인서를 첨부한다"}],
    "format_rules": [{"text": "제안서 원본 8부와 USB 1개를 방문 제출", "quote": "제안서 원본 8부와 USB 1개를 방문 제출한다"}],
    "dated_events": [{"label": "질의 마감", "when": "2026. 11. 3.(화) 18:00", "quote": "질의 마감은 2026. 11. 3.(화) 18:00"}],
}
DRAFTED = {
    "evaluation_guides": [
        {"name": "전략 및 방법론", "focus": "사업 이해를 보여 준다.", "materials": [
            {"text": "유사 사업 수행 실적 증명", "company_facts": ["C1", "C9"]}, {"text": "방법론 설명 자료", "company_facts": []}]},
        {"name": "수행 계획", "focus": "일정의 적정성.", "materials": [{"text": "단계별 일정표", "company_facts": "C1"}]},
    ],
    "steps": [{"title": "신용평가서 발급 신청", "detail": "발급에 며칠 걸린다.", "lead_time": "오래 걸림"}, {"title": "제안서 인쇄", "detail": "8부.", "lead_time": "이상한 값"}],
}


def build(extracted=EXTRACTED, drafted=DRAFTED, docs=(("제안요청서.hwp", RFP),), facts=FACTS):
    call = caller(extracted, drafted)
    return prep_guide.build_guide(notice=NOTICE, version=VERSION, docs=list(docs), facts=facts, call=call), call


def test_only_items_whose_quote_is_in_the_document_survive():
    guide, _ = build()
    assert [item["name"] for item in guide["evaluation_items"]] == ["전략 및 방법론", "수행계획", "입찰가격 평가"]  # 배점 큰 순, 가격은 뒤
    assert guide["total_points"] == 45
    assert guide["submission_documents"][0]["text"] == "신용평가등급확인서"
    assert guide["warnings"] == []


def test_materials_only_point_at_profile_facts_that_exist():
    guide, _ = build()
    strategy, plan, price = guide["evaluation_items"]
    assert strategy["materials"][0] == {"text": "유사 사업 수행 실적 증명", "company_facts": ["C1"]}  # 없는 C9 는 버린다
    assert strategy["materials"][1]["company_facts"] == []
    assert plan["focus"] == "일정의 적정성." and plan["materials"][0]["company_facts"] == []  # 이름의 띄어쓰기가 달라도 붙고, 목록이 아닌 값은 버린다
    assert price["materials"] == []


def test_schedule_joins_notice_dates_and_dates_written_in_the_document():
    guide, _ = build()
    assert [(row["label"], row["source"]) for row in guide["schedule"]] == [("입찰 시작", "공고 일정"), ("입찰 마감", "공고 일정"), ("질의 마감", "공고 문서")]
    assert guide["schedule"][2]["when"] == "2026. 11. 3.(화) 18:00" and guide["schedule"][2]["at"] is None


def test_steps_keep_a_known_lead_time():
    guide, _ = build()
    assert [step["lead_time"] for step in guide["steps"]] == ["오래 걸림", "보통"]


def test_the_model_never_sees_the_profile_before_extraction_and_gets_facts_after():
    _, call = build()
    assert len(call.calls) == 2
    assert "ISO 27001" not in call.calls[0][1]
    assert "ISO 27001" in call.calls[1][1] and "지어낸 항목" not in call.calls[1][1]


def test_no_evaluation_items_is_said_plainly_and_still_guides_submission():
    guide, call = build(extracted={**EXTRACTED, "evaluation_items": []})
    assert guide["evaluation_items"] == [] and guide["total_points"] is None
    assert "평가 항목과 배점을 찾지 못했습니다" in guide["warnings"][0]
    assert len(call.calls) == 2 and guide["steps"]


def test_no_readable_document_makes_no_model_call():
    guide, call = build(docs=(("빈 문서.hwp", "   "),))
    assert call.calls == []
    assert [row["label"] for row in guide["schedule"]] == ["입찰 시작", "입찰 마감"]
    assert "첨부 문서가 없어" in guide["warnings"][0]


def test_scoring_table_is_picked_even_when_requirements_dominate_a_long_document():
    # 요구사항이 수백 번 나오는 긴 제안요청서에서도 배점표가 발췌에 들어가야 한다.
    filler = "\n".join(f"요구사항 SFR-{index:03d} 요구사항 상세 설명. 요구사항 분류와 요구사항 고유번호." + "가" * 300 for index in range(300))
    scoring = "제안서 평가항목 및 배점한도: 사업 이해도 10점, 추진전략 15점, 기술 및 기능 30점."
    passages = prep_guide.pick_passages([("제안요청서.hwpx", filler[:60000] + "\n" + scoring + "\n" + filler[60000:])])
    assert "추진전략 15점" in passages
    assert len(passages) < 40000


def test_duplicate_attachments_are_read_once():
    docs = prep_guide.distinct_documents([("2.제안요청서.hwp", "짧은 본문"), ("1.공고문.pdf", "공고"), ("2.제안요청서.pdf", "더 긴 본문입니다")])
    assert docs == [("2.제안요청서.pdf", "더 긴 본문입니다"), ("1.공고문.pdf", "공고")]


def test_company_facts_come_only_from_the_profile():
    company = SimpleNamespace(
        region_name="서울특별시", company_size="SMALL", staff=SimpleNamespace(total_count=8),
        industries=[SimpleNamespace(industry_code="0036", industry=SimpleNamespace(name="정보통신공사업"))],
        performances=[SimpleNamespace(name="민원 포털 유지관리", client_name="A시청", amount=120000000, completed_at=None, completed_year=2025)],
        certifications=[SimpleNamespace(name="ISO 27001", issuer_name=None, expires_at=None)],
        staff_roles=[SimpleNamespace(role_name="개발자", headcount=5, career_years=None)],
    )
    facts = prep_guide.company_facts(company)
    assert [fact["id"] for fact in facts] == ["C1", "C2", "C3", "C4", "C5"]
    assert facts[0]["text"] == "소재지 서울특별시, 소기업, 상시 근로자 8명"
    assert facts[2]["text"] == "민원 포털 유지관리, 발주처 A시청, 계약금액 120,000,000원, 2025년 완료"
