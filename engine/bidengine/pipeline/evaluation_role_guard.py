"""Conservative protection against treating explicit bid scoring tables as eligibility gates.

Only explicit scoring-table headed chunks can downgrade performance/experience
requirements. A matching requirement with any non-scoring evidence is left
untouched, as are all other requirement types and ungrounded evidence.
"""

from __future__ import annotations

import re
from typing import Any

from bidengine.contracts import Evidence, QualificationRequirement

# Real tenders use several score-table titles, including headings preceded by
# form numbers or page markers. A title alone is insufficient: require tabular
# score evidence *and* reject chunks containing an eligibility heading.
_SCORING_HEAD = re.compile(
    r"(?:정량\s*적?\s*평가\s*\(\s*\d+\s*점\s*\)"
    r"|평가\s*항목\s*별\s*점수\s*기준"
    r"|사업\s*수행\s*실적\s*평가\s*기준"
    r"|적격\s*업체\s*선정\s*평가\s*표"
    r"|주요\s*사업\s*수행\s*실적"
    r"|제안서\s*평가\s*기준"
    r"|평가\s*항목\s*및\s*배점"
    r"|(?:사업\s*)?수행\s*실적\s*평가\s*기준)"
)
_SCORE_TABLE_MARKER = re.compile(
    r"(?:배\s*점|평\s*점|점\s*수|평가\s*요소|평가\s*등급|등급\s*및\s*배점|\d+\s*점)"
)


def _is_scoring_only_chunk(content: str) -> bool:
    # Header must be close to the start. Do not classify incidental mentions
    # deep inside a long clause as a dedicated score table.
    if not _SCORE_TABLE_MARKER.search(content) or _ELIGIBILITY_HEADING.search(content):
        return False
    # A reference to "evaluation table" inside a qualification paragraph is
    # not the heading of that table. Match a short line prefix only.
    for line in content[:350].splitlines():
        matched = _SCORING_HEAD.search(line)
        if matched is not None and len(line[:matched.start()].strip()) <= 35:
            return True
    return False
_ELIGIBILITY_HEADING = re.compile(
    # If even an incidental bidder-eligibility reference shares the chunk,
    # do not risk converting a valid mandatory requirement into informational.
    r"(?:입찰\s*참가\s*자격|참가\s*자격\s*및\s*조건)"
)
_SCORING_ONLY_TYPES = {"PERFORMANCE_AMOUNT", "PERFORMANCE_COUNT", "EXPERIENCE_FIELD"}


def guard_scoring_only_performance(
    requirements: list[QualificationRequirement],
    evidence: list[Evidence],
    chunks: list[dict[str, Any]],
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """Keep score criteria visible as informational but never mandatory.

    To prevent false downgrades, require every citation to belong to a
    chunk with an explicit score-table heading. No quote or chunk -> no change.
    """
    by_key = {item.evidence_key: item for item in evidence}
    by_chunk = {str(chunk.get("chunk_id")): str(chunk.get("text") or "") for chunk in chunks}
    updated: list[QualificationRequirement] = []
    diagnostics: list[dict[str, Any]] = []
    for item in requirements:
        if item.requirement_role != "mandatory" or item.type not in _SCORING_ONLY_TYPES or not item.evidence_keys:
            updated.append(item)
            continue
        citations = [by_key.get(key) for key in item.evidence_keys]
        if not all(ref is not None and ref.chunk_id in by_chunk for ref in citations):
            updated.append(item)
            continue
        if not all(
            _is_scoring_only_chunk(by_chunk[ref.chunk_id])
            for ref in citations if ref is not None
        ):
            updated.append(item)
            continue
        updated.append(item.model_copy(update={
            "requirement_role": "informational",
            "required": False,
            "scope": {**item.scope, "non_eligibility_reason": "EVALUATION_SCORE_TABLE"},
        }))
        diagnostics.append({
            "code": "CLAUSE_NOT_LABELLED",
            "raw": item.raw,
            "reason": "EVALUATION_SCORE_TABLE",
            "evidence_keys": list(item.evidence_keys),
        })
    return updated, diagnostics
