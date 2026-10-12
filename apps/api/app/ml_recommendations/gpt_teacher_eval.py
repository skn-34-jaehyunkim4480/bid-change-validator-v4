"""Same-holdout teacher-agreement comparison. Never promotes a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .search_compare import bm25_map
from .trainer import (baseline_score, deep_scorer, grouped,
                      lgb_score, load_deep, load_rows, rank_metrics)


def compare(dataset: Path, models: Path) -> dict:
    dataset, models = Path(dataset), Path(models)
    manifest = json.loads((dataset.parent / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("evaluation_scope") != "GPT_TEACHER_IMITATION_ONLY":
        raise ValueError("Teacher-only provenance required")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if manifest["sha256"]["pairs.jsonl"] != digest:
        raise ValueError("Dataset integrity check failed")
    if manifest.get("human_reviewed_labels") != 0:
        raise ValueError("This experiment must not include human-approved labels")
    training = json.loads((models / "evaluation.json").read_text(encoding="utf-8"))
    if training["dataset_sha256"] != digest or not training["evaluation_scope"].startswith("GPT_TEACHER_IMITATION_ONLY"):
        raise ValueError("Model provenance does not match GPT Teacher labels")
    filenames = {"lightgbm.txt", "bi_encoder.pt", "cross_encoder.pt"}
    if {name:hashlib.sha256((models/name).read_bytes()).hexdigest()
        for name in filenames} != training["model_sha256"]:
        raise ValueError("Model checksum mismatch")
    test = grouped(load_rows(dataset), "test")
    if not test:
        raise ValueError("Empty heldout test queries")
    import lightgbm as lgb
    bm25 = bm25_map(test)
    booster = lgb.Booster(model_file=str(models/"lightgbm.txt"))
    scorers = {
        "keyword": baseline_score,
        "bm25": lambda row: bm25[row["pair_id"]],
        "lightgbm": lambda row: lgb_score(booster, row),
        "bi_encoder": deep_scorer(load_deep(models, "bi_encoder")),
        "cross_encoder": deep_scorer(load_deep(models, "cross_encoder")),
    }
    metrics, per_company = {}, {}
    for name, fn in scorers.items():
        k10 = rank_metrics(test, fn, k=10, min_label=2)
        k20 = rank_metrics(test, fn, k=20, min_label=2)
        metrics[name] = {
            "precision_at_10": k10["Precision@K"],
            "recall_at_20": k20["Recall@K"],
            "ndcg_at_10": k10["nDCG@K"],
            "mrr": k10["MRR"],
            "rank_latency_p50_ms": k10["latency_p50_ms"],
            "rank_latency_p95_ms": k10["latency_p95_ms"],
            "test_queries": k10["queries"],
        }
        per_company[name] = [{
            "company_id": group[0]["company_id"],
            "precision_at_10": rank_metrics([group], fn, k=10, min_label=2)["Precision@K"],
            "relevant_in_sample": sum(r["label"] >= 2 for r in group),
            "sampled_candidates": len(group),
        } for group in test]
    max_precision = sum(min(10, sum(r["label"] >= 2 for r in group))
                        / min(10, len(group)) for group in test) / len(test)
    gate_reasons = []
    if len(test) < 20: gate_reasons.append("Fewer than 20 independent test company queries")
    if not manifest["strict_temporal_holdout"]:
        gate_reasons.append("Train/validation/test are not strictly time-separated")
    if any(len(group) <= 20 for group in test):
        gate_reasons.append("Recall@20 is a tautology with <=20 judged candidates per test company")
    if any(len(group) <= 10 for group in test):
        gate_reasons.append("Precision@10 cannot distinguish rankers with <=10 judged candidates per test company")
    if max_precision < .90:
        gate_reasons.append("The labeled candidate set makes Precision@10 >= .90 arithmetically unattainable")
    gate_reasons.append("No human-reviewed holdout; GPT agreement is not actual bid relevance accuracy")
    return {
        "evaluation_scope": "GPT_TEACHER_IMITATION_ONLY",
        "teacher_model": "gpt-6", "human_reviewed": False,
        "test_queries": len(test),
        "test_label_distribution": dict(Counter(str(r["label"]) for group in test for r in group)),
        "dataset_sha256": digest,
        "model_sha256": training["model_sha256"],
        "model_bytes": training["model_bytes"],
        "training_seconds": training["training_seconds"],
        "metrics": metrics, "per_company": per_company,
        "test_precision_at_10_ceiling": max_precision,
        "claimed_90_percent_success": False if gate_reasons else metrics["lightgbm"]["precision_at_10"] >= .90,
        "generalization_claim_blockers": gate_reasons,
        "champion_eligible": False,
        "latency_scope": "local CPU rank scoring over 10 candidate pairs per company; not end-to-end API",
        "bm25_latency_excludes_map_build": True,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = compare(args.dataset, args.models)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"metrics":result["metrics"],
                      "test_precision_at_10_ceiling":result["test_precision_at_10_ceiling"],
                      "goal_claimable":result["claimed_90_percent_success"],
                      "out":str(args.out)},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
