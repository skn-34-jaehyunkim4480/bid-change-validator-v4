import { useEffect, useState, useSyncExternalStore } from 'react';
import { apiFetch, ApiError } from './api';

/*
  요금제와 멤버십 창(2026-10-13). 서버가 한도를 넘은 요청에 402 MEMBERSHIP_REQUIRED 를 주면
  어느 화면에서든 같은 창을 띄운다(components/membership-modal.tsx).
*/

export type MembershipKind = 'NOTICE_CHECK' | 'COPILOT_QUESTION' | 'GENERAL_QUESTION';
/** 일반 도우미의 한도를 물을 때 getMembership 에 주는 값(대화 id 와 같다). */
export const GENERAL_CHAT = 'general';
export type PlanCode = 'FREE' | 'BASIC' | 'UNLIMITED';

export type MembershipPlan = {
  code: PlanCode;
  name: string;
  monthly_price: number;
  /** null 은 제한 없음. */
  notice_checks: number | null;
  /** 공고 하나에서 물을 수 있는 횟수. */
  copilot_questions: number | null;
  /** 일반 도우미에 한 달 동안 물을 수 있는 횟수. */
  general_questions: number | null;
  /** 공고 대화와 일반 도우미를 합쳐 한 달 동안 물을 수 있는 횟수. 있으면 위 둘 대신 이것만 적용된다. */
  copilot_total: number | null;
};

/** 지금 대화에 적용되는 채팅 한도. NOTICE: 이 공고에서, GENERAL: 일반 도우미 한 달, TOTAL: 둘을 합쳐 한 달. */
export type ChatQuota = { scope: 'NOTICE' | 'GENERAL' | 'TOTAL'; limit: number | null; used: number };

export type Membership = {
  limited: boolean;
  plan: PlanCode;
  plan_name: string;
  period: string;
  expires_at: string | null;
  /** notice_checks 는 한 달에 확인할 수 있는 공고 수, copilot_questions 는 공고 대화 하나에서 물을 수 있는 횟수. */
  limits: { notice_checks: number | null; copilot_questions: number | null };
  /** copilot_questions 는 공고(caseId)를 준 조회에서만 채워진다. */
  used: { notice_checks: number | null; copilot_questions: number | null };
  plans: MembershipPlan[];
  /** 공고(caseId)나 일반 도우미를 준 조회에서만 채워진다. */
  chat?: ChatQuota | null;
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

/** caseId(공고 대화)나 GENERAL_CHAT(일반 도우미)을 주면 그 대화에 적용되는 채팅 한도(chat)도 함께 온다. */
export const getMembership = (caseId?: string) =>
  request<Membership>(`/api/v1/membership${!caseId ? '' : caseId === GENERAL_CHAT ? '?general=true' : `?case_id=${encodeURIComponent(caseId)}`}`);

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

/** 사용량이 바뀌었을 수 있을 때(검토 완료, 가입) 부르면 화면의 한도 표시가 다시 읽는다. */
let usageVersion = 0;
const usageListeners = new Set<() => void>();
export const membershipUsage = {
  subscribe: (listener: () => void) => { usageListeners.add(listener); return () => { usageListeners.delete(listener); }; },
  get: () => usageVersion,
  refresh: () => { usageVersion += 1; usageListeners.forEach((listener) => listener()); },
};

/** 지금 계정의 요금제와 사용량. 불러오기 전이거나 실패하면 null 이고, 그때는 한도 표시를 그리지 않는다. */
export function useMembership(caseId?: string, tick?: string | number): Membership | null {
  const version = useSyncExternalStore(membershipUsage.subscribe, membershipUsage.get, () => 0);
  const [value, setValue] = useState<Membership | null>(null);
  useEffect(() => {
    let alive = true;
    getMembership(caseId).then((next) => { if (alive) setValue(next); }).catch(() => { /* 표시만 생략한다 */ });
    return () => { alive = false; };
  }, [caseId, tick, version]);
  return value;
}

export const won = (amount: number) => `${amount.toLocaleString('ko-KR')}원`;
