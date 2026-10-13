# PR B — CPU BM25 + E5-small retrieval smoke (stacked on PR A)

This is an **offline retrieval diagnostic**, not a model rollout. It runs the pretrained `intfloat/multilingual-e5-small` on CPU, with explicit `query:` and `passage:` prompts, normalized embeddings, and `max_seq_length=256`. BM25 includes Korean character bigrams; BM25 and E5 independently score the **full 383-version frozen snapshot**, without either retriever prefiltering the other. RRF is applied to their independent Top 100 lists. No model weights, source notices, label data or results are committed.

The 383-snapshot contains titles only. A *separate* diagnostic mode optionally appends `UNVERIFIED_CANDIDATE` source blocks for 22/56 notices whose draft windows matched section keywords, **explicitly not accepted as verified task text**. Neither mode can yield valid company–full-task accuracy. Only use outputs to verify feasibility, latency, independence, and ranking diversity.

## Reproduction on GPU-less WebGPT Windows VM

```powershell
$env:PYTHONPATH=(Resolve-Path engine).Path+';'+(Resolve-Path apps/api).Path
$env:HF_HOME=(Join-Path (Resolve-Path '..\ml-relevance-audit-private-20261013').Path 'hf-cache')
py -m pip install -U sentence-transformers
# Separately cache intfloat/multilingual-e5-small once in HF_HOME.
py -m app.ml_recommendations.light_retrieval_eval `
  --snapshot ..\ml-synthetic-20261013\snapshot.json `
  --out ..\ml-relevance-audit-private-20261013\e5-title-smoke.json
# OPTIONAL diagnostic only (never production/approval):
py -m app.ml_recommendations.light_retrieval_eval `
  --snapshot ..\ml-synthetic-20261013\snapshot.json `
  --draft ..\ml-relevance-audit-private-20261013\tasks\draft.json `
  --out ..\ml-relevance-audit-private-20261013\e5-draft-smoke.json
```

Model inference uses `local_files_only=True` so subsequent comparisons don't silently download further model weights. Run all large public-HF downloads in a separate, private cache and do not commit them. Runtime includes corpus embedding + company query encoding but excludes cold model loading; query latency includes query encoding and numpy similarity but no external API/network.

## Observed CPU measurements, 2026-10-13

| Evaluation mode | Notices | Nonempty synthetic companies | Added unverified task snippets | BM25 all queries | E5 encode corpus+queries | E5 query p50/p95 | BM25/E5 Top-10 overlap |
|---|---:|---:|---:|---:|---:|---:|---:|
| Title-only | 383 | 29 | 0 | 0.173s | 1.638s | 10.18/14.50ms | 2.38/10 |
| Title + unverified task snippets | 383 | 29 | 22 | 0.023s | 2.249s | 11.05/26.01ms | 2.52/10 |

The BM25 timing difference is run-to-run variance/warm cache and **not a speedup claim**; E5 model loading is not timed. The query overlap difference indicates retrieval diversity, **not relevance improvement**. The second mode contains biased/unverified snippets and must not be used as model quality evidence.

**nDCG@10, judged Recall@50, MRR: NOT RUN (no independent full-task relevance labels).** The next phase must independently review version-hashed task excerpts and create a leakage-safe test set as defined in PR A. Only then decide between baseline BM25, CPU E5, and RRF. Do not automatically select or deploy E5 based on these measurements; BGE-M3/Qwen3/Reranker remain optional.

## Additional retrospective GPT Teacher pilot — **not production accuracy**

For an honest early signal only, we ranked the *original* PR #73 title-based GPT-6 Teacher test portion with an independently pretrained zero-shot E5-small model. This dataset has **2 synthetic companies, 20 company–notice judgments, only 10 candidates per company** and no source-bound business task bodies; strict temporal holdout was already unsuccessful. Results are therefore highly unstable and cannot approve deployment or qualify as a new independent full-task holdout.

| Retrospective title-only test | nDCG@10 |
|---|---:|
| BM25 (new Korean bigram baseline) | **0.765489** |
| Pretrained multilingual-E5-small, zero-shot | **0.930040** |
| Earlier LightGBM experiment | 0.860709 (prior report; verify exact pipeline settings before controlled comparisons) |

This is *promising but inconclusive*; retrieval can look superior on 2 synthetic firms by chance or benchmark design. The previous PR's `BM25=0.778744` used a different tokenization pipeline and should **not** be directly compared with the new BM25 number as if identical. Do not promote E5 on these figures.

```powershell
py -m app.ml_recommendations.title_only_teacher_pilot `
  --pairs ..\gpt-teacher-private-20261013\dataset\pairs.jsonl `
  --out ..\ml-relevance-audit-private-20261013\teacher_pilot_result.json
```
