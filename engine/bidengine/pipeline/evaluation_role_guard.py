"""Conservative protection against treating explicit bid scoring tables as eligibility gates.

Only explicit scoring-table headed chunks can downgrade performance/experience
requirements. A matching requirement with any non-scoring evidence is left
untouched, as are all other requirement types and ungrounded evidence.
"""

from __future__ import annotations

import re
from typing import Any

from bidengine.contracts import Evidence, QualificationRequirement

_SCORING_HEAD = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:정량\s*평가\s*\(\s*\d+\s*점\s*\)|평가\s*항목\s*별\s*점수\s*기준)"
)
_ELIGIBILITY_HEADING = re.compile(
    r"(?:^|\n)\s*(?:\d+[.)]\s*)?(?:입찰\s*참가\s*자격|참가\s*자격\s*및\s*조건)"
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
            _SCORING_HEAD.match(by_chunk[ref.chunk_id])
            and not _ELIGIBILITY_HEADING.search(by_chunk[ref.chunk_id])
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
