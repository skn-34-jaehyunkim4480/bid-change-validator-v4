import { apiFetch, ApiError } from '@/lib/api';
import type { CompanyProfile } from '@/lib/qualification-api';
import { invalidateSharedData } from '@/lib/shared-query-cache';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `요청에 실패했습니다. (${response.status})`, response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  // 실적·인증을 바꾸면 회사 프로필 조회(캐시 90초)가 낡는다. 비우지 않으면 추가·수정·삭제가 화면에 바로 나타나지 않는다.
  if (init?.method && !['GET', 'HEAD'].includes(init.method.toUpperCase())) invalidateSharedData();
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type PerformancePayload = {
  name: string;
  client_name?: string;
  amount: number;
  started_at?: string;
  completed_at: string;
  description?: string;
  fields?: string[];
  verified?: boolean;
};

export type CertificationPayload = {
  name: string;
  /** 공고가 번호로 요구하는 값(예: 직접생산확인의 세부품명번호 10자리). 판정에 쓰인다. */
  certification_code?: string;
  /** 증명서에 적힌 발급 번호. 기록용이고 판정에는 쓰이지 않는다. */
  certificate_number?: string;
  issuer_name?: string;
  issued_at?: string;
  expires_at?: string;
  verified?: boolean;
};

export function createPerformance(companyId: string, payload: PerformancePayload) {
  return request<CompanyProfile['performances'][number]>(`/api/v1/companies/${companyId}/performances`, { method: 'POST', body: JSON.stringify(payload) });
}

export function updatePerformance(companyId: string, performanceId: string, payload: Partial<PerformancePayload>) {
  return request<CompanyProfile['performances'][number]>(`/api/v1/companies/${companyId}/performances/${performanceId}`, { method: 'PATCH', body: JSON.stringify(payload) });
}

export function deletePerformance(companyId: string, performanceId: string) {
  return request<void>(`/api/v1/companies/${companyId}/performances/${performanceId}`, { method: 'DELETE' });
}

export function createCertification(companyId: string, payload: CertificationPayload) {
  return request<CompanyProfile['certifications'][number]>(`/api/v1/companies/${companyId}/certifications`, { method: 'POST', body: JSON.stringify(payload) });
}

export function updateCertification(companyId: string, certificationId: string, payload: Partial<CertificationPayload>) {
  return request<CompanyProfile['certifications'][number]>(`/api/v1/companies/${companyId}/certifications/${certificationId}`, { method: 'PATCH', body: JSON.stringify(payload) });
}

export function deleteCertification(companyId: string, certificationId: string) {
  return request<void>(`/api/v1/companies/${companyId}/certifications/${certificationId}`, { method: 'DELETE' });
}
