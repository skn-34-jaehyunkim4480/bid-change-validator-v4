import hashlib
import json

import pytest
from fastapi import HTTPException

from app.ml_recommendations.experimental_runtime import read_artifacts, rank_artifacts
from app.ml_recommendations.router import (
    ExperimentalRecommendationRequest, recommend_experimental,
)


def artifacts(tmp_path):
    docs = [
        {"notice_id": "n1", "notice_version_id": "v1", "title": "solar panel",
         "search_text": "solar panel specification", "source_status": "TASK_CANDIDATE_UNVERIFIED"},
        {"notice_id": "n2", "notice_version_id": "v2", "title": "hospital cleaning",
         "search_text": "hospital cleaning service", "source_status": "TITLE_FALLBACK"},
    ]
    blob = json.dumps(docs, ensure_ascii=False).encode()
    (tmp_path / "corpus.json").write_bytes(blob)
    vec = [0.] * 384
    vec[0] = 1.
    opposite = [0.] * 384
    opposite[1] = 1.
    query = "solar panel"
    vectors = {
        "schema": "bidcheck-e5-offline-v1", "corpus_sha256": hashlib.sha256(blob).hexdigest(),
        "docs": [{"notice_version_id": "v1", "vector": vec},
                 {"notice_version_id": "v2", "vector": opposite}],
        "queries": [{"query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                     "company_id": "test", "vector": vec}],
    }
    (tmp_path / "vectors.json").write_text(json.dumps(vectors), encoding="utf-8")
    read_artifacts.cache_clear()
    return read_artifacts(str(tmp_path))


def test_all_three_modes_and_valid_version_intersection(tmp_path):
    docs, vec = artifacts(tmp_path)
    for mode in ("bm25", "e5_small", "hybrid_rrf"):
        result = rank_artifacts(docs, vec, valid_versions={"v1"}, query="solar panel", mode=mode)
        assert result["mode_used"] == mode
        assert result["valid_indexed_count"] == 1
        assert [x["notice_version_id"] for x in result["rankings"]] == ["v1"]


def test_e5_query_absent_never_loads_model_and_falls_back(tmp_path):
    docs, vec = artifacts(tmp_path)
    result = rank_artifacts(docs, vec, valid_versions={"v1", "v2"},
                            query="different profile", mode="hybrid_rrf")
    assert result["mode_used"] == "bm25"
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "NO_EXACT_CACHED_QUERY_VECTOR"


def test_no_active_notices_cannot_recommend_old_snapshot(tmp_path):
    docs, vec = artifacts(tmp_path)
    result = rank_artifacts(docs, vec, valid_versions=set(), query="solar panel")
    assert result["rankings"] == []
    assert result["valid_indexed_count"] == 0


def test_corrupt_corpus_digest_rejected(tmp_path):
    artifacts(tmp_path)
    (tmp_path / "corpus.json").write_text('[{"notice_version_id":"v1"}]', encoding="utf-8")
    read_artifacts.cache_clear()
    with pytest.raises(ValueError, match="digest"):
        read_artifacts(str(tmp_path))


def test_query_not_empty(tmp_path):
    docs, vec = artifacts(tmp_path)
    with pytest.raises(ValueError, match="Empty"):
        rank_artifacts(docs, vec, valid_versions={"v1"}, query=" ")


def test_experimental_endpoint_default_is_disabled(monkeypatch):
    monkeypatch.delenv("ML_EXPERIMENTAL_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc:
        recommend_experimental(ExperimentalRecommendationRequest(query="solar panel"),
                               db=None, user=None)
    assert exc.value.status_code == 503


def test_new_live_notice_gets_title_fallback_without_stale_e5(tmp_path):
    docs, vec = artifacts(tmp_path)
    result = rank_artifacts(docs, vec, valid_versions={"v1", "v3"},
                            live_titles={"v1": "solar", "v3": "solar equipment"},
                            query="solar panel", mode="hybrid_rrf")
    assert result["valid_indexed_count"] == 1
    assert result["live_title_fallback_count"] == 1
    assert {x["notice_version_id"] for x in result["rankings"]} == {"v1", "v3"}
    assert result["fallback_used"]


def test_corrupted_artifact_uses_live_title_fallback(tmp_path, monkeypatch):
    import app.ml_recommendations.router as m
    monkeypatch.setenv("ML_EXPERIMENTAL_ENABLED", "true")
    monkeypatch.setenv("ML_EXPERIMENTAL_ARTIFACT_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(m, "candidates", lambda db, **kw: [
        {"notice_version_id":"v3","notice_id":"n3","title":"solar equipment","version_number":1}])
    monkeypatch.setattr(m, "experimental_live_candidate_map",
                        lambda db: {"v3": {"notice_id":"n3", "title":"solar equipment",
                                           "version_number":1}})
    monkeypatch.setattr(m, "partition_ranked", lambda *a, **k: ([], []))
    res = recommend_experimental(ExperimentalRecommendationRequest(query="solar panel"),
                                 db=object(), user=None)
    assert res.fallback_used
    assert res.fallback_reason == "OFFLINE_ARTIFACT_UNAVAILABLE"
    assert res.live_title_fallback_candidates == 1
    assert res.valid_live_candidates == 1


def test_experimental_api_happy_path_uses_live_version_only(monkeypatch, tmp_path):
    import app.ml_recommendations.router as m
    docs, vectors = artifacts(tmp_path)
    monkeypatch.setenv("ML_EXPERIMENTAL_ENABLED", "true")
    monkeypatch.setenv("ML_EXPERIMENTAL_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(m, "candidates", lambda db, **kw: [
        {"notice_id": "n1", "title": "solar panel", "version_number": 1,
         "is_stale": False, "analysis_run_id": None, "analysis_status": "UNKNOWN"}])
    monkeypatch.setattr(m, "experimental_live_candidate_map",
                        lambda db: {"v1": {"notice_id":"n1", "title":"solar panel",
                                           "version_number":1}})
    observed = []
    def partition(db, company_id, ranked, limit, source, query):
        observed.extend(ranked)
        return [], []
    monkeypatch.setattr(m, "partition_ranked", partition)
    result = recommend_experimental(ExperimentalRecommendationRequest(
        query="solar panel", mode="hybrid_rrf", limit=10), db=object(), user=None)
    assert result.mode_used == "hybrid_rrf"
    assert result.valid_live_candidates == 1
    assert result.indexed_live_candidates == 1
    assert result.stale_source_documents == 0
    assert [x["notice_id"] for x in observed] == ["n1"]


def test_changed_source_sha_discards_stale_vector(monkeypatch, tmp_path):
    import app.ml_recommendations.router as m
    docs, vectors = artifacts(tmp_path)
    docs[0]["selected_document"] = {
        "document_id": "ce7688d5-0d53-4d79-aaef-cff855894410",
        "extracted_sha256_metadata": "known"}
    # Update immutable artifact pair consistently.
    data = json.dumps(docs, ensure_ascii=False).encode()
    (tmp_path / "corpus.json").write_bytes(data)
    vectors["corpus_sha256"] = hashlib.sha256(data).hexdigest()
    (tmp_path / "vectors.json").write_text(json.dumps(vectors), encoding="utf-8")
    read_artifacts.cache_clear()
    monkeypatch.setenv("ML_EXPERIMENTAL_ENABLED", "true")
    monkeypatch.setenv("ML_EXPERIMENTAL_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(m, "candidates", lambda db, **kw: [
        {"notice_id": "n1", "title": "solar panel", "version_number": 1,
         "is_stale": False, "analysis_run_id": None, "analysis_status": "UNKNOWN"}])
    monkeypatch.setattr(m, "experimental_live_candidate_map",
                        lambda db: {"v1": {"notice_id":"n1", "title":"solar panel",
                                           "version_number":1}})
    monkeypatch.setattr(m, "partition_ranked", lambda *a, **k: ([], []))
    class DummyDB:
        def execute(self, stmt):
            class EmptyResult:
                def all(self):
                    return []  # Referenced attachment no longer exists
            return EmptyResult()
    result = recommend_experimental(ExperimentalRecommendationRequest(
        query="solar panel", mode="hybrid_rrf"), db=DummyDB(), user=None)
    assert result.stale_source_documents == 1
    assert result.indexed_live_candidates == 0
    assert result.live_title_fallback_candidates == 1
    assert result.mode_used == "bm25"


