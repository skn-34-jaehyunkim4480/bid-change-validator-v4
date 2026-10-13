"""일반 도우미가 공고를 찾아 판정 화면으로 이어 주는 두 가지 요청(2026-10-13).

    "보안관제 공고 찾아줘"            → 공고 목록에서 찾아 준다. 화면은 공고마다 「판정 화면으로」 단추를 단다.
    "AI 추천으로 뜬 공고 판정해줘"   → AI 추천 화면과 같은 추천 결과를 가져와 준다. 화면은 「판정하기」 단추를 단다.

모델을 부르지 않는다. 문장에서 요청을 알아보는 것은 정해진 표현으로 하고(아래 정규식), 찾는 것은 공고 찾기 화면·AI 추천
화면이 쓰는 것과 같은 조회다. 그래서 요금제의 채팅 횟수도 쓰지 않는다. 알아보지 못한 문장은 평소처럼 모델이 답한다.
판정 자체는 여기서 하지 않는다 — 단추를 누르면 참가자격 화면이 열리고 거기서 검토가 시작된다(한도와 분석 비용이 그 화면의 규칙을 따른다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth_models import AppUser
from ..models import BidNotice, BidNoticeVersion

LinkAction = Literal["OPEN", "JUDGE"]
MAX_LINKS = 5


class NoticeLink(BaseModel):
    """대화 안에 다는 공고 한 건. action 이 JUDGE 면 화면이 판정 화면을 열면서 검토를 바로 시작한다."""
    notice_id: UUID
    bid_notice_no: str
    title: str
    institution: str | None = None
    bid_closed_at: datetime | None = None
    expired: bool = False
    action: LinkAction = "OPEN"
    note: str | None = None


@dataclass(frozen=True)
class LinkAnswer:
    answer: str
    links: list[NoticeLink]


_RECOMMENDED = re.compile(r"(?:AI|에이아이|인공지능)\s*추천|추천\s*(?:공고|된|으로|에\s*(?:뜬|있는|나온)|받은|해\s*준)|추천.{0,6}공고", re.IGNORECASE)
_JUDGE = re.compile(r"판정|검토|분석|확인해|가능한지|자격")
_SEARCH_VERB = re.compile(r"찾아|검색|보여\s*줘|보여\s*주|알려\s*줘|알려\s*주|있어\??$|있나|있니|있을까")
_NOTICE_NUMBER = re.compile(r"\b(?:R\d{2}[A-Z]{2}\d{6,}|\d{11,})\b", re.IGNORECASE)
# 찾는 낱말이 아닌 말들. 이것들을 지우고 남은 것을 검색어로 쓴다.
_NOISE = re.compile(
    r"(?:입찰\s*)?공고(?:문|들)?(?:를|을|은|는|가|이|도|좀|만)?|"
    r"찾아\s*(?:봐\s*)?(?:줘|주세요|줄래|줄\s*수\s*있어|주실래요)?(?:요)?|검색\s*(?:해\s*)?(?:줘|주세요|줄래)?(?:요)?|"
    r"보여\s*(?:줘|주세요|줄래)(?:요)?|알려\s*(?:줘|주세요|줄래)(?:요)?|있어\??|있나요?\??|있니\??|있을까요?\??|"
    r"관련(?:된|한)?|관한|에\s*대한|대한|해당하는|같은|좀|혹시|지금|현재|올라온|나온|뜬|중에(?:서)?|"
    r"판정\s*(?:화면)?(?:까지|으로|에서)?|해\s*줘|해\s*주세요|부탁해(?:요)?|[.?!~,]"
)


def _is_expired(version: BidNoticeVersion) -> bool:
    closed = version.bid_closed_at
    if closed is None:
        return False
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    return closed < datetime.now(timezone.utc)


def search_terms(message: str) -> str | None:
    """"…공고 찾아줘" 꼴이면 찾을 낱말을 돌려준다. 그런 요청이 아니거나 낱말이 남지 않으면 None."""
    text = message.strip()
    number = _NOTICE_NUMBER.search(text)
    if number and ("공고" in text or _SEARCH_VERB.search(text)):
        return number.group(0).upper()
    if "공고" not in text or not _SEARCH_VERB.search(text):
        return None
    terms = " ".join(_NOISE.sub(" ", text).split())
    # 한 글자짜리 조사만 남았거나 아무것도 없으면 찾을 것이 없다("공고 찾아줘").
    terms = " ".join(token for token in terms.split() if len(token) >= 2)
    return terms or None


def wants_recommended(message: str) -> bool:
    """AI 추천에 뜬 공고를 판정하거나 보여 달라는 요청인가."""
    return bool(_RECOMMENDED.search(message)) and bool(_JUDGE.search(message) or _SEARCH_VERB.search(message))


def _link(notice: BidNotice, version: BidNoticeVersion, *, action: LinkAction, note: str | None = None) -> NoticeLink:
    return NoticeLink(
        notice_id=notice.id, bid_notice_no=notice.bid_notice_no, title=notice.title,
        institution=notice.announcing_institution_name or notice.demanding_institution_name,
        bid_closed_at=version.bid_closed_at, expired=_is_expired(version), action=action, note=note,
    )


def find_notices(db: Session, terms: str) -> LinkAnswer:
    # 공고 찾기 화면과 같은 조건·순서로 찾는다(마감 전 공고 먼저).
    from ..routers.notices import _availability_order, _keyword_filters

    rows = db.execute(
        select(BidNotice, BidNoticeVersion)
        .join(BidNoticeVersion, (BidNoticeVersion.notice_id == BidNotice.id) & BidNoticeVersion.is_current.is_(True))
        .where(*_keyword_filters(terms))
        .order_by(_availability_order(datetime.now(timezone.utc)), BidNotice.last_seen_at.desc(), BidNotice.id.desc())
        .limit(MAX_LINKS + 1)
    ).all()
    if not rows:
        return LinkAnswer(f"「{terms}」에 맞는 공고를 찾지 못했습니다. 낱말을 줄이거나 공고번호로 다시 찾아 보세요. 위쪽 검색창에서도 같은 검색을 할 수 있습니다.", [])
    more = len(rows) > MAX_LINKS
    links = [_link(notice, version, action="OPEN") for notice, version in rows[:MAX_LINKS]]
    head = f"「{terms}」로 찾은 공고입니다" + (f"(위에서 {MAX_LINKS}건만 보여 드립니다. 더 보려면 위쪽 검색창에서 같은 낱말로 찾아 주세요)" if more else "") + "."
    return LinkAnswer(head + " 「판정 화면으로」를 누르면 그 공고의 참가자격 화면이 열립니다.", links)


def recommended_notices(db: Session, user: AppUser | None, company_id: UUID | None) -> LinkAnswer:
    if company_id is None:
        return LinkAnswer("AI 추천은 회사 프로필을 기준으로 합니다. 회사 프로필을 먼저 만들어 주세요.", [])
    # AI 추천 화면이 부르는 것과 같은 조회를 그대로 쓴다(추천 로직은 여기서 바꾸지 않는다).
    from fastapi import HTTPException
    from ..ml_recommendations.router import MLRecommendationRequest, recommend_ml

    try:
        result = recommend_ml(MLRecommendationRequest(company_id=company_id, limit=MAX_LINKS), db, user)
    except HTTPException as error:
        return LinkAnswer(f"AI 추천을 불러오지 못했습니다. AI 추천 화면에서 다시 확인해 주세요. ({error.detail})", [])
    labels = {"core_met": "핵심 요건 충족", "core_unmet": "핵심 요건 미충족", "needs_review": "확인 필요", "stale": "다시 분석 필요", "UNKNOWN": "미검토"}
    ranked = [*result.items, *result.needs_review_items][:MAX_LINKS]
    if not ranked:
        return LinkAnswer("지금 AI 추천에 뜬 공고가 없습니다. 회사 프로필의 업종·실적을 채우면 추천이 나옵니다.", [])
    by_id = {
        notice.id: (notice, version)
        for notice, version in db.execute(
            select(BidNotice, BidNoticeVersion)
            .join(BidNoticeVersion, (BidNoticeVersion.notice_id == BidNotice.id) & BidNoticeVersion.is_current.is_(True))
            .where(BidNotice.id.in_([item.notice_id for item in ranked]))
        ).all()
    }
    links = [
        _link(*by_id[item.notice_id], action="JUDGE", note=f"추천 {item.rank}위 · {labels.get(item.qualification_state, '미검토')}")
        for item in ranked if item.notice_id in by_id
    ]
    return LinkAnswer(
        "AI 추천에 뜬 공고입니다. 「판정하기」를 누르면 그 공고의 참가자격 화면이 열리고 검토가 바로 시작됩니다. "
        "추천 순위는 연관성 순서이고 참가자격 판정이 아닙니다.",
        links,
    )


def answer_with_links(db: Session, user: AppUser | None, message: str) -> LinkAnswer | None:
    """공고를 찾거나 추천 공고를 판정해 달라는 요청이면 답을 만든다. 아니면 None(평소처럼 모델이 답한다)."""
    if wants_recommended(message):
        return recommended_notices(db, user, user.company_id if user is not None else None)
    terms = search_terms(message)
    if terms is not None:
        return find_notices(db, terms)
    return None
