"""Opt-in industry/task query construction for experimental retrieval ONLY.

Company geography, legal registration numbers and business size are not textual
relevance signals. They remain in the qualification profile and must never be
deleted from deterministic eligibility checks. Concepts are conservative,
reusable search associations, not legal license equivalences.
"""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class TaskConcept:
    industry_triggers: tuple[str, ...]
    task_terms: tuple[str, ...]


# First entry is an industry label/code pattern, not a company identifier.
# These are retrieval synonyms ONLY; never sufficient proof of qualification.
CONCEPTS: tuple[TaskConcept, ...] = (
    TaskConcept((
        "\uad6d\ub0b4\uc678\uc5ec\ud589\uc5c5", "\uc885\ud569\uc5ec\ud589\uc5c5",
        "1261", "1262",
    ), (
        "\uad6d\uc678\uc5f0\uc218", "\ud574\uc678\uc5f0\uc218",
        "\uc218\ud559\uc5ec\ud589", "\ud604\uc7a5\uccb4\ud5d8\ud559\uc2b5",
        "\uad6d\uc678\ud604\uc7a5\uccb4\ud5d8\ud559\uc2b5",
        "\uc5b4\ud559\uc5f0\uc218", "\uad50\uc721\uc5ec\ud589",
        "\uccb4\ud5d8\ud559\uc2b5", "\uad6d\uc678\ud604\uc7a5\uc2e4\uc2b5",
    )),
    # Domestic-only permits must not get overseas-task synonyms.
    TaskConcept(("\uad6d\ub0b4\uc5ec\ud589\uc5c5", "1263"), (
        "\uc218\ud559\uc5ec\ud589", "\ud604\uc7a5\uccb4\ud5d8\ud559\uc2b5",
        "\uad6d\ub0b4\uc5ec\ud589", "\uccb4\ud5d8\ud559\uc2b5",
        "\uad50\uc721\uc5ec\ud589", "\ud604\uc7a5\ud559\uc2b5",
    )),
    TaskConcept(("\ud3d0\uae30\ubb3c",), (
        "\ud3d0\uae30\ubb3c\ucc98\ub9ac\uc6a9\uc5ed",
        "\uc0dd\ud65c\ud3d0\uae30\ubb3c", "\uac74\uc124\ud3d0\uae30\ubb3c",
        "\ud3d0\uae30\ubb3c\ucc98\ub9ac\uc2dc\uc124",
    )),
    TaskConcept(("\ucef4\ud4e8\ud130\uad00\ub828\uc11c\ube44\uc2a4",
                 "\uc18c\ud504\ud2b8\uc6e8\uc5b4", "\uc815\ubcf4\uc2dc\uc2a4\ud15c",
                 "\ub514\uc9c0\ud138\ucf58\ud150\uce20"), (
        "\uc2dc\uc2a4\ud15c\uad6c\ucd95",
        "\uc18c\ud504\ud2b8\uc6e8\uc5b4\uac1c\ubc1c",
        "\uc815\ubcf4\uc2dc\uc2a4\ud15c\uc720\uc9c0\uad00\ub9ac",
        "\uc2dc\uc2a4\ud15c\ud1b5\ud569",
    )),
    TaskConcept(("\uc704\ud0c1\uae09\uc2dd", "\uae09\uc2dd\uc601\uc5c5"), (
        "\ud559\uad50\uae09\uc2dd", "\ub2e8\uccb4\uae09\uc2dd",
        "\uae09\uc2dd\uc704\ud0c1",
    )),
    TaskConcept(("\uc0b0\uc5c5\ub514\uc790\uc778", "\ub514\uc790\uc778\uc804\ubb38"), (
        "\ub514\uc790\uc778\uc6a9\uc5ed", "\ube0c\ub79c\ub4dc\ub514\uc790\uc778",
        "\uc2dc\uac01\ub514\uc790\uc778",
    )),
    TaskConcept(("\uc5d4\uc9c0\ub2c8\uc5b4\ub9c1", "\uac74\uc124\uc5d4\uc9c0\ub2c8\uc5b4\ub9c1"), (
        "\uac74\uc124\uc0ac\uc5c5\uad00\ub9ac", "\uac10\ub9ac",
        "\uc124\uacc4\uc6a9\uc5ed",
    )),
    TaskConcept(("\ud589\uc0ac\ub300\ud589\uc5c5",), (
        "\ud589\uc0ac\ub300\ud589", "\uc804\uc2dc\uc6b4\uc601",
        "\ud589\uc0ac \uc6b4\uc601", "\ucd95\uc81c \uc6b4\uc601",
    )),
    TaskConcept(("\uc790\ub3d9\ucc28-\ud29c\ub2dd", "\uc790\ub3d9\ucc28-\uad6d\ub0b4 \uc81c\uc791"), (
        "\ucc28\ub7c9\uc81c\uc791", "\uc790\ub3d9\ucc28\uc81c\uc791",
        "\ucc28\ub7c9\uad6c\ub9e4", "\uad6c\uc870\ubcc0\uacbd",
    )),
    TaskConcept(("\uc758\ub8cc\uae30\uae30 \ud310\ub9e4",), (
        "\uc758\ub8cc\uae30\uae30", "\uc758\ub8cc\uc7a5\ube44",
        "\uc758\ub8cc\uae30\uae30\uad6c\ub9e4",
    )),
    TaskConcept(("\uc804\uae30\uacf5\uc0ac\uc5c5",), (
        "\uc804\uae30\uacf5\uc0ac", "\uac00\ub85c\ub4f1\ubcf4\uc218",
        "\uc804\uae30\uc124\ube44\uacf5\uc0ac",
    )),
    TaskConcept(("\ud1a0\ubaa9\uacf5\uc0ac\uc5c5",), (
        "\ud1a0\ubaa9\uacf5\uc0ac", "\uac74\uc124\uacf5\uc0ac",
        "\uc2dc\uc124\uacf5\uc0ac",
    )),
    TaskConcept(("\uac00\ucd95\ubd84\ub1e8\ucc98\ub9ac",), (
        "\uac00\ucd95\ubd84\ub1e8\ucc98\ub9ac\uc2dc\uc124",
        "\ubd84\ub1e8\ucc98\ub9ac\uc2dc\uc124",
        "\ud658\uacbd\uae30\ucd08\uc2dc\uc124",
    )),
)


