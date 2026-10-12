# [02] AI Core — BCV4-02-002 Real Golden DRAFT source audit

**Baseline:** `origin/develop` at `78cb1c0` (PR #62 merged). **Evaluation type:** offline source/selection diagnostics only; **NOT** model quality validation. No LLM/embedding calls, no production writes.

## Scope and exact provenance

- Existing `qualification-real-v0.1`: five real-notice cases, six version snapshots, 23 document records. Existing `validate_dataset` checks manifests, checksums, document/blocks SHA, version and document references. These are saved source snapshots, **not** independently approved semantic ground truth or a live AWS comparison.
- `qualification-label-drafts-v0.1/cases/C01.json`: 8 unreviewed, `PENDING` source eligibility candidates, including 4 mapped canonical candidates. The 5 risk findings are also unreviewed; they are **not** eight-type canonical labels or verdict labels.
- `R26BK01686455` G2 v1/000 → v2/001: observation `G2-region-clause-removal-candidate` is explicitly DRAFT. The baseline PDF's p.6, block 5 contains the Gangwon office location clause; the same whitespace-normalized sentence is absent from all four v2 extracted documents. This is only *exact quote absence*, not confirmed semantic removal or a safe decision to RETIRE.
- Source-only C01/C02/C03 have null DB UUID identities. Dataset document keys must never be substituted for operational DB IDs.

### Example for product review

- Notice number: `R26BK01686455`, G2 1st version (`000`) vs 2nd (`001`). Repository source identity: `9a3ca6d6-52c5-40b0-b236-57f570a93ccf`.
- Baseline document SHA-256: `69f9a125e19a95d050a5ddcbbf231c23d405dc6ac977bd952a35b450626420d1`.
- Changed document SHA-256: `91b9fae05cbd842d8f2bb17bf41074e0dac9ef4744748f7191947a6888c9f052`.
- If the legacy ID remains in the deployed database and the user's IP is allowlisted, inspect the site's `/notices/9a3ca6d6-52c5-40b0-b236-57f570a93ccf` page and its two versions, then compare the qualification section on original PDF page 6. This route exists in the web code, but current live DB identity and login access were **not verified**.

## Offline deterministic findings (no extractor/model)

| Measure | Value | Meaning |
| --- | ---: | --- |
| C01 draft label raw-location grounding | 8/8 | Each draft quote agrees with its specified original block(s), section and paragraph coordinates. Not independent semantic approval. |
| C01 draft candidates inside selected chunks | 8/8 | **Provisional selection coverage**, not requirement recall. |
| C01 candidates visible within 32k context | 8/8 | No selected C01 draft quote was truncated. |
| C04 legacy selection | 169 chunks | Candidate selection volume, not 169 qualifications. |
| C04 serialized selection | 35,716 characters | 3,716 characters past the 32k context limit; confirm against real runtime mode before altering prioritization. |
| G2 baseline Gangwon quote present/selected | yes / yes | Extracted/source-block observation. |
| G2 v2 exact quote absent | yes | Does not establish that the restriction was legally repealed. |
| Approved semantic labels | 0 | No evidence for model extraction quality threshold. |
| Requirement Precision / Recall / F1 | **NOT_MEASURED** | No approved exhaustive truth and no model inference. |
| Evidence match / false definitive judgments / UNKNOWN quality | **NOT_MEASURED** | No compared model/production judgment outputs or reviewed company profile truth. |

These are **not** model results: no LLM structured extraction was run and no synthetic/pending labels were promoted. The runner returns `null` for model PRF, evidence accuracy and wrong definitive judgments.

### Context limitations / risk

The offline adapter exercises the existing **legacy selection-only** path. The production system also supports `clause`, `hybrid`, and `closed_first` paths and can use LLM-assisted selection; the above truncation cannot be assumed to occur identically in the currently deployed mode. In C04, content after the 32k limit includes scheduling/evaluation material, so this count alone is **not** evidence of lost mandatory conditions. Do not patch the selector based solely on chunk count.

## AWS read-only verification

- STS read access valid; `bidcheck-dev` RDS reported `available`, PostgreSQL `17.11`; EC2 running and registered Online with SSM. SSM read-only inventory found the existing API, Worker, Poller, Web and Caddy containers.
- Existing S3 bucket small LIST/HEAD/GET checks were permitted. Exact prefix `R26BK01686455/` yielded **0 listed objects**; this does **not** prove missing original files without RDS `storage_key` mapping. Do not infer a document loss.
- Local direct RDS TCP attempt timed out. **RDS SELECT, current analysis run Fingerprint, live Evidence/qualification rows and current S3 SHA cross-check: NOT_RUN / UNVERIFIED**. No production analysis rows were created, deleted or changed.
- No external OpenAI API or paid embeddings invoked; no GLM call, no model deployment or credential changes. The authenticated web self-service qualification-analysis endpoint can incur paid external inference on a real new execution and was deliberately **not** called. Local GLM structured-output compatibility is **NOT_TESTED**.

## Next independent-review and accuracy gate

1. Review at least the eight C01 candidates and associated non-qualification/evaluation traps against original binary rendering, correcting draft labels and recording independent reviewer and approval time. Independently label all mandatory conditions, negations and exceptions; partial positive draft labels alone cannot yield precision.
2. Cover at least 20 diverse notices with 100+ source positive conditions and 100+ reviewed negatives/traps, all canonical types, industry/registration, AND/OR, amount/duration, multiple legal exceptions, and at least 10 G1→G2 transitions. Include distinct company profiles with independently verified judgment truth for false `SATISFIED` and `UNSATISFIED` counts. These are initial sample targets, **not a guarantee** of statistically significant performance.
3. Read-only reconcile live RDS notice/version/document IDs, source SHA, current extracted SHA and verified Fingerprints/Evidence against S3 `storage_key` and immutable snapshot. Never backfill unknown fingerprints by inference.
4. Run the deployed extractor in an isolated offline copy with a permitted nonpaid model only after verifying JSON Schema/structured-output compatibility. Do not equate deterministic unit tests, source selection coverage or guessed labels with production model precision.

## Run offline

```powershell
$env:PYTHONPATH = "engine;eval"
$env:PYTHONIOENCODING = "utf-8"
py -3 -m bideval.draft_source_audit --dataset eval/golden/qualification-real-v0.1 --draft eval/golden/qualification-label-drafts-v0.1/cases/C01.json
py -3 -m pytest -q eval/tests/test_draft_source_audit.py
```

**No AI Core or DB/API contract changes in BCV4-02-002**; this work adds a deliberately gated provenance and coverage audit, its regression tests, and this report. The feature is a **quality instrumentation improvement**, not an accuracy improvement claim.
