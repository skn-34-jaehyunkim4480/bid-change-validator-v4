"""Regression: J13-style HWP/PDF + unsupported XLSX must not block AI start."""
from types import SimpleNamespace

import pytest

from apps.api.app.qualification.document_readiness import qualification_documents


def doc(name: str, status: str, *, download: str = "DOWNLOADED", blocks=None):
    return SimpleNamespace(
        name=name, download_status=download, extraction_status=status,
        extracted_blocks=blocks if blocks is not None else ([{"text": "body"}] if status == "EXTRACTED" else None),
    )


def test_j13_supported_notice_and_unsupported_excel_is_ready():
    result = qualification_documents([
        doc("표준공고문.hwp", "EXTRACTED"),
        doc("울산삼일고등학교 공고문.pdf", "EXTRACTED"),
        doc("중간처리 내역서.xlsx", "UNSUPPORTED"),
    ])
    assert result.ready is True
    assert result.waiting is False
    assert result.skipped == ("중간처리 내역서.xlsx",)


@pytest.mark.parametrize("state", ["PENDING", "FAILED", "EMPTY"])
def test_supported_file_not_extracted_cannot_be_silently_skipped(state):
    result = qualification_documents([
        doc("notice.hwp", "EXTRACTED"), doc("details.pdf", state),
        doc("items.xlsx", "UNSUPPORTED"),
    ])
    assert result.ready is False
    assert result.waiting is True


def test_missing_download_not_skipped_even_if_status_unsupported():
    result = qualification_documents([doc("notice.hwp", "EXTRACTED"),
                                      doc("cost.xlsx", "UNSUPPORTED", download="FAILED")])
    assert result.ready is False
    assert result.skipped == ()


def test_no_usable_source_never_becomes_ready():
    for documents in ([], [doc("cost.xlsx", "UNSUPPORTED")],
                      [doc("notice.pdf", "EXTRACTED", blocks=[])]):
        result = qualification_documents(documents)
        assert result.ready is False


def test_extracted_source_with_no_blocks_must_be_reprocessed():
    result = qualification_documents([doc("notice.pdf", "EXTRACTED", blocks=[])])
    assert result.ready is False
    assert result.waiting is True
