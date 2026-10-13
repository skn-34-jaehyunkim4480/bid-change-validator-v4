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

## Small, explicitly NON-independent task-excerpt quality screen

Deterministically sample 25 out of 217 auto-selected task-source candidates (seed=1015), review the first ~230 text characters. 8 of these 25 were flagged as POSSIBLE_BOILERPLATE_DOMINANCE (proposal evaluation tables, generic contract, warranty, supplier qualification). This is a quick model-authored risk screen, NOT full-document review and NOT a measurement of the actual 217-source false-selection rate. Useful task detail may exist elsewhere in the selected source. Full private per-version audit is stored at ml-relevance-audit-private-20261013/prd_task_excerpt_quality_sample25.json. Do not use these 25 screened fragments as an independent test set.

The new /ml-experimental route also appears under the actual main FastAPI OpenAPI schema, as does the preserved /ml route. A direct endpoint registration regression test was added. AWS production end-to-end request testing, live validity/title/document SHA matching against production RDS, and t3.small CPU/memory measurements remain NOT DONE. An additional AWS read-only freshness query was not permitted by the local execution safety check; no alternative access path was attempted.

The experiment remains opt-in, disabled by default, with no AWS updates or PR merges.

## AWS sidecar validation (2026-10-13, final reported measurements)

All work was performed in an ISOLATED Docker validation container on current EC2 t3.small. Production API/worker/poller/Caddy containers and operating /ml route were not replaced, restarted or patched. No host ports exposed. The experiment was limited to 384MB RAM, 0.8 vCPU and a root-read-only private artifact/code mount. AWS document S3 files and RDS were not updated. Artifact staging used the existing private, AES256-encrypted, public-access-blocked S3 bucket and root-only temporary local EC2 files with SHA256 verification.

- Original PR D experiment: 3 current Golden profile requests against REAL read-only RDS returned Hybrid, 347 indexed vectors and about 2,671 current live title-fallback notices. Whole-handler wall time 9.36s, 5.98s, 6.05s. A stage trace found candidates() all-notices eager analysis consumed **5,603ms out of 6,181ms**; rank_artifacts took about 211ms.
- Performance fix: experimental_live_candidate_map reads the same current validity/cancellation/deadline policy as candidates() using cheap columns and DOES NOT precompute qualifications/analysis for all 3k active notices. After ranking, expensive legacy candidates() is restricted to the top 100 notice IDs. Existing production /ml's default unrestricted candidates() call is unchanged. Changed title/version between slim and detailed reads is dropped.
- Re-test 3 Golden profiles on AWS: wall 571ms, 370ms, 359ms, all Hybrid; no detected stale extracted SHA metadata; expected title fallbacks.
- **32 / 32** REAL AWS Golden company-query profiles successfully matched exact precomputed E5 hashes and returned mode hybrid_rrf through the direct service handler, with CURRENT read-only RDS evidence (not public HTTP auth). P50 **381.69ms**, P95 **507.52ms**, max **662.1ms**. 347 indexed vectors common to the tested active population, no stale source metadata mismatch; no handler errors. Across 32 calls: 0 deterministic qualification core_met items, 160 needs_review items. These must NEVER be advertised as verified eligible companies or independent relevance validation.
- Runtime container after exercise: **117.4MiB / 384MiB**, operational main API **139.9MiB**, available host memory approximately **797MiB**. No GPU/PyTorch model on AWS; rankings use stored embeddings.
- An isolated live RDS REPEATABLE READ test directly compared the old full production candidates() + current version resolution to the new thin map at the SAME timestamp and snapshot: **3020 vs 3020**, identical notice version IDs, notice IDs, title and version number. This was the comparison instant and may change as the poller ingests notices.
- Existing isolated HTTP sidecar returned **401** for unauthenticated POST, as intended. A separate in-process FastAPI TestClient (test-only dependency override for authentication, never applied in the running service) returned **200** for a real-RDS Golden-company Hybrid request in approximately **1098ms**. This validates route registration, full handler, Pydantic serialization and HTTP contract, but is NOT a publicly accessible authenticated session or production deployed E2E performance.
- 383 frozen artifact versions vs ~3020 currently valid RDS versions is still a significant **coverage gap**: only 347 current records have these old E5 vectors; the others are discoverable by title-only BM25. This PoC's candidate coverage is useful but **not full live source-backed indexing**, and true ML retrieval precision/recall was not independently verified.
- Restart required to reload changed private frozen artifacts due in-process cache. Do not merge PRs or enable the experimental route in production without separate approval.

**Note:** This validation is strictly for the Oct 15 demo deadline; no work after the presentation is planned.

## 2026-10-13: fix malformed Unicode cancellation SQL predicates

The experimental live-candidate query contained literal percent-question-question-percent patterns in TWO LIKE filters, where the existing operational candidate policy had proper Korean cancellation/invalidity words. Fixed those two patterns to match existing /ml SQL policy; the additional _not_cancelled() and eligible_window() Python guards were already correct and remain unchanged. This is a confirmed SQL filter bug, NOT evidence that a cancelled notice actually appeared in recommendations.

Regression tests:
- Inspect actual SQLAlchemy query bound parameters and assert exact cancellation patterns match existing /ml, including absence of malformed question marks.
- Feed normal, Korean cancelled/invalid and English CANCELLED synthetic rows through the Python backup validity checks, asserting only normal remains.
- Entire targeted ML regression suite: 83 passed locally.

No PR merge or AWS production deployment performed as part of this correction. The AWS sidecar used in the preceding integration tests has already been removed.

## 2026-10-14: experimental opt-in industry/task query BM25

Only the experimental POST /api/v1/recommendations/ml-experimental accepts
query_strategy=industry_v1. Existing API requests default to legacy.
Production /ml, shared company_query() and existing legacy experiment are
UNCHANGED. The response exposes query_strategy_used, including fallback to
legacy when no usable capability fields are present. The explicit user text
query is preserved verbatim.

For a company-ID request without explicit query, industry_v1 constructs text
from industry names/codes and relevant performance, certification and staff
role names, explicitly excluding company name, region and company size from
text similarity. Company region and other attributes remain available for
deterministic eligibility checks. This version uses reusable, limited
industry-task concepts (travel, waste, software, food, design, engineering,
events, vehicle, medical, electricity, construction and agriculture). Domestic
travel does not expand to international-only tasks. Industry synonyms are
retrieval cues, not legal qualification rules.

To test, POST:
  {"company_id":"AUTHORIZED-UUID","query_strategy":"industry_v1","mode":"bm25","limit":5}

The new text SHA does not match old cached E5 query vectors. If the caller
requests Hybrid/E5 with an absent exact query vector, the runtime safely
falls back to BM25 and reports mode_used=bm25 plus its fallback_reason.
Document vectors are unchanged; no model or training modifications.

32 synthetic Golden companies evaluated using a frozen AWS read-only snapshot
of 3,585 live notices and their real, minimal company capability records.
J22 BM25 travel-topic title hits at Top10 improved from 0 to 10, and
Yeongam R26BK01741999 rank from 3580 to 14. Across the 27 profiles with
concept entries, 24 increased weak industry-keyword title matches at Top10,
3 stayed unchanged and 0 declined; 5 did not have such a diagnostic concept.
These are development-only textual proxies (the same synonym words define
the proxy), NOT independent accuracy, eligibility or verified precision.

AWS RDS read-only check: structured participation_limits populated on only
1 out of 5,996 current notice versions (including closed). Consequently
there is NO safe comprehensive region/license hard filter yet. Unknown
restrictions remain needs_review, not core_met or core_unmet.
No production deployment, no PR merge and no paid model invocations.
