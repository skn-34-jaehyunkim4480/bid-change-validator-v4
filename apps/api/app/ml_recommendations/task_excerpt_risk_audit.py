"""Deterministic review-priority screen for *unverified* selected task excerpts.

This is not human review, not a source selection truth label, and not an
independent relevance metric. It never modifies a search corpus or ranks bids.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from .full_task_corpus import TASK_NAMES

# A single signal is not a rejection: scope details may coexist with legal rules.
CONTRACT = re.compile(
    r"계약상대자|계약조건|관련\s*법령|관계\s*법률|본\s*과업\s*계약자|"
    r"과업\s*수행자\s*.*책임|청렴계약|입찰참가|제안서\s*평가|평가위원|"
    r"계약보증금|하자보수|제출\s*서류|제안사\s*(?:일반|재무)|"
    r"불이행|위반\s*시|계약기간|입찰유의", re.I,
)
TOC = re.compile(r"목\s*차|차\s*례|CONTENTS|평가\s*항목\s*작성\s*방법", re.I)
PAGE_REFERENCES = re.compile(r"(?:\s|^)[IVX]+\.\s*.+?\d{1,3}(?=\s|$)|(?:\s|^)\d+\.\s*[^\n]{4,40}\s+\d{1,3}(?=\s|$)")
TASK = re.compile(
    r"사업\s*(?:내용|범위|목적)|과업\s*(?:내용|범위)|주요\s*(?:사양|규격|기능)|"
    r"구축\s*(?:범위|내용)|기술\s*(?:사양|규격)|물품\s*(?:규격|사양)|"
    r"제품\s*구성|납품\s*범위|설치\s*장소|개발\s*대상|"
    r"설치\s*수량|장비\s*구성|단위\s*수량", re.I,
)
MEASURABLE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:km|mm|cm|m2|㎡|MHz|GHz|Gbps|TB|GB|kW|대|개|식|톤|m³)"
    r"|RS-232|USB|LIMS|API|연계\s*기능|구체적\s*기능", re.I
)


def risk_flags(row: dict) -> list[str]:
    if row.get("source_status") != "TASK_CANDIDATE_UNVERIFIED":
        return []
    source = row.get("selected_document") or {}
    passages = source.get("excerpts") or []
    if not passages:
        return ["MISSING_SELECTED_EXCERPTS"]
    texts = [str(r.get("text", "")).strip() for r in passages]
    if not all(texts):
        return ["EMPTY_SELECTED_EXCERPT"]
    first = texts[0]
    joined = "\n".join(texts)
    reasons = []
    if TOC.search(first[:500]) and len(PAGE_REFERENCES.findall(first[:900])) >= 3:
        reasons.append("POSSIBLE_TABLE_OF_CONTENTS")
    contract = len(CONTRACT.findall(joined))
    concrete = len(TASK.findall(joined)) + len(MEASURABLE.findall(joined))
    if contract >= 2 and contract > concrete:
        reasons.append("CONTRACT_LANGUAGE_DOMINANT")
    if CONTRACT.search(first[:140]) and concrete < 2:
        reasons.append("OPENING_CONTRACT_CLAUSE")
    if not TASK_NAMES.search(str(source.get("name") or "")) and concrete == 0:
        reasons.append("NON_TASK_NAME_NO_CONCRETE_SCOPE")
    return reasons


def audit(corpus: list[dict], *, private_corpus_sha256: str) -> dict:
    counts = Counter()
    flagged = []
    ids = set()
    for row in corpus:
        version = str(row["notice_version_id"])
        if version in ids:
            raise ValueError("Duplicate notice version in corpus")
        ids.add(version)
        if row.get("source_status") != "TASK_CANDIDATE_UNVERIFIED":
            counts["TITLE_ONLY_OR_OTHER"] += 1
            continue
        counts["UNVERIFIED_CANDIDATE"] += 1
        reasons = risk_flags(row)
        if not reasons:
            counts["NO_AUTOMATIC_RISK_FLAG"] += 1
            continue
        counts["AUTOMATIC_RISK_FLAG"] += 1
        for reason in reasons:
            counts[f"FLAG_{reason}"] += 1
        src = row.get("selected_document") or {}
        flagged.append({
            "notice_version_id": version,
            "document_id": src.get("document_id"),
            "source_excerpt_sha256": src.get("excerpt_sha256"),
            "risk_reasons": reasons,
            "review_status": "UNREVIEWED_PRIORITY_QUEUE",
        })
    return {
        "status": "RULE_BASED_REVIEW_PRIORITY_ONLY_NOT_ACCURACY",
        "corpus_sha256": private_corpus_sha256,
        "corpus_count": len(corpus),
        "counts": dict(counts),
        "items": flagged,
        "false_selection_rate": "NOT_MEASURED",
        "human_review_count": 0,
        "automatically_rejected": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    opts = parser.parse_args()
    if opts.out.exists():
        raise FileExistsError("Do not overwrite frozen quality audit")
    raw = opts.corpus.read_bytes()
    output = audit(json.loads(raw), private_corpus_sha256=sha256(raw).hexdigest())
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k,v in output.items() if k != "items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
