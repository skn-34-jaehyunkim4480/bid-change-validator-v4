# AWS read-only source verification — 2026-10-13

**Purpose:** establish whether AWS contains source-bound business task data for a *new* relevance evaluation corpus. This supplements PR A's frozen local snapshot inventory; it does not make any labels or score models.

## Access path (no modification)

- Reused existing `boto3` AWS login on the WebGPT Windows VM, region `ap-northeast-2`.
- Verified the existing PostgreSQL RDS, private attachment S3 bucket, EC2 instance, and SSM Online status.
- The running API container already has configured database access. Queried via existing EC2 SSM read-only `docker exec ...` route using SQLAlchemy `SET TRANSACTION READ ONLY` and `statement_timeout`. No new database credentials, storage objects, tables, migrations, or AWS resources.
- The first **unbounded aggregate** timed out at 10 seconds. It was **not retried**. All following queries were restricted to existing version IDs, and succeeded. Do not repeat full-table scans in production.

## Actual DB evidence

The frozen 2026-10-13 local snapshot contains 32 seeded synthetic firms and **383 version IDs**. Those exact **383 IDs were matched against the live AWS RDS `notice_documents.notice_version_id`**, not matched by a fuzzy notice title. The bounded query returned:

| RDS result within these 383 versions | Count |
|---|---:|
| `EXTRACTED` document rows | 1,308 |
| Distinct version IDs with extracted documents | **375** |
| Extracted documents with 200+ characters (`extracted_char_count`) | 1,303 |
| Extracted documents with JSON extraction blocks | 1,308 |
| `UNSUPPORTED` document rows | 145 |
| `EMPTY` document rows | 20 |

The distinct-version coverage is **375 / 383 (~97.9%)** for *some* extraction text, **not** independently audited business-task coverage. Some documents are large generic procurement/contract rules rather than the project's tasks.

PostgreSQL `pg_stat_user_tables.n_live_tup` estimates at time of check (not exact counts): approximately **4,421 notices**, **4,878 versions**, **17,867 document rows**. An earlier limited 50-version document sample returned 57 EXTRACTED and 13 UNSUPPORTED among the first 70 rows.

For three version-bound attachments with filenames indicating proposals/task statements, retrieved read-only **`extracted_blocks`** and confirmed structured headings / paragraphs:

- Weather radar purchase & installation RFP: actual extraction blocks include `사업 목적` and `사업 범위` (32 regex hits across 4,294 blocks).
- VMS system project RFP/task document: `사업개요`, `사업범위`, and detailed requirements (303 regex hits across 1,254 blocks).
- Integrated IT operations and maintenance RFP: a specific IT infrastructure/service maintenance objective and `사업범위` section (165 regex hits across 3,780 blocks).

These checks establish **real source content exists in AWS**. They are not yet GPT-reviewed business relevance labels and the raw regex hits contain TOC/boilerplate. Keep their source metadata and snippets in private local files only. No original attachment contents are committed.

## Crucial correction to earlier result

The **zero notice-number intersection** between the older repository Golden 124-notice corpus and local 383-notice snapshot is *only a mismatch between those two local collections*. It does **not** imply that AWS lacks the 383 versions' body text. The RDS evidence above disproves that inference.

## Evaluation gates remaining

1. Extract a local immutable, version-bound business-task **subset**, with hashes for RDS document IDs, extracted text, source block IDs and S3 originals when verifiable. Filter out procurement boilerplate; do not automatically promote keyword matches to `VERIFIED_TASK`.
2. Resolve **confirmed notice/re-notice family closure** across samples and preserve posting timestamps. 308 of the snapshot's 383 notices are dated 2026-10-12; older, separate dates/families are needed for meaningful chronological splits. Do not artificially reshuffle dates.
3. GPT/human blind-label independent company–full-task pairs. Existing PR #73's 100 title-only labels remain frozen and must **not** become full-task truth by changing metadata.
4. Apply PR A's strict independent evaluation contract; **no valid full-task test accuracy yet**. Once ready, independently search the same full notice universe with BM25 and CPU E5-small, then evaluate judged-pool recall/nDCG, including runtime. Larger embedding/reranker models remain conditional.

## Local private evidence (uncommitted)

`..\ml-relevance-audit-private-20261013\aws_coverage_383.json` — bounded source-document coverage and 12 metadata samples.

`..\ml-relevance-audit-private-20261013\aws_task_sample.json` — source-bound heading/paragraph excerpts from three named RFPs.

`..\ml-relevance-audit-private-20261013\aws_sample_50.json` — earlier bounded 50-version result.

**No deployment, model download, paid API, data change, PR merge, or Champion promotion.**
