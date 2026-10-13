import test from 'node:test';
import assert from 'node:assert/strict';
import { isMlExperimentalResponse } from './ml-experimental-schema.ts';

const item = {
  notice_id: 'n1', title: '해외 연수', rank: 1, relevance_score: 2.13,
  reason: 'Keyword overlap', version_number: 1,
  analysis_run_id: null, analysis_version: null, analysis_status: 'UNKNOWN',
  qualification_state: 'UNKNOWN', qualification_reason: 'No verified current analysis',
  rule_version: null, is_stale: false, deadline_source: 'explicit', effective_deadline: null,
};
const response = {
  experiment: 'offline_task_corpus_v1', query_strategy_used: 'industry_v1',
  mode_requested: 'bm25', mode_used: 'bm25', fallback_used: true,
  fallback_reason: 'UNINDEXED_LIVE_TITLE_FALLBACK',
  valid_live_candidates: 3585, indexed_live_candidates: 347,
  live_title_fallback_candidates: 3238, stale_source_documents: 0,
  retrieval_latency_ms: 42, task_source_status: 'UNVERIFIED_NO_INDEPENDENT_ACCURACY',
  note: 'not independent accuracy', items: [], needs_review_items: [item],
};

void test('independent opt-in BM25 + industry_v1 response is validated', () => {
  assert.equal(isMlExperimentalResponse(response), true);
  assert.equal(isMlExperimentalResponse({ ...response, mode_used: 'trained_ml' }), false);
  assert.equal(isMlExperimentalResponse({ ...response, query_strategy_used: 'legacy' }), true);
  assert.equal(isMlExperimentalResponse({ ...response, valid_live_candidates: -1 }), false);
  assert.equal(isMlExperimentalResponse({ ...response, retrieval_latency_ms: Number.NaN }), false);
  assert.equal(isMlExperimentalResponse({ ...response, needs_review_items: [], items: [item] }), false);
  assert.equal(isMlExperimentalResponse({
    ...response, needs_review_items: [{ ...item, qualification_state: 'core_unmet' }],
  }), false);
  assert.equal(isMlExperimentalResponse({ ...response, task_source_status: 'VERIFIED' }), false);
});