def test_nonfinite_document_vector_rejected(tmp_path):
    from app.ml_recommendations.experimental_runtime import read_artifacts
    artifacts(tmp_path)
    vec = json.loads((tmp_path/"vectors.json").read_text())
    vec["docs"][0]["vector"][0] = float("nan")
    (tmp_path/"vectors.json").write_text(json.dumps(vec),encoding="utf-8")
    read_artifacts.cache_clear()
    with pytest.raises(ValueError,match="Nonfinite"):
        read_artifacts(str(tmp_path))


def test_changed_or_unnormalized_query_vector_rejected(tmp_path):
    from app.ml_recommendations.experimental_runtime import read_artifacts
    artifacts(tmp_path)
    vec = json.loads((tmp_path/"vectors.json").read_text())
    vec["queries"][0]["vector"] = [10.]*384
    (tmp_path/"vectors.json").write_text(json.dumps(vec),encoding="utf-8")
    read_artifacts.cache_clear()
    with pytest.raises(ValueError,match="Invalid offline E5 query vector"):
        read_artifacts(str(tmp_path))


def test_missing_vector_and_duplicate_doc_vector_fail_closed(tmp_path):
    from app.ml_recommendations.experimental_runtime import read_artifacts
    artifacts(tmp_path)
    vec = json.loads((tmp_path/"vectors.json").read_text())
    vec["docs"][1]["notice_version_id"] = "v1"
    (tmp_path/"vectors.json").write_text(json.dumps(vec),encoding="utf-8")
    read_artifacts.cache_clear()
    with pytest.raises(ValueError,match="Duplicate or missing"):
        read_artifacts(str(tmp_path))


