"""PR8 rhwp native CLI fallback is isolated and never changes legacy by default."""
import io
import json
from types import SimpleNamespace

from apps.api.app.services import document_extraction as extraction

MAGIC = bytes.fromhex("d0cf11e0a1b11ae1") + b"fake-cfb"


def test_native_only_when_preferred(monkeypatch):
    monkeypatch.setenv("BIDCHECK_RHWP_BIN", "/usr/local/bin/rhwp")
    monkeypatch.setenv("BIDCHECK_RHWP_MODE", "prefer")
    monkeypatch.setattr(extraction.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"pageCount": 2, "truncated": False,
                           "pages": [{"page": 0, "text": "첫쪽 자격요건"},
                                     {"page": 1, "text": "둘째쪽 제출서류"}]}).encode("utf8")))
    got = extraction.extract_document(io.BytesIO(MAGIC), filename="notice.hwpx", content_type=None)
    assert got.extractor == "RHWP_PR8_PAGE_TEXT"
    assert got.blocks[0]["location"] == "p.1"
    assert "제출서류" in got.text


def test_legacy_kept_on_native_failure(monkeypatch):
    monkeypatch.setenv("BIDCHECK_RHWP_BIN", "/usr/local/bin/rhwp")
    monkeypatch.setenv("BIDCHECK_RHWP_MODE", "prefer")
    monkeypatch.setattr(extraction.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout=b""))
    monkeypatch.setattr(extraction, "_extract_hwp", lambda source:
                        extraction._finish("HWP5_BODYTEXT", [{"text": "기존 정상 추출"}]))
    got = extraction.extract_document(io.BytesIO(MAGIC), filename="notice.hwp", content_type=None)
    assert got.extractor == "HWP5_BODYTEXT"


def test_existing_success_does_not_invoke_native_by_default(monkeypatch):
    monkeypatch.setenv("BIDCHECK_RHWP_BIN", "/usr/local/bin/rhwp")
    monkeypatch.delenv("BIDCHECK_RHWP_MODE", raising=False)
    def unexpected(*args, **kwargs):
        raise AssertionError("CLI must not run for already successful legacy extraction")
    monkeypatch.setattr(extraction.subprocess, "run", unexpected)
    monkeypatch.setattr(extraction, "_extract_hwp", lambda source:
                        extraction._finish("HWP5_BODYTEXT", [{"text": "기존 정상 추출"}]))
    got = extraction.extract_document(io.BytesIO(MAGIC), filename="notice.hwp", content_type=None)
    assert got.extractor == "HWP5_BODYTEXT"


def test_truncated_native_output_is_not_accepted(monkeypatch):
    monkeypatch.setenv("BIDCHECK_RHWP_BIN", "/usr/local/bin/rhwp")
    monkeypatch.setenv("BIDCHECK_RHWP_MODE", "prefer")
    monkeypatch.setattr(extraction.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"pageCount": 1, "truncated": True,
                           "pages": [{"page": 0, "text": "부분 추출"}]}).encode("utf8")))
    monkeypatch.setattr(extraction, "_extract_hwp", lambda source:
                        extraction._finish("HWP5_BODYTEXT", [{"text": "전체 원문"}]))
    got = extraction.extract_document(io.BytesIO(MAGIC), filename="notice.hwp", content_type=None)
    assert got.text == "전체 원문"