def industry_task_query(company) -> str:
    """Build company-agnostic retrieval query from business capabilities.

    Every company is treated by its industry/qualification attributes, never by
    synthetic Golden company IDs. Unknown industries retain their names instead
    of being silently suppressed. Input models need only industry/name fields.
    """
    bits: list[str] = []
    labels: list[str] = []
    codes: set[str] = set()
    for industry in getattr(company, "industries", ()) or ():
        obj = getattr(industry, "industry", None)
        name = (getattr(obj, "name", None) or
                getattr(industry, "name", None) or "")
        code = (getattr(industry, "industry_code", None) or
                getattr(industry, "code", None) or "")
        if isinstance(name, str) and name.strip():
            labels.append(name.strip())
            bits.append(name.strip())
        if code:
            codes.add(str(code))
    # Performance description captures concrete services rather than financial
    # values; certification/role names may contain domain-relevant terminology.
    for group, field in (("performances", "name"), ("certifications", "name"),
                         ("staff_roles", "role_name")):
        for row in (getattr(company, group, ()) or ())[:8]:
            val = getattr(row, field, None)
            if isinstance(val, str) and val.strip():
                bits.append(val.strip()[:90])

    for concept in CONCEPTS:
        if any(trigger in label for label in labels for trigger in concept.industry_triggers) or (
            codes.intersection(concept.industry_triggers)
        ):
            bits.extend(concept.task_terms)

    # Stable ordering, no repeated keywords, bounded by existing API query limit.
    unique: list[str] = []
    seen: set[str] = set()
    for value in bits:
        cleaned = " ".join(value.split())
        if cleaned and cleaned not in seen:
            unique.append(cleaned)
            seen.add(cleaned)
    return " ".join(unique)[:500]
