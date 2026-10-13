/** A separate, opt-in retrieval contract. Never treated as a trained ML result. */
import { isRecommendationResponse, type MlRecommendation } from './ml-recommendation-schema.ts';

export type MlExperimentalResponse = {
  experiment: 'offline_task_corpus_v1';
  query_strategy_used: 'industry_v1' | 'legacy';
  mode_requested: 'bm25' | 'e5_small' | 'hybrid_rrf';
  mode_used: 'bm25' | 'e5_small' | 'hybrid_rrf';
  fallback_used: boolean;
  fallback_reason: string | null;
  valid_live_candidates: number;
  indexed_live_candidates: number;
  live_title_fallback_candidates: number;
  stale_source_documents: number;
  retrieval_latency_ms: number;
  task_source_status: 'UNVERIFIED_NO_INDEPENDENT_ACCURACY';
  note: string;
  items: MlRecommendation[];
  needs_review_items: MlRecommendation[];
};

const MODES = new Set(['bm25', 'e5_small', 'hybrid_rrf']);
const nonNegativeInteger = (value: unknown) =>
  Number.isInteger(value) && (value as number) >= 0;

/** Validate all evidence and qualification fields using the production item schema,
 * without converting retrieval results into trained-ML metadata.
 */
export function isMlExperimentalResponse(value: unknown): value is MlExperimentalResponse {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  if (row.experiment !== 'offline_task_corpus_v1' ||
    !['industry_v1', 'legacy'].includes(row.query_strategy_used as string) ||
    !MODES.has(row.mode_requested as string) ||
    !MODES.has(row.mode_used as string) ||
    typeof row.fallback_used !== 'boolean' ||
    !(row.fallback_reason === null || typeof row.fallback_reason === 'string') ||
    !nonNegativeInteger(row.valid_live_candidates) ||
    !nonNegativeInteger(row.indexed_live_candidates) ||
    !nonNegativeInteger(row.live_title_fallback_candidates) ||
    !nonNegativeInteger(row.stale_source_documents) ||
    typeof row.retrieval_latency_ms !== 'number' ||
    !Number.isFinite(row.retrieval_latency_ms) || row.retrieval_latency_ms < 0 ||
    row.task_source_status !== 'UNVERIFIED_NO_INDEPENDENT_ACCURACY' ||
    typeof row.note !== 'string') return false;

  return isRecommendationResponse({
    model_version: null,
    dataset_version: null,
    scoring_source: 'lexical_fallback',
    input_sha256: null,
    fallback_used: row.fallback_used,
    fallback_reason: row.fallback_reason,
    total_valid_candidates: row.valid_live_candidates,
    note: row.note,
    items: row.items,
    needs_review_items: row.needs_review_items,
  });
}
