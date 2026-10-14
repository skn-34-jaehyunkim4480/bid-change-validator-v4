"""입찰 준비 지침서(2026-10-14).

판정이 끝난 공고 하나에 대해 "무엇을 어떤 순서로 준비해야 하는가" 를 정리해 준다. 제안서 글을
대신 쓰지 않는다 — 회사에 관한 사실을 문장으로 지어낼 여지를 두지 않으려는 것이다.

흐름
  1) 공고 문서에서 평가·제출·일정 대목만 골라 낸다(모델 없이).
  2) 모델 호출 1: 평가 항목·배점, 제출 서류, 작성 지침, 문서에 적힌 일정을 원문 인용과 함께 뽑는다.
     인용문이 실제 문서에 없으면 그 항목은 버린다.
  3) 모델 호출 2: 평가 항목마다 준비할 자료를 적고, 회사 프로필 항목(C1, C2 …) 가운데 쓸 수 있는
     것을 고르고, 준비 순서를 정한다. 없는 프로필 항목을 가리키면 그 연결은 버린다.

저장하지 않는다. 같은 공고를 다시 열면 화면이 브라우저에 둔 결과를 보여 준다.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..judgment_models import QualificationJudgmentRun
from ..models import BidNotice, BidNoticeVersion, Company, CompanyIndustry, NoticeDocument, PreflightCase

JsonCaller = Callable[[str, str], dict[str, Any]]

# 평가 항목과 배점이 있는 대목을 먼저 확보한다. 긴 제안요청서는 "요구사항" 이 수백 번 나와,
# 낱말 개수만으로 고르면 배점표가 통째로 빠진다(프로토타입 5건 중 2건이 그랬다).
SCORING_KEYS = ("배점", "평가항목", "평가 항목", "평가기준", "평가 기준", "평가요소")
SUBMISSION_KEYS = ("제출서류", "제출 서류", "구비서류", "제출방법", "제출 방법", "제안서 제출", "제출기한", "제출 기한",
                   "제안서 작성", "제안서작성", "작성요령", "작성 요령", "제안서 목차", "제안설명", "제안서 평가", "질의")
CONTEXT_KEYS = ("사업목적", "사업 목적", "사업개요", "사업 개요", "추진배경", "과업내용", "과업 내용", "사업범위", "요구사항")
TIERS = ((SCORING_KEYS, 14000), (SUBMISSION_KEYS, 12000), (CONTEXT_KEYS, 8000))
WINDOW = 1400
SPAN_LIMIT = 5000
GOLDEN_EXCERPT_PREFIX = "[골든셋 근거 발췌] "

DONE_STATUSES = {
    "core_met": "핵심 요건 충족", "core_unmet": "핵심 요건 미충족", "needs_review": "확인 필요",
    "eligible": "참여 가능", "ineligible": "참여 불가", "insufficient_data": "자료 부족",
}


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def distinct_documents(docs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """같은 문서가 hwp·pdf 두 벌로 붙은 공고가 많다. 이름(확장자 제외)이 같으면 긴 쪽만 남긴다."""
    best: dict[str, tuple[str, str]] = {}
    order: list[str] = []
    for name, body in docs:
        key = re.sub(r"\.(hwpx?|pdf|docx?)$", "", name.strip(), flags=re.IGNORECASE)
        if key not in best:
            order.append(key)
            best[key] = (name, body)
        elif len(body) > len(best[key][1]):
            best[key] = (name, body)
    return [best[key] for key in order]


def _spans(body: str, keys: tuple[str, ...]) -> list[tuple[int, int, int]]:
    marks = sorted({m.start() for key in keys for m in re.finditer(re.escape(key), body)})
    merged: list[list[int]] = []
    for pos in marks:
        start, end = max(0, pos - 300), min(len(body), pos + WINDOW)
        if merged and start <= merged[-1][1] and end - merged[-1][0] <= SPAN_LIMIT:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(sum(body[start:end].count(key) for key in keys), start, end) for start, end in merged]


def pick_passages(docs: list[tuple[str, str]]) -> str:
    """평가 → 제출·작성 → 사업 개요 순으로 대목을 고른다. 갈래마다 몫이 따로 있어 한 갈래가 다른 갈래를 밀어내지 못한다."""
    chosen: list[tuple[int, int, int]] = []

    def overlaps(index: int, start: int, end: int) -> bool:
        return any(i == index and start < e and s < end for i, s, e in chosen)

    for keys, budget in TIERS:
        candidates = sorted(
            ((score, index, start, end) for index, (_name, body) in enumerate(docs) for score, start, end in _spans(body, keys)),
            key=lambda row: (-row[0], row[1], row[2]),
        )
        used = 0
        for _score, index, start, end in candidates:
            if used + (end - start) > budget or overlaps(index, start, end):
                continue
            chosen.append((index, start, end))
            used += end - start
    return "\n\n".join(f"<<문서: {docs[index][0]}>>\n{docs[index][1][start:end]}" for index, start, end in sorted(chosen))


EXTRACT_SYSTEM = """너는 공공 입찰 공고문과 제안요청서를 읽어, 입찰을 준비하는 회사에 필요한 뼈대를 뽑는다.
주어진 발췌문에 적힌 것만 쓴다. 적혀 있지 않으면 빈 목록으로 둔다. 추측하지 않는다.
모든 항목에는 발췌문에서 그대로 옮긴 인용문(quote)을 붙인다. 인용문은 원문 글자를 바꾸지 않고 12~80자로 옮긴다.
JSON 으로만 답한다:
{"evaluation_items": [{"name": "평가 항목 이름", "points": 숫자 또는 null, "kind": "기술|가격|기타", "quote": "..."}],
 "submission_documents": [{"text": "제출해야 하는 서류·자료 하나", "quote": "..."}],
 "format_rules": [{"text": "분량·부수·제출 방법·작성 형식에 관한 지침 하나", "quote": "..."}],
 "dated_events": [{"label": "질의 마감·제안서 제출 마감·제안 발표처럼 날짜가 적힌 일", "when": "문서에 적힌 날짜·시각 그대로", "quote": "..."}]}
