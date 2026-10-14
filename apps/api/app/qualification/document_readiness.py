"""Qualification can analyze extracted documents without blocking on known unsupported attachments.

Never skip PENDING, FAILED or EMPTY documents. An unsupported item must have
been downloaded and attempted before it is excluded from the readiness gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class QualificationDocuments:
    ready: bool
    skipped: tuple[str, ...]
    waiting: bool


def qualification_documents(documents: Iterable[object]) -> QualificationDocuments:
    items = list(documents)
    extracted = 0
    skipped: list[str] = []
    waiting = False
    for document in items:
        downloaded = document.download_status == "DOWNLOADED"
        status = document.extraction_status
        if downloaded and status == "UNSUPPORTED":
            skipped.append(str(document.name))
        elif downloaded and status == "EXTRACTED" and document.extracted_blocks:
            extracted += 1
        else:
            # A source that is not yet downloaded/processed, has FAILED/EMPTY
            # extraction, or has no usable blocks must not be silently ignored.
            waiting = True
    return QualificationDocuments(
        ready=extracted > 0 and not waiting,
        skipped=tuple(skipped),
        waiting=waiting or not items,
    )
