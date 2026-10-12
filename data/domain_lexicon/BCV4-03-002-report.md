# [03] Domain Lexicon — BCV4-03-002 / AWS original spot-check, safety audit, offline retrieval

## Decision (2026-10-12)

**Do not deploy lexical expansion or context reranking.** The independent offline diagnostic shows no Recall uplift. The frozen E3 60-query historical fixture and available checked-in source blocks have **zero matching notice-round identifiers**, so the historic Dense 29.17%, Hybrid 50.00%, and LLM rerank 55.56% scores **cannot be fairly reproduced or compared** with this snapshot experiment. Those historical figures are NOT outputs of BCV4-03-002.

All data relationships remain `UNREVIEWED`, with zero legally approved synonyms. No engine, ML, product API or production search code was modified. No paid OpenAI API, embedding, or LLM invocation was executed.

## A. AWS live audit, tightly bounded

- AWS RDS `bidcheck-dev`: PostgreSQL, `available`, IAM database authentication **disabled**, public endpoint configured. Metadata-only check succeeded. **Live RDS extracted-text SELECT not run**: existing AWS RDS runtime config depends on an SSM-stored app password; the Windows worktree has no AWS CLI executable and its local `.env` resolves to a Docker `db` service rather than the AWS database. A directly usable read-only RDS SQL session was not established. This is **not** evidence that actual term extraction matches RDS.
- AWS S3: one `list_objects_v2` of maximum 90 keys and **three `get_object` calls**; max 400,000 bytes per object, combined 605,183 bytes. Original PDFs loaded into memory; no S3 write, no copied binaries in Git, no raw full-text export.
- `R26BK01707484`: SHA256 `46543ddd2df7c52dd2aaac000ed8e555e69b0a224bd3ed8f318755c2de899981`, 119,479 bytes, 7,979 characters from first six PDF pages, 19 existing expressions observed.
- `R26BK01708932`: SHA256 `f27743de3271339f66aa7e36d6038dd085b957290dc1cc2e9a3415e02d16568d`, 128,094 bytes, 13,919 characters, 17 expressions observed.
- `R26BK01715075`: SHA256 `9afb80632fbd5f004e593d568c19cd3347295a9c3a779aeba59f8bef8b5cc126`, 357,610 bytes, 2,586 characters, zero expressions in extracted text. This **does not establish that the PDF contains no relevant terms**; check extraction quality before any term-absence claim.
- S3 binary SHA256 values **are not** RDS extraction SHA256 values, and no matching extracted RDS records were verified.

Command: `py tools/domain_lexicon/aws_s3_sample.py`. **Live network access is explicit/manual only; never invoked by pytest or CI**.

## B. Additional candidate dataset integrity (independent checks)

| Item | Result |
|---|---:|
| Grounded concept anchors | 50 |
| Existing expression records / unreviewed | 123 / 123 |
| Automatic new candidates / unreviewed | 38 / 38 |
| Verified lexicon text excerpts in original blocks | 240 |
| Verified auto-candidate block and extraction SHA provenance | 38 |
| Distinct source snapshot files / unique file SHA | 277 / 271 |
| Identical file SHA reused across notice-rounds | 4 (investigation signal, not necessarily corruption) |
| Held-out qualification-real documents / matching file hashes in build corpus | 19 / 0 |
| Concept edges / broader candidates / detected cycles | 9 / 1 / 0 |
| Semantically approved synonyms | **0** |

`audit_quality.py` verifies exact raw extraction-file SHA, block text SHA, recorded block index, block location, excerpt containment (when not redacted), and auto candidate provenance. It checks contradictory and cyclical concept graph edges, duplicate block indices, and exact-byte holdout leakage. It **does not** claim legal semantic verification, nor does it check unseen semantically duplicated text across differently encoded files.

`review-triage-v0.2.json` includes **10 automated risk flags** (not human review): different lookback durations embedded in one concept, suspicious concatenated industry term `조사대상건설업`, headquarters versus business location, enterprise size hierarchies, performance categories, registration versus certification, document versus enterprise status, OR scope, and evaluation context. These are explicitly not approved synonym mappings.

## C. Out-of-sample local corpus crosscheck (not AWS RDS)

Input: `eval/golden/notice-changes-30d`, distinct from the BCV4-03-001 build corpus. Stratify by available category, at most 8 notice-rounds/category, one source document per selected version; prohibit matching notice-rounds or exact extraction SHA with build corpus.

