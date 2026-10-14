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
# 찾는 낱말이 아닌 말들. 낱말 단위로 보고, 이것에 해당하는 낱말을 지운 나머지를 검색어로 쓴다.
# 말투가 달라도("찾아와봐", "찾아볼래", "검색 좀 해봐") 동사·부름말·조사만 걸러지게 낱말의 앞머리로 가른다.
_NOISE_TOKEN = re.compile(
    r"^(?:"
    r"(?:입찰)?공고(?:문|들)?(?:를|을|은|는|가|이|도|만|중에|중에서|에서)?|입찰|"
    r"찾(?:아(?!가)|으|기|는|을|자)\S*|검색\S*|보여\S*|알려\S*|골라\S*|"
    r"있어\S*|있나\S*|있니\S*|있을까\S*|있는지\S*|"
    r"관련\S*|관한|대한|에대한|해당하는|같은|쪽|"
    r"야|저기|음|혹시|좀|지금|현재|요즘|최근|올라온|나온|뜬|새로|"
    r"판정\S*|화면\S*|해|해봐|해줘\S*|해주\S*|줘|주세요|줄래\S*|와|와봐|봐|봐줘|부탁\S*|바로|빨리|얼른"
    r")$"
)
_PARTICLE = re.compile(r"(?:을|를|이|가|은|는|의|에|도)$")


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
    tokens = [token.strip(".,?!~…\"'「」") for token in text.split()]
    # 한 글자짜리만 남았거나 아무것도 없으면 찾을 것이 없다("공고 찾아줘").
    terms = " ".join(token for token in tokens if len(token) >= 2 and not _NOISE_TOKEN.match(token))
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


def _search(db: Session, terms: str) -> list:
    # 공고 찾기 화면과 같은 조건·순서로 찾는다(마감 전 공고 먼저).
    from ..routers.notices import _availability_order, _keyword_filters

    return db.execute(
        select(BidNotice, BidNoticeVersion)
        .join(BidNoticeVersion, (BidNoticeVersion.notice_id == BidNotice.id) & BidNoticeVersion.is_current.is_(True))
        .where(*_keyword_filters(terms))
        .order_by(_availability_order(datetime.now(timezone.utc)), BidNotice.last_seen_at.desc(), BidNotice.id.desc())
        .limit(MAX_LINKS + 1)
    ).all()


def find_notices(db: Session, terms: str) -> LinkAnswer:
    rows = _search(db, terms)
    if not rows:
        # "소프트웨어를", "용역이" 처럼 조사가 붙어 안 잡혔을 수 있다. 낱말 끝의 조사를 떼고 한 번 더 찾는다.
        bare = " ".join(_PARTICLE.sub("", token) if len(token) >= 3 else token for token in terms.split())
        if bare != terms:
            retried = _search(db, bare)
            if retried:
                rows, terms = retried, bare
    if not rows:
        return LinkAnswer(f"「{terms}」에 맞는 공고를 찾지 못했습니다. 낱말을 줄이거나 공고번호로 다시 찾아 보세요. 위쪽 검색창에서도 같은 검색을 할 수 있습니다.", [])
    more = len(rows) > MAX_LINKS
    links = [_link(notice, version, action="OPEN") for notice, version in rows[:MAX_LINKS]]
    head = f"「{terms}」로 찾은 공고입니다" + (f"(위에서 {MAX_LINKS}건만 보여 드립니다. 더 보려면 위쪽 검색창에서 같은 낱말로 찾아 주세요)" if more else "") + "."
    return LinkAnswer(head + " 「판정 화면으로」를 누르면 그 공고의 참가자격 화면이 열립니다.", links)


def _company_for(db: Session, user: AppUser | None) -> UUID | None:
    """추천의 기준이 될 회사. 계정에 회사가 있으면 그 회사다.

    시스템 관리자와 로그인 없이 쓰는 개발 환경은 계정에 회사가 없다. 이때는 화면들(AI 추천, 공고 찾기)이 고르는 것과
    같은 회사 — 가장 최근에 만든 회사 — 를 쓴다. 일반 계정에 회사가 없으면 None 이다(판정할 회사 프로필이 없다).
    """
    if user is not None and user.company_id is not None:
        return user.company_id
    if user is None or user.role == "SYSTEM_ADMIN":
        from ..models import Company
        return db.scalar(select(Company.id).order_by(Company.created_at.desc()).limit(1))
    return None


def recommended_notices(db: Session, user: AppUser | None, company_id: UUID | None) -> LinkAnswer:
    if company_id is None:
        return LinkAnswer(
            "아직 회사 프로필이 없어 추천과 판정을 할 수 없습니다. 회사 프로필 화면에서 회사명과 업종만 넣어 만들면 "
            "(나머지 항목은 비워 두어도 됩니다) AI 추천 공고를 바로 판정으로 이어 드립니다.", [])
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
        return recommended_notices(db, user, _company_for(db, user))
    terms = search_terms(message)
    if terms is not None:
        return find_notices(db, terms)
    return None
