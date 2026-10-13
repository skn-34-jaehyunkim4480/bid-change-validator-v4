# PR D: Opt-in CPU-only experimental recommendation API

No changes to existing /api/v1/recommendations/ml operational semantics. New
POST /api/v1/recommendations/ml-experimental is disabled by default.

Input examples:
  {"company_id":"<uuid>","limit":20,"mode":"hybrid_rrf"}
  {"query":"software maintenance","limit":20,"mode":"bm25"}
Supported modes: bm25, e5_small, hybrid_rrf. Scores are NOT eligibility,
probability or verified model accuracy.

## Security, integrity, and freshness

- ML_EXPERIMENTAL_ENABLED defaults to false. ML_EXPERIMENTAL_ARTIFACT_DIR
  must point at the locally mounted read-only pair corpus.json/vectors.json.
- Corpus SHA256 integrity validation is mandatory. No ML transformer weights
  are loaded at API runtime; E5 is CPU dot product on frozen embeddings.
- Intersect frozen notice-version records with LIVE candidate versions from
  the existing production deadline/cancellation validity policy.
  A source document extracted-text SHA or notice-title mismatch discards
  the stale vector and falls back to current notice title BM25.
- Live valid notices missing from the offline corpus remain discoverable via
  title fallback, including newly received notices. Missing or corrupt
  artifact also uses live-title BM25 with explicit fallback reason.
- Query E5 vectors must match the exact incoming UTF-8 SHA256; any changed
  company query or arbitrary text query falls back to BM25. Existing
  locally frozen synthetic profiles are NOT guaranteed to render identical
  query strings to the production company_query function. For real-profile
  E5, precompute exact live company_query strings offline.
- Company authorization and deterministic qualification partition are
  reused. No new DB writes, paid model invocations, or data migrations.
- Locally immutable artifact cache requires restart after artifact update.

## Offline experiment, not independent accuracy

- 383 frozen current sample versions, 1304 metadata-eligible source documents
  over 374 versions, 731 selected source previews. 217 automatically selected
  UNVERIFIED task excerpts, 166 title-only fallback.
- 383 locally precomputed E5 vectors, 29 synthetic query vectors; source
  original S3 bytes not independently rehashed.
- Of 21 developer-authored positive pairs, only 10 lie in this 383-version
  sampled candidate population. BM25 Top10=6/10, E5 Top10=2/10,
  Hybrid RRF Top10=6/10. These are NOT human-judged labels.
- Local Windows artifact-only runtime: BM25 ~48ms, E5 ~57ms,
  RRF ~56ms. These times exclude actual AWS RDS lookup/qualification and
  DO NOT claim EC2 2GB performance.
- Model selection, champion validation and genuine blind holdout remain
  unproven. The deployed AWS service is UNCHANGED; no PR merged.

## Remaining user-approval-gated integration

1. Merge stacked PR #75, #77, #79 and this independent PR D after approval.
2. Place locally generated artifacts on a private read-only EC2 volume and
   configure experimental-only Docker volume/environment settings.
3. Enable opt-in API, validate live deadline/cancellation rules, provenance,
   latency and memory (actual t3.small EC2). Do not load E5 on EC2.
4. Retain existing /ml lexical fallback unless truly independent verified
   accuracy supports any change.

## 2026-10-13 local Golden query embeddings: mismatch corrected, OFFLINE only

Original 29 synthetic cached query SHA256 values had ZERO exact matches to the 32 live Golden company_query(company) strings in the AWS database. Consequently Hybrid/E5 would fall back to BM25 for real company-ID requests.

For the 32 Golden companies alone, read exact actual company_query text using a bounded READ ONLY AWS RDS transaction. Saved all sensitive profile text exclusively to private local files. Using pretrained cached intfloat/multilingual-e5-small on local CPU, generated normalized 384-dimensional vectors for query-prefixed live Golden profile strings. All 383 original notice document vectors and the same frozen corpus were preserved.

Private immutable artifact directory:
ml-relevance-audit-private-20261013/experimental_api_input_live_golden_v2
contains corpus.json (383), vectors.json (383 docs and 32 Golden queries), manifest.json with SHA hashes and explicit experimental-unverified status. Generated vectors SHA256: 66082cac75ddb7ad91f69ae312e72b1e84200a8aa9de2d51d50a1c221edbcf33.

Local real-profile playback: all 32/32 queries use Hybrid without BM25-only fallback, when all 383 frozen versions are treated as eligible. CPU full corpus retrieval p50 44ms, p95 53ms. This deliberately excludes AWS RDS filtering, application qualification and t3.small response time: no end-to-end cloud latency claim.

The runtime now validates 384/consistent document-and-query dimensions, finite numeric vectors, approximate unit norms, non-duplicated versions, consistent query hashes and sane input sizes before accepting an artifact. Any changed live company query hash continues to fall back to BM25 until its vector is regenerated. Never publish raw company profiles or vector data to GitHub.

NO AWS write, no service deployment, no model promotion, no PR merge. Independent recommendation accuracy remains unproven.
