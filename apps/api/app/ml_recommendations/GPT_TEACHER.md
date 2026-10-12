# GPT Teacher — isolated local agreement experiment

This is NOT a human-reviewed or production training path. It tests whether
existing rankers can mimic explicit GPT Teacher 0–3 *business relevance*
judgments for synthetic J01–J32 companies and public notice metadata.
It cannot decide qualification or change the existing Rule Engine, API,
Champion Registry, or AWS service.

## Provenance, data, security

Input is an immutable local snapshot.json and separately GPT-authored private
annotations.jsonl. No code in this workflow generates labels. The annotations
bind company ID, notice/version ID, 0–3 grade (or held), direct written
rationale, source gpt_teacher, teacher model, fixed split and SHA256 fingerprint
of the complete company and notice records. Confidence may be null and is
never a probability. Input drift, duplicate pairs, missing provenance or
rationale, company cross-split and confirmed notice-family overlap fail closed.

Keep the input snapshot, raw GPT annotations, pairs.jsonl, teacher_labels.jsonl,
manifest, MLflow SQLite DB, model weights and comparisons OUTSIDE GIT.
No paid LLM/API calls, AWS writes, deployments or automatic Champion selection.

## Commands from repository root

Configure PYTHONPATH for apps/api and engine in the terminal first.
All PRIVATE_DIR paths are outside the Git worktree.

~~~powershell
py -m app.ml_recommendations.gpt_teacher --snapshot PRIVATE_DIR\snapshot.json --annotations PRIVATE_DIR\annotations.jsonl --out PRIVATE_DIR\dataset
py -m app.ml_recommendations.trainer --dataset PRIVATE_DIR\dataset\pairs.jsonl --out PRIVATE_DIR\models --seed 42 --epochs 2 --device cpu --mlflow-local
py -m app.ml_recommendations.gpt_teacher_eval --dataset PRIVATE_DIR\dataset\pairs.jsonl --models PRIVATE_DIR\models --out PRIVATE_DIR\comparison.json
~~~

The resulting manifest forces human_reviewed_labels=0, reviewed_labels=0,
champion_eligible=false. Never pass these labels into human_training,
review, or Registry approval.

## Initial evidence and mandatory caveats (2026-10-13)

The frozen snapshot has 32 synthetic companies and 383 active-at-snapshot
public notices; 100 directly judged pairs of 10 selected synthetic companies
form train/validation/test 60/20/20, graded 0/1/2/3 = 34/21/19/26.
Company and confirmed-family split disjointness PASS.
The snapshot contains notice TITLES, not full task/attachment contents.
There is no verified GLM qualification analysis in this experiment.

Strict chronological partitioning FAILS because dates concentrate on
2026-10-12. There are only two test-company queries with ten candidates each:
Precision@10 cannot distinguish ranking algorithms; Recall@20=1.0 is
tautological. The dataset's positive prevalence gives Precision@10 a
maximum of 0.45 even under perfect ordering. Hence any 0.90 performance
claim is BLOCKED. nDCG/MRR are illustrative only.

For credible validation: get more independent companies, at least 20 heldout
test queries, >20 GPT-judged candidates per query, temporal holdout spanning
different days, full notice tasks, independent human review and class-balanced
evaluation. Business relevance must stay separate from Rule Engine eligibility.
