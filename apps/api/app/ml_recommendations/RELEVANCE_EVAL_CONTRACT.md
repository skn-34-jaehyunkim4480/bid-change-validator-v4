# PR A — business-relevance data and blind evaluation contract

This is an **offline-only** contract, **not** a production recommendation change or an eligibility decision. No trained weights and no GPT-generated judgments are committed.

## Data lineage (`bidcheck-business-relevance-v1`)

Company: `company_id`, `profile_origin` (`synthetic` or `verified_real`), `profile_text` describing **business capabilities**, exact **official** `industry_codes` and `product_codes`. Region, registration, licenses, certifications and eligibility judgment must not be silently mixed into relevance text.

Notice: stable `notice_id`, current `notice_version_id`, `family_id` (versions, confirmed revisions and linked re-notices must share one family), timezone-aware `posted_at`, `title`, `business_type`, `task_text`, `body_status`, `task_evidence`.

`VERIFIED_TASK` means the actual business task (project scope, deliverable, technology) can be traced to one or more source blocks. Each evidence item must contain the SAME `notice_id` and `notice_version_id`, relative `source_file` under `--source-root`, actual `document_sha256`, literal `excerpt`, its `excerpt_sha256`, and `block_refs`. With `--source-root`, SHA and excerpt are rechecked against extracted block files. Without it, full-task evaluation is not ready. `MISSING`/`UNVERIFIED` body must have empty `task_text` and `task_evidence`, never substitute the title and call it a task. Extract eligibility boilerplate from task text before annotation, but keep provenance of task excerpts.

Official master mapping: only exact matching `code` + `name` + active status from `data/master/industry_codes.csv` (and future product-master importer). Synthetic GOLDEN codes and candidate synonym mappings remain unmatched. `data/domain_lexicon/seed.tsv` can inform term recognition; `candidates-v0.1.json`, `auto-candidates-v0.1.json`, and `relations-v0.1.json` have NO approved semantic expansions. Not used to fabricate relevance labels.

Review: external private JSON `schema_version`, `corpus_sha256`, `reviews` records with `company_id`, `notice_version_id`, `company_sha256`, `notice_sha256`, `split`, `grade` 0–3, `annotation_basis=FULL_TASK`, `label_source=gpt_teacher|human_reviewed`, `reviewer_id`, substantive `rationale`. `0/1` means independently judged lower relevance, **not unreviewed**. Reviews must be written independently after reading the real company and full task inputs; Python must not manufacture grade values or infer teacher review from keyword overlap. Existing 100 title-based GPT Teacher labels stay in PR #73's separate, private corpus and **cannot** be relabeled FULL_TASK automatically.

## Leakage/ready gates

- Duplicate company IDs, duplicate notice versions, duplicate reviews, stale company/task fingerprints, wrong version evidence, or missing source SHA fail closed.
- Corpus must explicitly declare `family_linkage_status=CONFIRMED_CLOSED`; otherwise its evaluation readiness fails. Strict company independence across train / validation / test; confirmed revised notices, base notice numbers, and same notice families must not cross split. Group relations must be closed **before** the corpus is frozen. Do not assume that a fuzzy similar title is a confirmed relation.
- Strict posting time separation: max(train) < min(validation) and max(validation) < min(test), based on `posted_at` (not collection time). Missing times block strict evaluation.
- Minimum 10 independently reviewed test companies, 30 tested company–notice judgments each, with both relevant (2/3) and nonrelevant (0/1) observations. These are **initial minimum gates**, not statistical proof of target accuracy. Holdout used to tune models is no longer a final untouched test.
- Audit labels and corpus snapshot digests every run. Synthetic firm evaluations are exploratory only; real-firm recommendation accuracy is not established.
- No hard negative is assigned just because a retriever missed the notice. Recall@50 measured against the pooled *judged* relevant subset must be labeled `pooled/judged Recall`, **not** full-corpus recall. nDCG@10 and MRR are judged-subset metrics until relevance coverage is sufficient. Do not treat unjudged as 0 and do not claim Champion approval.

## Independent retrieval / reviewer blinding

BM25 and embedding each search the **full same valid notice universe independently** and return up to 100 notice_version_ids per company. Store runs with `retrieval_mode=INDEPENDENT_FULL_CORPUS` and identical `universe_sha256=sha(sorted(all notice_version_ids))` and `corpus_sha256`; `audit_pool` rejects prefetched BM25-only candidates or missing universe agreement.

`make_blind_pool` combines candidate sets per company, strips model identity and rank, and sorts deterministically before presenting to the GPT/human reviewer. Keep retriever provenance/selection frequencies separately for audit. A blind pool is **not** a source of labels and selecting only the pooled candidates introduces incomplete judgments (must report it).

Rerankers may be evaluated on the same pooled candidate set, while independent *retrieval recall* must always be evaluated on each retriever's original full-universe output.

## Reproducible frozen local inventory

```powershell
$env:PYTHONPATH=(Resolve-Path apps/api).Path
py -m app.ml_recommendations.relevance_eval_inventory `
  --snapshot ..\ml-synthetic-20261013\snapshot.json `
  --golden-root eval/golden/notice-sample-20261006f `
  --industry-master data/master/industry_codes.csv `
  --out ..\ml-relevance-audit-private-20261013
```

Read-only snapshot on 2026-10-13: **32 synthetic companies**, **383 title-only notices**, Golden repository **124 different notices / 277 extracted files**, **zero matching base notice numbers**, **zero title-snapshot notices with task body**, **27 exact official industry code-name matches**, **16 unmatched company industry-code records**. These counts belong to this frozen local snapshot and cannot be generalized to the live AWS database. Local input and output remain **outside Git**; snapshot SHA256 `60dc4455c6701964396a3247da81daad9666c1e64a4d423bb8c5026d6d6f4cc1`.

This means **evaluation status: NOT RUN / no full-task independent labels**. It would be wrong to attach the 124 historical Golden texts to the 383 current snapshot notices by title similarity, or re-use PR #73's title-only label grades as full-task truth.

## Next gates

1. Obtain version-bound business task excerpts for a sufficient number of **current or historically time-splittable** notices from existing extraction/S3 sources; create local, immutable dataset with real source SHA and confirmed family closure. Existing AWS is read-only, not required by this PR.
2. Obtain blind independent relevance judgments with substantial explanations on verified full-task inputs; freeze distinct development/held-out temporal and company partitions.
3. Run baseline full-universe BM25 and CPU E5-small only **after** these gates; report latency and judged-pool recall / nDCG. Test BGE-M3/Qwen3/Reranker only if baseline is inadequate and there is storage/headroom. No AWS deploy, production Champion promotion, external paid inference or PR merge without separate approval.

Run tests with:

```powershell
$env:PYTHONPATH=(Resolve-Path engine).Path+';'+(Resolve-Path apps/api).Path
py -m pytest apps/api/tests/test_ml_relevance_eval_contract.py -q
```
