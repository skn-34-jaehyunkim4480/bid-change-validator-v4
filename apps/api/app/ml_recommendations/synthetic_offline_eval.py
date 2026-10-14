"""Compare existing rankers on the same pseudo-labelled, isolated holdout.

These scores measure rule imitation, not independent company relevance accuracy.
No network, external model download, or Champion registration is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .search_compare import bm25_map
from .trainer import (baseline_score, deep_scorer, grouped, lgb_score,
                      load_deep, load_rows, rank_metrics)


def evaluate(dataset: Path, models: Path) -> dict:
    manifest = json.loads((dataset.parent / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("evaluation_scope") != "PSEUDO_LABELED_RULE_IMITATION":
        raise ValueError("Only the explicitly marked pseudo-label experiment is supported")
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if manifest["sha256"]["pairs.jsonl"] != digest:
        raise ValueError("Dataset SHA mismatch")
    rows = load_rows(dataset)
    test = grouped(rows, "test")
    if not test:
        raise ValueError("No holdout queries")
    import lightgbm as lgb

    bm25 = bm25_map(test)
    booster = lgb.Booster(model_file=str(models / "lightgbm.txt"))
    scorers = {
        "sql_keyword": baseline_score,
        "bm25": lambda row: bm25[row["pair_id"]],
        "lightgbm": lambda row: lgb_score(booster, row),
        "bi_encoder": deep_scorer(load_deep(models, "bi_encoder")),
        "cross_encoder": deep_scorer(load_deep(models, "cross_encoder")),
    }
    metrics = {}
    examples = {}
    for name, score in scorers.items():
        at10 = rank_metrics(test, score, k=10, min_label=2)
        at20 = rank_metrics(test, score, k=20, min_label=2)
        metrics[name] = {
            "ndcg_at_10": at10["nDCG@K"],
            "recall_at_20": at20["Recall@K"],
            "mrr": at10["MRR"],
            "latency_p50_ms_at_10": at10["latency_p50_ms"],
            "latency_p95_ms_at_10": at10["latency_p95_ms"],
            "test_queries": at10["queries"],
            "failures": at10["failures"],
        }
        examples[name] = []
        for group in test[:2]:
            ranked = sorted(group, key=lambda row: (-score(row), row["notice_id"]))
            examples[name].append({
                "synthetic_company": group[0]["query_id"],
                "top_notices": [{"notice_no": row["notice_no"],
                                 "title": row["notice_text"],
                                 "pseudo_grade": row["label"],
                                 "pseudo_reason": row["pseudo_reason"]}
                                for row in ranked[:3]],
            })
    training = json.loads((models / "evaluation.json").read_text(encoding="utf-8"))
    if training["dataset_sha256"] != digest:
        raise ValueError("Model report belongs to a different dataset")
    model_files = ("lightgbm.txt", "bi_encoder.pt", "cross_encoder.pt")
    hashes = {name: hashlib.sha256((models / name).read_bytes()).hexdigest()
              for name in model_files}
    if training["model_sha256"] != hashes:
        raise ValueError("Model artifact SHA mismatch")
    return {
        "scope": "PSEUDO_LABELED_RULE_IMITATION; NOT human-reviewed accuracy",
        "approval_labels": 0,
        "dataset_sha256": digest,
        "snapshot_sha256": manifest["snapshot_sha256"],
        "model_sha256": hashes,
        "model_bytes": training.get("model_bytes"),
        "peak_memory": "NOT_MEASURED; artifact bytes are not process RSS",
        "training_seconds": training.get("training_seconds"),
        "git_sha": training.get("git_sha"),
        "seed": training["seed"],
        "split_audit": manifest["leakage"],
        "metrics": metrics,
        "examples": examples,
        "champion_eligible": False,
        "limitations": [
            "Only pseudo-labelled synthetic companies/public notice titles; no independent relevance judgments",
            "Companies with no pseudo-positive were excluded from model evaluation",
            "The same capability-overlap family of signals generates labels and model features",
            "Ranking is restricted to the sampled candidate set, not all active AWS notices",
            "BM25 p50/p95 measures ranking after its index/score-map precomputation; not end-to-end latency",
            "Per-model memory peak was not measured",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.dataset, args.models)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"scope": report["scope"], "metrics": report["metrics"],
                      "output": str(args.out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