evaluation_items 는 세부 항목을 우선해 최대 14개, submission_documents 최대 14개, format_rules 최대 8개, dated_events 최대 8개."""

GUIDE_SYSTEM = """너는 공공 입찰을 준비하는 회사 실무자에게 준비 지침을 정리해 준다. 제안서 글을 대신 쓰지 않는다.

지켜야 할 것
1. 회사에 관한 사실은 '회사 프로필' 에 있는 항목만 안다. 프로필에 없는 실적·인증·인력·숫자를 지어내지 않는다.
2. 준비 자료(materials)마다, 프로필 항목이 그 자료의 근거가 되면 그 id 를 company_facts 에 적고, 없으면 빈 목록으로 둔다.
3. 점수나 낙찰 가능성을 예측하지 않는다. 날짜를 지어내지 않는다.
4. 문장은 짧게, 무엇을 하라는 것인지 드러나게 쓴다.

evaluation_guides: 넘겨받은 평가 항목마다 하나(가격 평가 항목은 뺀다). name 은 넘겨받은 이름 그대로.
  materials 는 그 항목에서 점수를 받으려면 준비해야 할 자료·증빙 2~4개, focus 는 그 항목에서 보여 줘야 할 것 한 문장.
steps: 준비 순서 4~8단계. 발급·확인에 시간이 걸리는 것(신용평가서, 실적증명서, 인력 재직·자격 증빙, 공동수급 협정 등)을 앞에 둔다.
  넘겨받은 제출 서류와 작성 지침을 반영한다. 평가 항목이 없으면 제출 서류와 작성 지침만으로 쓴다.
