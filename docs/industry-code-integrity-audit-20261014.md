# G2B industry code integrity audit ? 2026-10-14

## Official source and exhaustive comparison

Authoritative G2B API: Industry & Legal Basis, operation
getIndstrytyBaseLawrgltInfoList. Fetched pages 1/2/3
(999 + 999 + 918 rows), and compared against read-only AWS RDS.

- Official distinct valid codes: 2,916; all four digits and active.
- AWS missing official codes: 0.
- AWS official code/name/active mismatches: 0.
- AWS extra nonofficial codes: 17; 16 synthetic Golden and one pytest 0004.
- Repository data/master/industry_codes.csv already matches all 2,916 official records.
- 0004 is not an official active G2B code; official info-communication
  construction is 0036. Official electric construction is 0037.

## Failure source and risk

The shared Golden v0.2 seed created synthetic GOLDEN-Jxx-xx
industry IDs for missing fixture codes; 16 prior master rows remain
active. J22 synthetic domestic/overseas travel needs the official
1262 identifier to match a 1262 notice. J24 general construction
engineering uses official 4966. The test fixtures used 0003 and 0004
with erroneous names; general-contractor rule mistakenly included 0004.
Code matching can produce false UNSATISFIED for the actual J22 profile
when the requirement is a four-digit official code.

## Safe change and scope

- Hide active Golden or pytest-only master rows from the normal
  industry picker and new company industry writes, preserving
  historical per-code lookups and FK relations.
- Correct test fixtures and general-contractor list.
- Make shared Golden seeds map J22 -> 1262 and J24 -> 4966 after
  verifying the official master; preserve standalone Golden fixtures.
  Never guess a mapping for the ambiguous J09-J12, J19, J23 or J26.
- Force old Golden synthetic master rows inactive when shared seed
  encounters them, without removing FK historical records.
- A strict, idempotent repair helper supports read-only default,
  optional apply, case identity and provenance guards, retention of
  verification flags and immutable historical judgment records.

## Verification performed

- Clean local PostgreSQL 17 migrations; 91 relevant API, Golden,
  judgment-engine and ML regression tests passed.
- Separate local DB imported 2,916 official codes and seeded all 32
  Golden companies in shared mode; J22 and J24 are canonical. Its
  read-only repair audit reports zero pending edits.
- Regression test emulated the 17 legacy active test masters and two
  synthetic profile links in a transaction, checked the repair,
  idempotency, historical data retention and unchanged verified flags,
  and rolled back the entire test.

## Required release sequence

1. Review the independent PR and CI; no merge without approval.
2. Deploy corrected code before any DB cleanup to prevent regression.
3. Inspect live AWS state via repair_golden_industry_codes.py
   (read-only by default).
4. Back up affected rows and obtain explicit approval for targeted
   J22/J24 link updates plus deactivating 17 test-only codes.
5. Verify active count 2916; Golden history still readable; recent
   judgments correctly reflect canonical codes. Cached exact E5
   queries may fall back to BM25 after a code change.

No AWS production data was changed in this work.
