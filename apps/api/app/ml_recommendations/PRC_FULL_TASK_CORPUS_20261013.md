# PR C continued: AWS extraction to local retrieval corpus (2026-10-13)

**Development-stage artifact only. No independently validated task accuracy.**
No AWS database/S3 writes, model deployment, merged PR, or paid API calls.

## Frozen source inventory

- Original AWS 383-version snapshot: 1,308 EXTRACTED documents in 375 versions.
- This exporter required 180+ extracted chars and JSON array blocks: 1,304 metadata rows across 374 notice versions. Four excluded by extraction-length/blocks gate.
- Bounded SSM read-only SQL batch export: 731 prioritized source document previews (up to two selected docs per version), chosen from the 1,304 metadata records.
- Source-file and extracted-text hashes are preserved as RDS metadata only, not independently verified S3 digests. At most eight preview blocks per inspected source were retained, then at most three per version selected; not full document coverage.
- The 383-version local artifact has 217 unverified TASK_CANDIDATE_UNVERIFIED, 166 TITLE_FALLBACK. This is an *automatic excerpt detection rate*, not verified task-scope correctness. Spot review found false positives in the first relaxed heuristic (309 candidates); conservative filters removed many but selected excerpts can still contain contractual boilerplate.

## Frozen offline E5 embeddings and diagnostic

- Pretrained multilingual-E5-small, locally cached model, CPU-only. Embeddings from actual tokenizer-bounded passages (not a single long truncated string), 856 document chunks for 383 versions plus 29 synthetic company query vectors. Nine document records exceeded the 8-chunk cap and were explicitly recorded as clipped.
- Comparison used the *same 383 candidate versions*, no shared BM25 prefilter.
- Previous model-authored development positives: only 10 of 21 pairs from seven profiles occur within these 383 versions. They were positively selected, not blind or human reviewed; unjudged results were not called negatives.

| Method | Known positive hits @10 | @50 | @100 |
| --- | ---: | ---: | ---: |
| BM25 | 6/10 | 7/10 | 8/10 |
| E5-small | 2/10 | 8/10 | 9/10 |
| Hybrid RRF | 6/10 | 8/10 | 9/10 |

No independent accuracy, nDCG, full recall, real-business performance, or champion promotion is claimed. Offline BM25 29 queries took 0.064s; not AWS latency.

## Local-only reproducibility

Source private root: ../ml-relevance-audit-private-20261013
Snapshot private root: ../ml-synthetic-20261013
Code entrypoints (run with apps/api and engine on PYTHONPATH):

1. python -m app.ml_recommendations.aws_full_task_export --snapshot SNAPSHOT/snapshot.json --out PRIVATE/full_task_corpus_v1 --batch-size 12
2. python -m app.ml_recommendations.offline_e5_artifact --corpus PRIVATE/full_task_corpus_v1/corpus.json --snapshot SNAPSHOT/snapshot.json --out PRIVATE/e5_small_full383_v2.json (HF_HOME existing local private cache)
3. python -m app.ml_recommendations.artifact_retrieval_eval --corpus PRIVATE/full_task_corpus_v1/corpus.json --snapshot SNAPSHOT/snapshot.json --vectors PRIVATE/e5_small_full383_v2.json --private-root PRIVATE --out PRIVATE/task_full383_e5_rrf_dev_eval_v1.json

Raw RDS excerpts, query profiles, vectors, and synthetic labels stay outside Git.

## Remaining gates

- Independently audit a blind sample for wrong attachment/task selection.
- Retrieve remaining historical candidates separately (442-version union is a different population).
- Confirm source originals/S3 SHA if claiming complete scope.
- Build independent company, notice-family and chronological holdout; no existing development labels qualify.
- PR D separate opt-in, API reads a frozen local artifact and intersects it with *live* eligible notices; no model resident in AWS.
- Arbitrary or changed company query must use lexical fallback when cached E5 query-hash is absent.

## 2026-10-14: deterministic source-excerpt review priority queue

New offline-only CLI: app.ml_recommendations.task_excerpt_risk_audit.
It reads the existing frozen private 383-version corpus but DOES NOT alter source
selection, remove any snippet, create labels, or change E5 embeddings.

Counts for exactly the frozen corpus SHA256
d5758f4b638b042bdbf9b6a218423c11fb6c06dbc529d6015ad0da70dcc39104:

- Total 383 versions; 217 unverified task candidates; 166 title fallback.
- 48 / 217 candidates flagged for priority human review: contract/qualification,
  supplier-bidding terms, or absent concrete task scope in a non-task filename.
- 169 / 217 not flagged by these rules. This is NOT evidence they are correct.
- Reasons overlap: contract dominant 42, opening contract clause 34,
  non-task filename/no concrete task signal 21.
- Compared with the earlier explicitly model-authored, short-preview 25-source
  pilot (8 flagged), the new deterministic rules catch only 4 of those 8.
  Neither is a truth set. Do not use either to calculate source precision/recall.
- All 217 retained as UNVERIFIED; automatically rejected=0; human reviewed=0.
- Private report, never committed: full_task_corpus_v1/task_excerpt_risk_v1.json.
  Has document IDs and original selected excerpt SHA for source audit.

Command:
python -m app.ml_recommendations.task_excerpt_risk_audit
  --corpus PRIVATE/full_task_corpus_v1/corpus.json
  --out PRIVATE/full_task_corpus_v1/task_excerpt_risk_v1.json

This queue prioritizes inspecting the original source passages. No new
independently reviewed relevance labels or validated BM25/E5 comparison were
produced. The live AWS production recommendation behavior remains unchanged.