JSON 으로만 답한다:
{"evaluation_guides": [{"name": "...", "focus": "...", "materials": [{"text": "...", "company_facts": ["C3"]}]}],
 "steps": [{"title": "...", "detail": "...", "lead_time": "오래 걸림|보통|바로 가능"}]}"""


def openai_json_caller() -> JsonCaller:
    """기본 모델을 JSON 응답으로 부른다. 키가 없으면 RuntimeError."""
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(timeout=180.0, max_retries=1)
    model = os.getenv("OPENAI_MODEL_DEFAULT") or "gpt-6-luna"
    effort = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip()

    def call(system: str, user: str) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        if effort:
            request["reasoning_effort"] = effort
        try:
            response = client.chat.completions.create(**request)
        except Exception as error:  # noqa: BLE001 - 모델이 이 파라미터를 안 받으면 빼고 한 번 더
            if "reasoning_effort" not in str(error):
                raise
            request.pop("reasoning_effort", None)
            response = client.chat.completions.create(**request)
        data = json.loads(response.choices[0].message.content or "{}")
        return data if isinstance(data, dict) else {}

    return call


def _rows(value: Any, limit: int) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)][:limit] if isinstance(value, list) else []


def _text(value: Any, limit: int = 300) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _points(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1000:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 2)


# Parents and their children both occur in extracted scoring tables. Summing them
# together double-counts technical evaluation (J22: 90 + 45 + 10 = 145).
_TECH_PARENT_NAMES = {
    "기술능력평가", "기술평가", "기술제안서평가", "기술제안평가",
}
_PRICE_PARENT_NAMES = {
    "가격평가", "입찰가격평가", "가격능력평가",
}


def evaluation_total_points(items: list[dict[str, Any]]) -> float | int | None:
    """Use category totals instead of summing a category total with its children.

    If a category's hierarchy is ambiguous, omit the total rather than
    claiming that a partial or double-counted sum is the evaluation total.
    """
    if not items:
        return None
    tech, price, other = [], [], []
    for item in items:
        category = str(item.get("kind") or "").strip()
        name = _squash(str(item.get("name") or ""))
        if name in _TECH_PARENT_NAMES or category == "기술":
            tech.append(item)
        elif name in _PRICE_PARENT_NAMES or category == "가격":
            price.append(item)
        else:
            other.append(item)

    def category_points(rows: list[dict[str, Any]], parent_names: set[str]):
        if not rows:
            return 0, False
        parent = [row for row in rows if _squash(str(row.get("name") or "")) in parent_names]
        if len(parent) > 1:
            return None, False
        # A category total is authoritative within that category, not additive.
        effective = parent if parent else rows
        numbers = [row.get("points") for row in effective]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0 for v in numbers):
            return None, False
        return sum(numbers), bool(parent)

    technical, technical_parent = category_points(tech, _TECH_PARENT_NAMES)
    prices, price_parent = category_points(price, _PRICE_PARENT_NAMES)
    if technical is None or prices is None:
        return None
    # A verified technical-category parent plus an explicit price category
    # already spans the scoring table. Unknown "other" child items (common
    # in extraction) must not erase or inflate that authoritative total.
    if technical_parent and price:
        total = technical + prices
    else:
        extras, _ = category_points(other, set())
        if extras is None:
            return None
        total = technical + prices + extras
    return int(total) if float(total).is_integer() and total > 0 else round(total, 2) if total > 0 else None


def grounded_rows(source: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """인용문이 문서에 실제로 있는 항목만 남긴다(띄어쓰기는 보지 않는다)."""
    flat = _squash(source)
    kept = []
    for row in rows:
        quote = _squash(_text(row.get("quote")))
        if len(quote) >= 6 and quote in flat:
            kept.append(row)
    return kept


def company_facts(company: Company) -> list[dict[str, str]]:
    """회사 프로필을 모델에 넘길 항목 목록으로 편다. 지침서는 이 항목 밖의 회사 사실을 말하지 못한다."""
    facts: list[tuple[str, str]] = []
    sizes = {"SMALL": "소기업", "MEDIUM": "중기업", "MID_SIZED": "중견기업", "LARGE": "대기업", "MICRO": "소상공인"}
    basics = [part for part in (company.region_name and f"소재지 {company.region_name}", sizes.get(company.company_size, company.company_size)) if part]
    if company.staff and company.staff.total_count:
        basics.append(f"상시 근로자 {company.staff.total_count}명")
    if basics:
        facts.append(("기본", ", ".join(basics)))
    industries = [f"{row.industry.name}({row.industry_code})" for row in company.industries if row.industry is not None]
    if industries:
        facts.append(("업종", ", ".join(industries[:20])))
    for item in sorted(company.performances, key=lambda row: str(row.completed_at or row.completed_year or ""), reverse=True)[:12]:
        when = item.completed_at.strftime("%Y년 %m월") if item.completed_at else (f"{item.completed_year}년" if item.completed_year else "")
        parts = [item.name, item.client_name and f"발주처 {item.client_name}", f"계약금액 {int(item.amount):,}원", when and f"{when} 완료"]
        facts.append(("실적", ", ".join(part for part in parts if part)))
    for item in company.certifications[:12]:
        parts = [item.name, item.issuer_name and f"발급 {item.issuer_name}", item.expires_at and f"유효 {item.expires_at:%Y-%m-%d}까지"]
        facts.append(("인증", ", ".join(part for part in parts if part)))
    for item in company.staff_roles[:8]:
        years = f", 경력 {float(item.career_years):g}년" if item.career_years is not None else ""
        facts.append(("인력", f"{item.role_name} {item.headcount}명{years}"))
    return [{"id": f"C{index}", "kind": kind, "text": text} for index, (kind, text) in enumerate(facts, start=1)]


def _schedule(version: BidNoticeVersion, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {"label": label, "at": value.isoformat(), "when": None, "source": "공고 일정", "quote": None}
        for label, value in (("입찰 시작", version.bid_started_at), ("입찰 마감", version.bid_closed_at), ("개찰", version.opened_at))
        if value is not None
    ]
    rows += [
        {"label": _text(row.get("label"), 80), "at": None, "when": _text(row.get("when"), 80), "source": "공고 문서", "quote": _text(row.get("quote"), 200)}
        for row in events if _text(row.get("label")) and _text(row.get("when"))
    ]
    return rows


def build_guide(*, notice: BidNotice, version: BidNoticeVersion, docs: list[tuple[str, str]], facts: list[dict[str, str]], call: JsonCaller) -> dict[str, Any]:
    """문서와 회사 프로필 항목으로 지침서를 만든다. DB 를 읽지 않는다."""
    docs = distinct_documents([(name, body) for name, body in docs if body.strip()])
    source = "\n\n".join(body for _name, body in docs)
    extracted = call(EXTRACT_SYSTEM, f"공고명: {notice.title}\n\n발췌문:\n{pick_passages(docs)}") if docs else {}
    kept = {
        "evaluation_items": grounded_rows(source, _rows(extracted.get("evaluation_items"), 14)),
        "submission_documents": grounded_rows(source, _rows(extracted.get("submission_documents"), 14)),
        "format_rules": grounded_rows(source, _rows(extracted.get("format_rules"), 8)),
        "dated_events": grounded_rows(source, _rows(extracted.get("dated_events"), 8)),
    }
    items = [
        {"name": _text(row.get("name"), 80), "points": _points(row.get("points")), "kind": _text(row.get("kind"), 10) or "기타", "quote": _text(row.get("quote"), 200)}
        for row in kept["evaluation_items"] if _text(row.get("name"))
    ]
    warnings: list[str] = []
    if not docs:
        warnings.append("이 공고에는 본문을 읽을 수 있는 첨부 문서가 없어, 공고 일정만 보여 드립니다.")
    elif not items:
        warnings.append("공고 문서에서 평가 항목과 배점을 찾지 못했습니다. 제안요청서가 첨부되지 않은 공고이거나, 가격만으로 낙찰자를 정하는 공고일 수 있습니다.")

    fact_ids = {fact["id"] for fact in facts}
    guides: dict[str, dict[str, Any]] = {}
    steps: list[dict[str, str]] = []
    if items or kept["submission_documents"] or kept["format_rules"]:
        material = {
            "공고명": notice.title,
            "평가 항목": [{"name": item["name"], "points": item["points"], "kind": item["kind"]} for item in items],
            "제출 서류": [_text(row.get("text")) for row in kept["submission_documents"]],
            "작성 지침": [_text(row.get("text")) for row in kept["format_rules"]],
        }
        drafted = call(GUIDE_SYSTEM, "공고에서 뽑은 것:\n" + json.dumps(material, ensure_ascii=False, indent=1)
                       + "\n\n회사 프로필:\n" + json.dumps(facts, ensure_ascii=False, indent=1))
        for row in _rows(drafted.get("evaluation_guides"), 20):
            materials = [
                {"text": _text(entry.get("text")), "company_facts": [fact for fact in entry.get("company_facts") or [] if fact in fact_ids]}
                for entry in _rows(row.get("materials"), 5) if _text(entry.get("text"))
            ]
            guides[_squash(_text(row.get("name"), 80))] = {"focus": _text(row.get("focus")), "materials": materials}
        steps = [
            {"title": _text(row.get("title"), 80), "detail": _text(row.get("detail"), 400),
             "lead_time": _text(row.get("lead_time"), 10) if _text(row.get("lead_time"), 10) in ("오래 걸림", "보통", "바로 가능") else "보통"}
            for row in _rows(drafted.get("steps"), 8) if _text(row.get("title"))
        ]

    evaluation = []
    for item in items:
        guide = guides.get(_squash(item["name"]), {})
        evaluation.append({**item, "focus": guide.get("focus", ""), "materials": guide.get("materials", [])})
    # 배점이 큰 항목부터. 가격 항목과 배점을 모르는 항목은 뒤로.
    evaluation.sort(key=lambda row: (row["kind"] == "가격", -(row["points"] or 0)))
    return {
        "notice": {"bid_notice_no": notice.bid_notice_no, "title": notice.title, "institution": notice.demanding_institution_name},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schedule": _schedule(version, kept["dated_events"]),
        "evaluation_items": evaluation,
        "total_points": evaluation_total_points(evaluation),
        "submission_documents": [{"text": _text(row.get("text")), "quote": _text(row.get("quote"), 200)} for row in kept["submission_documents"] if _text(row.get("text"))],
        "format_rules": [{"text": _text(row.get("text")), "quote": _text(row.get("quote"), 200)} for row in kept["format_rules"] if _text(row.get("text"))],
        "steps": steps,
        "profile_facts": facts,
        "warnings": warnings,
        "documents_read": [name for name, _body in docs],
    }


def judged_cases(db: Session, company_id) -> list[dict[str, Any]]:
    """판정이 끝난(판정 기록이 하나라도 있는) 검토 건. 가장 최근 판정의 결과를 붙인다."""
    runs = db.execute(
        select(QualificationJudgmentRun.preflight_case_id, QualificationJudgmentRun.overall_status, QualificationJudgmentRun.created_at)
        .where(QualificationJudgmentRun.company_id == company_id)
        .order_by(QualificationJudgmentRun.created_at.desc())
    ).all()
    latest: dict[Any, tuple[str, datetime]] = {}
    for case_id, status, created_at in runs:
        latest.setdefault(case_id, (status, created_at))
    if not latest:
        return []
    cases = db.scalars(select(PreflightCase).where(PreflightCase.id.in_(latest), PreflightCase.company_id == company_id)).all()
    now = datetime.now(timezone.utc)
    rows = []
    for case in cases:
        notice = db.get(BidNotice, case.notice_id)
        version = db.get(BidNoticeVersion, case.current_version_id)
        if notice is None or version is None:
            continue
        status, judged_at = latest[case.id]
        rows.append({
            "case_id": case.id, "bid_notice_no": notice.bid_notice_no, "notice_title": notice.title,
            "institution": notice.demanding_institution_name, "bid_closed_at": version.bid_closed_at,
            "expired": version.bid_closed_at is not None and version.bid_closed_at < now,
            "overall_status": status, "overall_label": DONE_STATUSES.get(status, status), "judged_at": judged_at,
        })
    rows.sort(key=lambda row: (row["expired"], -row["judged_at"].timestamp()))
    return rows


def has_judgment(db: Session, case: PreflightCase) -> bool:
    return db.scalar(select(QualificationJudgmentRun.id).where(QualificationJudgmentRun.preflight_case_id == case.id).limit(1)) is not None


def guide_for_case(db: Session, case: PreflightCase, *, call: JsonCaller) -> dict[str, Any]:
    notice = db.get(BidNotice, case.notice_id)
    version = db.get(BidNoticeVersion, case.current_version_id)
    company = db.scalar(
        select(Company).where(Company.id == case.company_id).options(
            selectinload(Company.industries).selectinload(CompanyIndustry.industry), selectinload(Company.staff),
            selectinload(Company.staff_roles), selectinload(Company.performances), selectinload(Company.certifications),
        )
    )
    documents = db.execute(
        select(NoticeDocument.name, NoticeDocument.extracted_text)
        .where(NoticeDocument.notice_version_id == version.id, NoticeDocument.extraction_status == "EXTRACTED")
        .order_by(NoticeDocument.document_order)
    ).all()
    docs = [(name, body or "") for name, body in documents if not name.startswith(GOLDEN_EXCERPT_PREFIX)]
    return build_guide(notice=notice, version=version, docs=docs, facts=company_facts(company) if company else [], call=call)
