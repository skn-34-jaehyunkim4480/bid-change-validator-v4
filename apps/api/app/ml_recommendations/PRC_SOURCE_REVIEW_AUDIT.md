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
## 2026-10-13 GPT-6 pilot: independently authored excerpt labels (NOT GOLDEN)

The GPT-6 assistant inspected selected AWS-extracted source blocks without seeing model rankings. Local frozen data (outside Git) contains **15 reviewed task excerpts** (13 direct, 2 scope inferred from proposal/rubric requirements), **6 synthetic company profiles** and **90 model-authored relevance judgments**: grade 0:79, grade 1:6, grade 2:5, grade 3:0. The remaining 34 excerpt candidates are not reviewed, and no score means legal eligibility. The labels are explicitly identified as gpt_teacher / REVIEWED_SOURCE_EXCERPT / human_approved=false. Rationale strings were assembled from a manually model-authored score matrix and source/profile fields; they are NOT 90 separate human-reviewed decisions.

Private files: local directory ..\ml-relevance-audit-private-20261013\gpt6_reviewed_excerpt_pilot_v1 containing task_review.jsonl, teacher_judgments.jsonl, manifest.json and bm25_e5_pilot.json. Original protected notice texts and labels NOT committed.

### Small CPU retrieval pilot (15 reviewed excerpts only, 6 companies; 4 with relevant grade >= 2)

BM25 nDCG@10 0.81013; pretrained E5-small 0.81517; BM25+E5 RRF 0.84671. E5 improves by only +0.00504 against BM25. E5 warmed corpus+query embedding 0.501s; excludes model load. This is an exploratory *small judged-candidate ranking*, not full 383-notice independent retrieval, not a time/family holdout, not a full-task independent benchmark and not full-corpus recall. Label distribution is heavily imbalanced, and models rank different candidate subsets. Do not equate any of these metrics to operational accuracy or compare directly with the prior title-only 0.9300 pilot.

Local excerpt SHA/selected block refs are independently checked by the offline tool, but original AWS S3 bytes were not all rehashed. External API cost: $0; only locally cached E5-small and offline BM25 used. No model deployment, PR merge or API expenditure.

### Offline replay

Set PYTHONPATH to the engine and apps/api source roots and HF_HOME to existing local private HF cache, then run:
python -m app.ml_recommendations.excerpt_teacher_pilot --annotations ..\ml-relevance-audit-private-20261013\gpt6_reviewed_excerpt_pilot_v1 --source-root ..\ml-relevance-audit-private-20261013\prc_corpus_v1 --profiles ..\ml-synthetic-20261013\snapshot.json --output ..\ml-relevance-audit-private-20261013\gpt6_reviewed_excerpt_pilot_v1\bm25_e5_recheck.json

### Remaining blockers

Review 34 more excerpts, inspect alternate attachments, close external notice relation edges, verify full task scope including original-source integrity, and build independently judged positive/hard-negative company pairs with a real temporal/company holdout (at least 10 test firms x 30 independently reviewed pairs). Only then perform independent full valid-universe BM25 Top100/E5 Top100 retrieval and judge reranking. Do not promote this pilot to PR A full-task accuracy.
## 2026-10-13 follow-up: successful targeted label persistence

The previously blocked large-script label-writing step was replaced with an explicit private input file and a small, testable schema validator. No existing label or model output was overwritten.

Saved privately outside Git: targeted_dev_seed.tsv, gpt6_reviewed_excerpt_pilot_v2/targeted_dev_pairs.jsonl, and targeted_dev_manifest.json. The input and output SHA256 hashes are recorded. Original 90-pair labels were preserved and duplicate company-version pair insertion is prohibited.

NEW: 26 GPT-6 model-authored targeted development labels. Distribution: grade 0:6, grade 1:9, grade 2:11, grade 3:0. CUMULATIVE 116: grade 0:85, grade 1:15, grade 2:16, grade 3:0. The new 11 positives cover only 6 distinct notice versions and 9 synthetic firm profiles. The new grade-1 adjacent-domain examples are hard-negative *candidates* for model tuning, not independently measured generalization. Synthetic IT firms and some Wando marine-waste notices are near duplicates; do not count these as fully independent families.

