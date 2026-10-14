/*
  입찰 준비 지침서(2026-10-14). 판정이 끝난 공고를 고르면 서버가 "무엇을 어떤 순서로 준비할지" 를 정리해 준다.
  서버는 결과를 저장하지 않는다 — 만든 지침서는 이 브라우저에 계정·공고별로 둔다(다시 만들면 질문 한 번을 더 쓴다).
*/
import { ApiError, apiFetch } from './api.ts';
import type { JudgedCase, PrepGuide } from './prep-guide-view.ts';

export * from './prep-guide-view.ts';

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, { ...init, headers: { 'Content-Type': 'application/json' } });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `요청에 실패했습니다. (${response.status})`, response.status, payload?.error?.code ?? 'UNKNOWN');
  }
  return (await response.json()) as T;
}

export const listJudgedCases = () => read<JudgedCase[]>('/api/v1/prep-guides/cases');

export const createPrepGuide = (caseId: string) =>
  read<PrepGuide>(`/api/v1/prep-guides/cases/${encodeURIComponent(caseId)}`, {
    method: 'POST', body: JSON.stringify({ allow_external_processing: true }),
  });

const key = (userId: string, caseId: string) => `bidcheck.prep-guide.v1:${userId}:${caseId}`;

/** 이 브라우저에 둔 지침서. 없거나 읽을 수 없으면 null. */
export function savedGuide(userId: string, caseId: string): PrepGuide | null {
  try {
    const raw = window.localStorage.getItem(key(userId, caseId));
    const guide = raw ? (JSON.parse(raw) as PrepGuide) : null;
    return guide && Array.isArray(guide.evaluation_items) && Array.isArray(guide.steps) ? guide : null;
  } catch {
    return null;
  }
}

export function saveGuide(userId: string, guide: PrepGuide) {
  try {
    window.localStorage.setItem(key(userId, guide.case_id), JSON.stringify(guide));
  } catch {
    // 저장하지 못해도 화면에는 방금 만든 지침서가 보인다.
  }
}