def test_hybrid_with_golden_query_sha_is_exact_not_similarity_match(tmp_path):
    docs, vectors = artifacts(tmp_path)
    stored_sha = vectors["queries"][0]["query_sha256"]
    assert hashlib.sha256("solar panel".encode()).hexdigest() == stored_sha
    hit = rank_artifacts(docs,vectors,valid_versions={"v1","v2"},
                         query="solar panel",mode="hybrid_rrf")
    miss = rank_artifacts(docs,vectors,valid_versions={"v1","v2"},
                          query="solar panel ",mode="hybrid_rrf")
    assert hit["mode_used"] == "hybrid_rrf"
    assert miss["mode_used"] == "bm25"
    assert miss["fallback_reason"] == "NO_EXACT_CACHED_QUERY_VECTOR"


def test_experimental_route_registered_with_main_app():
    from app.main import app
    api = app.openapi()
    assert "/api/v1/recommendations/ml" in api["paths"]
    assert "/api/v1/recommendations/ml-experimental" in api["paths"]
    assert "post" in api["paths"]["/api/v1/recommendations/ml-experimental"]



def test_fast_api_enriches_only_ranked_notices(monkeypatch, tmp_path):
    import app.ml_recommendations.router as m
    artifacts(tmp_path)
    monkeypatch.setenv("ML_EXPERIMENTAL_ENABLED", "true")
    monkeypatch.setenv("ML_EXPERIMENTAL_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(m, "experimental_live_candidate_map",
        lambda db: {"v1":{"notice_id":"n1","title":"solar panel","version_number":1},
                    "v2":{"notice_id":"n2","title":"hospital cleaning","version_number":1},
                    "v3":{"notice_id":"n3","title":"unindexed","version_number":1}})
    calls=[]
    def selected_rows(db, *, notice_ids=None, **kwargs):
        calls.append(notice_ids)
        return [{"notice_id":n,"title": {"n1":"solar panel","n2":"hospital cleaning","n3":"unindexed"}[n],
                 "version_number":1, "is_stale":False,"analysis_run_id":None,"analysis_status":"UNKNOWN"}
                for n in sorted(notice_ids)]
    monkeypatch.setattr(m,"candidates",selected_rows)
    monkeypatch.setattr(m, "partition_ranked", lambda *a,**k:([],[]))
    result=m.recommend_experimental(
        m.ExperimentalRecommendationRequest(query="solar panel",mode="hybrid_rrf",limit=5),
        db=object(),user=None)
    assert result.valid_live_candidates==3
    assert result.live_title_fallback_candidates==1
    assert len(calls)==1 and calls[0]=={"n1","n2","n3"}


