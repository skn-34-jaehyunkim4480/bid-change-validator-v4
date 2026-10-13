import { apiFetch, ApiError } from './api';

/*
  요금제와 멤버십 창(2026-10-13). 서버가 한도를 넘은 요청에 402 MEMBERSHIP_REQUIRED 를 주면
  어느 화면에서든 같은 창을 띄운다(components/membership-modal.tsx).
*/

export type MembershipKind = 'NOTICE_CHECK' | 'COPILOT_QUESTION';
export type PlanCode = 'FREE' | 'BASIC' | 'UNLIMITED';

export type MembershipPlan = {
  code: PlanCode;
  name: string;
  monthly_price: number;
  /** null 은 제한 없음. */
  notice_checks: number | null;
  copilot_questions: number | null;
};

export type Membership = {
  limited: boolean;
  plan: PlanCode;
  plan_name: string;
  period: string;
  expires_at: string | null;
  limits: { notice_checks: number | null; copilot_questions: number | null };
  used: { notice_checks: number | null; copilot_questions: number | null };
  plans: MembershipPlan[];
  demo_code_enabled: boolean;
};

export const MEMBERSHIP_REQUIRED = 'MEMBERSHIP_REQUIRED';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, { ...init, headers: { 'Content-Type': 'application/json' } });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(body?.error?.message ?? `요청에 실패했습니다. (${response.status})`, response.status, body?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<T>;
}

export const getMembership = () => request<Membership>('/api/v1/membership');

/** 멤버십 코드로 가입한다. 카드 정보는 보내지 않는다 — 서버에 그것을 받는 칸이 없다. */
export const subscribeWithCode = (plan: Exclude<PlanCode, 'FREE'>, membershipCode: string) =>
  request<Membership>('/api/v1/membership/subscribe', { method: 'POST', body: JSON.stringify({ plan, membership_code: membershipCode }) });

/** 창이 열려 있으면 그 이유(무엇의 한도를 넘었는가), 닫혀 있으면 null. */
let opened: MembershipKind | null = null;
const listeners = new Set<() => void>();

export const membershipModal = {
  subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
  get: () => opened,
  open: (kind: MembershipKind) => { opened = kind; listeners.forEach((listener) => listener()); },
  close: () => { opened = null; listeners.forEach((listener) => listener()); },
};

/** 한도를 넘어서 막힌 것이면 멤버십 창을 띄우고 true 를 돌려준다. */
export function openMembershipIfRequired(error: unknown, kind: MembershipKind): boolean {
  if (!(error instanceof ApiError) || error.code !== MEMBERSHIP_REQUIRED) return false;
  membershipModal.open(kind);
  return true;
}

export const won = (amount: number) => `${amount.toLocaleString('ko-KR')}원`;