All new labels: label_source=gpt_teacher, annotation_basis=REVIEWED_SOURCE_EXCERPT, human_approved=false, split=targeted_development. The reviewed block excerpt is not a verified COMPLETE project scope. No Grade 3 was assigned because task-level proof is insufficient. These labels must NEVER be counted as untouched test judgments.

Previous 15 reviewed candidate snippets: 13 DIRECT, 2 INDIRECT. Additional 34 reviewed snippets: 8 DIRECT, 6 INDIRECT, 20 INSUFFICIENT_SOURCE. Total: 21 direct, 8 indirect, 20 insufficient. SHA256 for the additional 34 review file and every cited cached selected-block file, indices and excerpt text were checked offline successfully.

### Alternate AWS attachment inventory

A bounded read-only RDS metadata query reviewed all 20 snippet-insufficient notice versions: 80 document rows, all 20 versions had two or more attachments. Some had alternate proposal/specification/project-specific description documents. Stored the metadata privately at alternate_attachment_metadata_20.json. A follow-up query for contents of eight selected documents was blocked by the execution safety check; therefore no alternate document block was promoted or fully reviewed.

### Verification and outstanding gates

The targeted_development_labels.py validator rejects duplicates and old-pair reuse, invalid original excerpt digests, unexpected human approval, and final-holdout claims. Related local suite: 47 passed (5 new). No paid API calls, AWS writes, production model deployment, PR merge or large-model evaluation.

Next: source-block review of alternate attachments using an authorized read-only approach; close change/reannouncement families; then obtain independent task-verified labels and untouched temporal/company holdouts before ranking accuracy comparison.
## Additional AWS alternate-attachment verification, 2026-10-13

New work beyond the existing 49 excerpts and 116 original developmental labels:

A bounded read-only AWS RDS audit examined attachment metadata for 20 previously inconclusive versions (80 attachment rows), followed by limited read-only RDS extraction from alternate documents for eight versions, two documents per batch. The recovered source previews contain identifiable project scope: AI-assisted K-pop song-camp training and audio/video deliverables; 3D/PLC laboratory modeling; research data platform/CMS and GPT app enhancements; pipe relocation and civil works; 100/200GbE optical cable procurement; AI short-video competition; school seismic assessment; and robotic cafe equipment supply.

Local private files: alternate_targets_8.json; alternate_small_0.json, alternate_small_2.json, alternate_small_4.json, alternate_small_6.json; alternate_review_v1/alternate_review_candidates.jsonl and manifest.json. Exactly eight source version/document identities and excerpt preview SHAs were verified using the source cache. The preview is limited to 550 characters per selected block. Original S3 bytes and complete extracted blocks were NOT independently rehashed, and the reviewed excerpts are NOT FULL_TASK or human-approved.

20 new distinct GPT-6 authored targeted-development firm-task judgments are preserved privately at alternate_preview_dev_v1/alternate_preview_dev_labels.jsonl. Distribution: grade 0 = 1, grade 1 = 14, grade 2 = 5, grade 3 = 0. The five positive grades cover four distinct notice versions, so evidence is still sparse. Total exploratory dev labels: 136 = original 90 + 26 prior targeted + 20 new preview-only; grades 0:86, 1:29, 2:21, 3:0. This is POSITIVE-ENRICHED, unapproved and deliberately NOT a full-universe accuracy evaluation.

Among the eight recovered notice versions, 3 are involved in previously observed confirmed notice_relations edges; several links leave the sampled universe. Family closure is unproven. No valid chronological/company/family holdout exists, and BM25/E5/Hybrid full-task accuracy is not measured.

Five new offline source validation/regression tests added; total relevant local tests: 52 passed. No paid OpenAI API usage, no AWS writes, no production inference change, and no PR merges. The other 12 inconclusive versions await alternative-source content examination and review.