- 23 independent notice-rounds / 23 different extraction file SHA values: SERVICE 8, GOODS 8, CONSTRUCTION 7.
- 84 / 123 lexicon surfaces observed; 39 absent in this **limited historical sample**, not deprecated terms.
- Different contexts for the same surface occur: `등록` (qualifications, submissions, unclassified), `입찰참가자격` (qualification and evaluation), `납품실적` (evaluation, submission, other), `수행실적` (submission or other). The `context_role_candidate` rule is a **weak hint**, not a truth label.

## D. Offline retrieval diagnostic, not an E3 benchmark

- Inputs: four fixed *researcher-written* query/label pairs from `data/domain_lexicon/holdout-smoke-v0.1.json`, existing `eval/golden/retrieval-v0.1/spans.json` (4 POSITIVE and 2 known TRAP labels), actual source documents from independent `qualification-real-v0.1` C01. This benchmark is **one notice / 3 documents / 328 chunks**, not E3 20 notice-rounds and 60 questions.
- Existing `bidengine.rag.retrieval._lexical_ranking` BM25 is reused; identical version-scoped records/chunks across methods; zero OpenAI calls. No use of lexicon candidate documents for index training, no use of gold quotes for reranker construction, only for post-retrieval label matching.
- All four retrievals remain within the same frozen notice version. Wrong evidence cannot be fully measured because only two trap spans are adjudicated; the reported metric is **known-trap hits**, not global false evidence rate.

| Method (same 4-query offline smoke) | Recall@4 | Recall@10 | Known TRAP hits @4 / @10 | p50 / p95 (ms; very small sample) | Paid API |
|---|---:|---:|---:|---:|---:|
| Existing BM25 | 75% (3/4) | 75% | 0 / 0 | 42.335 / 42.353 | $0 |
| NFKC + whitespace-only normalization | 75% | 75% | 0 / 0 | 41.129 / 41.632 | $0 |
| Navigation/context candidate | 75% | 75% | 0 / 0 | 48.554 / 49.488 | $0 |

Q02 (`소프트웨어사업 컴퓨터관련서비스사업 업종코드`) missed the frozen matching span in all three methods. No recall improvement and no demonstrated reduction in verified wrong evidence. Runtime comparisons have only **N=4**, are not statistically stable, and are **not** comparable to the hosted E3 latencies.

**NOT RUN (not PASS):** historical E3 Dense/Hybrid due to absent matching frozen per-version index and no-paid-embedding policy; reviewed synonym expansion because zero reviewed synonyms; selective LLM reranking and answer generation due to $0.26 API balance and paid-call prohibition.

## E. Safety and integration recommendation

- NFKC/whitespace normalization is mechanically conservative but **already present** in the existing retrieval implementation; no new product change or measurable uplift justifies adopting a separate layer.
- Candidate concept relations, not-equivalent guards and review queue can be used **offline for curator review only**.
- Never merge `최근 3년` and `최근 5년`, `중소기업` and `소기업`, `본점 소재지` and `사업장 소재지`, `등록` and `인증`, `납품실적` and `수행실적`, or arbitrary `또는` scopes into decision equivalence.
- **Do not integrate any new search or rule-engine adapter yet.** MASTER should retain current Hybrid retrieval and its existing abstention/evidence guards.
- Next genuine quality measurement: independently frozen E3 index/embeddings and same notice-version records, then read-only RDS query via approved secure credentials, followed by manually verified term-sense and evidence labels. Avoid querying gold evidence text to build lexical expansion features.

## API cost and local GLM plan

- This PR executes zero paid OpenAI API calls, zero paid embeddings, zero LLM rerank calls, and creates no AWS resources. S3 GET incurs only existing AWS request/transfer usage.
- The existing E3 script instantiates `create_openai_embeddings` and might create new embeddings if indexes are missing; rerank/full answer evaluation could call an LLM approximately once per evaluable question (historically 59 reranks and 59 generations). Exact cost cannot be safely estimated without token accounting and index cache state; **do not execute on the approximately $0.26 balance**.
- Local GLM can potentially replace a future structured-output labeling/rerank experiment, but API compatibility (`response_format` strict JSON schema, tool handling) and answer correctness have **not** been validated. Do not redirect the production model or claim GLM parity.

## Reproduce without network or paid API

```powershell
$env:PYTHONPATH="engine;eval;apps/api"
py tools/domain_lexicon/audit_quality.py
py tools/domain_lexicon/snapshot_crosscheck.py
py tools/domain_lexicon/offline_retrieval_smoke.py
py -m pytest tools/domain_lexicon/test_audit_v2.py tools/domain_lexicon/test_lexicon.py -q
```

AWS original check requires an explicit, separate manual command: `py tools/domain_lexicon/aws_s3_sample.py` (max 3 GETs). None of the offline tests requires AWS credentials.
