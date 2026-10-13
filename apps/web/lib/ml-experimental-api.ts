import { apiFetch, ApiError } from './api';
import { isMlExperimentalResponse, type MlExperimentalResponse } from './ml-experimental-schema';

export const EXPERIMENTAL_RECOMMENDATION_PATH = '/api/v1/recommendations/ml-experimental';

/** An explicit user action only: no automatic paid analysis, training, or writes. */
export async function listIndustryExperimentalRecommendations(companyId: string): Promise<MlExperimentalResponse> {
  const response = await apiFetch(EXPERIMENTAL_RECOMMENDATION_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ company_id: companyId, limit: 50, mode: 'bm25', query_strategy: 'industry_v1' }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    const message = response.status === 503
      ? '실험 검색은 서버에서 비활성 상태이거나 검색 데이터가 준비되지 않았습니다.'
      : payload?.detail ?? '실험 검색 조회에 실패했습니다. (' + response.status + ')';
    throw new ApiError(message, response.status, 'ML_EXPERIMENTAL_API_ERROR');
  }
  const data: unknown = await response.json();
  if (!isMlExperimentalResponse(data)) {
    throw new Error('실험 추천 API 응답이 현재 웹 계약과 일치하지 않습니다.');
  }
  if (data.query_strategy_used !== 'industry_v1') {
    throw new Error('서버가 업종 기반 검색 전략을 적용하지 않았습니다.');
  }
  return data;
}
