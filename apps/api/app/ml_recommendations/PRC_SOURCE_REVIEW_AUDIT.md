# PR C: AWS source-bound relevance review corpus (offline)

**Status: PREPARATION ONLY. No verified full-task labels or accuracy estimate.**

## What has been done (2026-10-13)

- Reused existing WebGPT Windows VM AWS boto3 credentials, and the existing RDS access through EC2 SSM. Queried **read-only** using `SET TRANSACTION READ ONLY` and bounded 8–11 second statements. No RDS/S3 writes or AWS deploy.
- Sampled 60 historical notice versions in three ordered date windows (2026-09-11–14, 09-30, 10-10); 59 selected source documents, 27 with unverified task-like windows.
- Combined those with the earlier 56-version current snapshot pilot (22 task-like windows) to build **116 versions / 115 distinct notice IDs** over September and October. The combined offline review queue has **49 source-block candidates** and **67 without eligible candidate windows in the one-document selection**. Failure to find windows is not proof that the notice lacks task details.
- Queried a bounded set of `notice_relations` / `bid_notice_versions`: 41 CONFIRMED relation rows and 10 sampled notices with more than one version. Some relations lead outside the sample. The resulting corpus declares `family_linkage_status=UNVERIFIED`; no model evaluation can pass the PR A gate.
- Generated a **private** frozen `corpus_unverified.json`, `task_review_queue.jsonl`, local `source_blocks/{document_id}.blocks.json` files and `manifest.json`. All records retain notice ID/version and RDS source document ID, original-file SHA field, extracted-text SHA field, local selected-block file SHA, block refs and excerpt SHA.
- Verified the local excerpt export SHA and source block indices. The **original RDS/S3 attachment bytes were not redownloaded and independently rehashed**. RDS SHA fields are provenance metadata, not independently proven PDF/HWP digests.
- No candidate automatically becomes `VERIFIED_TASK`; no GPT Teacher/human judgment is invented. Source-verification review is a separate step from company–notice relevance labeling. Existing PR #73's 100 title-only labels/weights are preserved as-is and not treated as FULL_TASK.
- WebGPT CPU-only BM25 and multilingual-E5-small were already run in predecessor PR #77. The older two-synthetic-company title-only nDCG results are an exploratory signal, **not proof** for these new business-task inputs.

## Strict next-stage blockers

1. **Review** source windows for actual project scope and reject tables of contents, contract/eligibility boilerplate and missing text. Where the first preferred attachment contains no task, inspect alternate version-bound source attachments. Repeat excerpt/SHA checks after selection.
2. **Close** relations across sample boundaries, including confirmed reannouncements, historical versions and suggested/unresolved links, and separately check train/validation/test family membership.
3. Keep strict chronological non-overlapping train/validation/test and distinct company profiles. The actual date distribution and verified project diversity determine feasible holdout sizes; never reshuffle posting dates to satisfy the gate.
4. Prepare *blind* GPT Teacher/human review tasks from independently retrieved BM25 Top 100 and E5 Top 100 union after source approval. As of this PR, labels are **not purchased/created**. Due to the reported roughly $0.26 OpenAI API balance, **no additional external paid GPT API calls** without new approval.
5. The initial 300–500 review *pairs* are only a development pilot; final heldout test must **separately** meet PR #75's 10 companies x 30 judged pairs, with relevant/irrelevant examples per company, temporal and family split, no training leakage. A synthetic-company test cannot establish real-company generalization.
6. Once all PR A gates pass, the `validated_eval.py` CLI computes judged-pool nDCG@10, pooled judged Recall@50, and observed top10 judgment coverage for independently searched BM25, E5 and RRF. It **refuses** to report scores before validation. This is not full-corpus recall; do not count unjudged documents as irrelevant.
7. BGE-M3/Qwen3/Reranker and operating inference integration are **deferred**. No production Champion promotion or PR merge without explicit user approval.

## Offline reproduction (uses private files, no network)

```powershell
$env:PYTHONPATH=(Resolve-Path engine).Path+';'+(Resolve-Path apps/api).Path
py -m app.ml_recommendations.task_review_queue `
 --snapshot ..\ml-synthetic-20261013\snapshot.json `
 --draft ..\ml-relevance-audit-private-20261013\tasks\draft.json `
 --draft ..\ml-relevance-audit-private-20261013\historical_task_draft.json `
 --relations ..\ml-relevance-audit-private-20261013\lineage_sample.json `
 --industry-master data/master/industry_codes.csv `
 --out ..\ml-relevance-audit-private-20261013\prc_corpus_v2

py -c "from pathlib import Path; from app.ml_recommendations.source_audit import verify_frozen_review_queue; print(verify_frozen_review_queue(Path('..')/'ml-relevance-audit-private-20261013'/'prc_corpus_v2'))"

py -m pytest apps/api/tests/test_ml_task_review_queue.py -q
```

**Private extracted notice content and synthetic profiles are outside Git.** This PR only contains the exporters, audit/validation logic, reproducible test fixtures and this report.

PR dependency order: **#75 -> #77 -> PR C** (C targets #77's head branch). Each remains Draft/unmerged pending approval.