def test_fast_api_discards_changed_title_during_rich_enrichment(monkeypatch,tmp_path):
    import app.ml_recommendations.router as m
    artifacts(tmp_path)
    monkeypatch.setenv("ML_EXPERIMENTAL_ENABLED", "true")
    monkeypatch.setenv("ML_EXPERIMENTAL_ARTIFACT_DIR",str(tmp_path))
    monkeypatch.setattr(m,"experimental_live_candidate_map",
        lambda db:{"v1":{"notice_id":"n1","title":"solar panel","version_number":1}})
    monkeypatch.setattr(m,"candidates",lambda db,**kw:[
       {"notice_id":"n1","title":"changed title","version_number":2,
        "is_stale":False,"analysis_run_id":None,"analysis_status":"UNKNOWN"}])
    observed=[]
    monkeypatch.setattr(m,"partition_ranked",
                        lambda db,cid,rows,limit,source,query:(observed.extend(rows) or [],[]))
    result=m.recommend_experimental(
        m.ExperimentalRecommendationRequest(query="solar panel",mode="bm25"),
        db=object(),user=None)
    assert observed==[]
    assert result.valid_live_candidates==1


def test_enrichment_shortcut_empty_notice_ids():
    from app.ml_recommendations.router import candidates
    assert candidates(object(),notice_ids=set()) == []


def test_enrichment_refuses_more_than_100_notices():
    from app.ml_recommendations.router import candidates
    with pytest.raises(ValueError,match="capped at 100"):
        candidates(object(),notice_ids={f"n{i}" for i in range(101)})



def test_sql_cancellation_predicates_match_existing_ml_candidate_policy():
    """Bind-parameter comparison catches accidental Unicode -> ?? corruption."""
    import app.ml_recommendations.router as m

    class Capture:
        def __init__(self):
            self.statement = None

        def execute(self, statement):
            self.statement = statement
            return []

    old_db, new_db = Capture(), Capture()
    assert m.candidates(old_db) == []
    assert m.experimental_live_candidate_map(new_db) == {}

    def cancel_patterns(db):
        assert db.statement is not None
        return {
            value for value in db.statement.compile().params.values()
            if isinstance(value, str) and value.startswith("%")
        }

    expected = {"%" + chr(0xCDE8) + chr(0xC18C) + "%",
                "%" + chr(0xBB34) + chr(0xD6A8) + "%",
                "%cancel%"}
    assert expected.issubset(cancel_patterns(old_db))
    assert cancel_patterns(new_db) == cancel_patterns(old_db)
    assert "%??%" not in cancel_patterns(new_db)


def test_experimental_live_map_defensively_excludes_cancelled_and_invalid_notices():
    """Even if SQL returns a cancelled row, Python guards must reject it."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    import app.ml_recommendations.router as m

    now = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
    base = [str(uuid4()) for _ in range(12)]
    valid_posted, valid_closed = now - timedelta(days=1), now + timedelta(days=1)

    def row(i, notice_kind, version_kind):
        return (
            base[2*i], "Notice "+str(i), notice_kind,
            base[2*i+1], 1, version_kind, valid_posted, valid_closed,
        )

    normal = row(0, "regular", "regular")
    cancelled_notice = row(1, chr(0xCDE8)+chr(0xC18C), "regular")
    cancelled_version = row(2, "regular", chr(0xCDE8)+chr(0xC18C))
    invalid_notice = row(3, chr(0xBB34)+chr(0xD6A8), "regular")
    invalid_version = row(4, "regular", chr(0xBB34)+chr(0xD6A8))
    cancelled_en = row(5, "regular", "CANCELLED")
    rows = [normal, cancelled_notice, cancelled_version,
            invalid_notice, invalid_version, cancelled_en]

    class DB:
        def execute(self, stmt):
            return iter(rows)

    found = m.experimental_live_candidate_map(DB(), now=now)
    assert set(found) == {normal[3]}
    assert found[normal[3]]["notice_id"] == normal[0]
