# Qualification analysis run status audit — 2026-10-15

## Scope and provenance

Read-only production PostgreSQL inspection via AWS Systems Manager on EC2
i-080c0feecbcfb9826 in ap-northeast-2, under AWS account
226234259348. Commands fe310eca-f6bc-4773-9893-bdddbe9354a0 and
89dd282f-5dd7-4484-9b09-b1f39542011b. SQL transactions were marked
SET TRANSACTION READ ONLY. No production rows, assets, or services were changed.

The figures describe **persisted runs at audit time**, not independent broken
notices. Newer runs may supersede historical failures. Latest-row queries
partition by notice_version_id and order by created_at DESC, id DESC; they
do **not** filter to the currently valid input fingerprint.

| Population | SUCCEEDED | PARTIAL | FAILED | Total |
| --- | ---: | ---: | ---: | ---: |
| Historical runs | 77 | 97 | 24 | 198 |
| Latest run per notice version | 18 | 29 | 6 | 53 |
| Latest run per current notice version | 13 | 21 | 4 | 38 |

### Failure categories

* Historical PARTIAL: 93 of 97 runs carry EXTRACTION_PARTIAL. Strict
  source validation accounted for 86 dropped detail spans and 70 dropped raw
  clauses across the historical PARTIAL runs. These are *dropped slot counts*,
  not unique run counts; preserving them is necessary to avoid ungrounded
  eligibility claims.
* Historical FAILED: all 24 runs carry EXTRACTION_FAILED. This includes
  historical validation failures and runs with no usable extracted blocks.
* All six latest-version FAILED records inspected have **zero extracted
  documents and zero listed attachments**, including synthetic GOLDEN and
  ASKBACK-SMOKE records and two R26BK entries. This is not evidence
  of a current widespread LLM service outage.

### J22 representative case

Notice R26BK01741999, versions 1 and 2:

* All four attachments in each version: DOWNLOADED / EXTRACTED, with
  populated extracted blocks. Document parsing did not fail.
* Version 1: PARTIAL, three canonical requirements, one dropped slot.
* Version 2: PARTIAL, eight canonical requirements, two dropped slots.
* The dropped slots in both versions report DETAIL_NOT_FOUND_IN_SOURCE
  (industry-name detail fields). The engine appropriately withholds a fully
  successful analysis instead of trusting unmatched model output.
* Deterministic industry-code salvage and the separate J22 qualification
  judgment repair are outside this change's scope.

## Code issue and targeted mitigation

extract_legacy_slots had a max_retry argument and retried when *all*
model-proposed slots failed grounding, but returned FAILED immediately on
any structured_extract exception. A transient extractor transport failure
therefore bypassed the caller's already-configured retry budget.

The fix retries extraction exceptions up to that existing budget. It retains:
source-grounding validation, failure status after exhaustion, bounded call
count (max_retry + 1), the response schema, and all historical run data.

This **does not claim** to fix historical PARTIAL runs, missing documents, or
model hallucinations. No expensive automatic reanalysis was performed.

## Local validation

From the repository root, with PYTHONPATH including engine and eval:

py -3.12 -m pytest engine/tests -q

Result: **629 passed**, including three new exception-retry regression tests.

## Follow-up work (separate scope)

1. Identify stale vs active runs by current document fingerprint before any
   reprocessing proposal.
2. Improve LLM extraction grounding for recurring rejected industry fields
   using controlled Golden comparisons; never weaken source checks merely to
   increase the SUCCEEDED rate.
3. Investigate which notices genuinely have missing attachments rather than
   historical smoke/fixture records, without modifying production data.