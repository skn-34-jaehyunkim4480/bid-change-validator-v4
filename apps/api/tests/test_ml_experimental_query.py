"""Regression of opt-in industry query; legacy /ml is not modified."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ml_recommendations.experimental_query import industry_task_query


def company(industries, *, region="Seoul", size="SMALL", name="Golden J22",
            performances=(), certifications=(), staff_roles=()):
    return SimpleNamespace(
        name=name, region_name=region, region_code="11",
        company_size=size,
        industries=[SimpleNamespace(industry=SimpleNamespace(name=n),
                                    industry_code=code) for n, code in industries],
        performances=[SimpleNamespace(name=x) for x in performances],
        certifications=[SimpleNamespace(name=x) for x in certifications],
        staff_roles=[SimpleNamespace(role_name=x) for x in staff_roles],
    )


def test_reusable_travel_industry_expands_and_strips_company_identity():
    c = company([("\uad6d\ub0b4\uc678\uc5ec\ud589\uc5c5", "1262")])
    q = industry_task_query(c)
    assert "\uc218\ud559\uc5ec\ud589" in q
    assert "\uc5b4\ud559\uc5f0\uc218" in q
    for forbidden in ("Golden J22", "Seoul", "SMALL", "11"):
        assert forbidden not in q
    assert len(q) <= 500
    c.name = "Entirely different company"
    assert industry_task_query(c) == q


def test_domestic_only_travel_does_not_expand_to_foreign_travel():
    q = industry_task_query(company([("\uad6d\ub0b4\uc5ec\ud589\uc5c5", "1263")]))
    assert "\uc218\ud559\uc5ec\ud589" in q
    assert "\uad6d\uc678\uc5f0\uc218" not in q
    assert "\ud574\uc678\uc5f0\uc218" not in q


def test_waste_and_software_industries_have_distinct_task_expansions():
    waste = industry_task_query(company([("\uac74\uc124\ud3d0\uae30\ubb3c \uc218\uc9d1\u00b7\uc6b4\ubc18\uc5c5", "1001")]))
    it = industry_task_query(company([("\uc18c\ud504\ud2b8\uc6e8\uc5b4\uc0ac\uc5c5\uc790", "1002")]))
    assert "\uac74\uc124\ud3d0\uae30\ubb3c" in waste
    assert "\uc2dc\uc2a4\ud15c\uad6c\ucd95" in it
    assert "\uc218\ud559\uc5ec\ud589" not in it


def test_unknown_industry_uses_original_domain_label_without_hardcoded_id():
    query = industry_task_query(company([("Custom specialty supply service", "9999")]))
    assert query == "Custom specialty supply service"


def test_missing_capabilities_return_empty_for_legacy_fallback():
    assert industry_task_query(company([])) == ""


def test_experimental_uses_opt_in_query_but_keeps_legacy_default(monkeypatch, tmp_path):
    import app.ml_recommendations.router as m
    from app.ml_recommendations.experimental_runtime import read_artifacts
    from app.ml_recommendations.qualification_adapter import company_query

    profile = company([("\uad6d\ub0b4\uc678\uc5ec\ud589\uc5c5", "1262")])
    company_id = uuid4()
    monkeypatch.setenv("ML_EXPERIMENTAL_ENABLED", "true")
    monkeypatch.setenv("ML_EXPERIMENTAL_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr(m, "_load_company", lambda db, c: profile)
    monkeypatch.setattr(m, "authorize_company_access", lambda user, c: None)
    monkeypatch.setattr(m, "experimental_live_candidate_map", lambda db: {})
    monkeypatch.setattr(m, "partition_ranked", lambda *a, **kw: ([], []))
    seen = []
    def rank_proxy(corpus, vectors, **kwargs):
        seen.append(kwargs["query"])
        return dict(rankings=[], mode_used="bm25", fallback_used=False,
                    fallback_reason=None, valid_indexed_count=0,
                    live_title_fallback_count=0, latency_ms=0.0)
    monkeypatch.setattr("app.ml_recommendations.experimental_runtime.rank_artifacts",rank_proxy)
    assert company_query(profile).startswith("Golden J22")
    response=m.recommend_experimental(
        m.ExperimentalRecommendationRequest(company_id=company_id,mode="bm25"),
        db=object(),user=None)
    assert seen[-1]==company_query(profile)
    assert response.query_strategy_used=="legacy"
    response=m.recommend_experimental(
        m.ExperimentalRecommendationRequest(
            company_id=company_id,query_strategy="industry_v1",mode="bm25"),
        db=object(),user=None)
    assert seen[-1]==industry_task_query(profile)
    assert response.query_strategy_used=="industry_v1"
    response=m.recommend_experimental(
        m.ExperimentalRecommendationRequest(
            company_id=company_id,query="manually entered",query_strategy="industry_v1",mode="bm25"),
        db=object(),user=None)
    assert seen[-1]=="manually entered"
    assert response.query_strategy_used=="legacy"


def test_query_strategy_rejects_unsupported_mode():
    import app.ml_recommendations.router as m
    with pytest.raises(ValueError):
        m.ExperimentalRecommendationRequest(query="test",query_strategy="not_known")
