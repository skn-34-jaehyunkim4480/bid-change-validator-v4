import { ApiError, getPreflightCase } from './api';
import { listQualificationJudgments, runQualificationJudgment, type QualificationJudgmentRun } from './qualification-api';

/*
  마지막으로 보던 검토 건(2026-10-13).
  - 「내 입찰 건」으로 돌아오면 목록 대신 보던 공고를 다시 연다(app/qualification/page.tsx).
    다만 검토 건 목록을 보고 있었으면 목록으로 돌아온다(2026-10-14) — 목록을 보다 다른 탭에 다녀왔는데
    예전에 열었던 공고가 열리면 안 된다.
  - 회사 프로필을 저장하면 그 공고를 다시 판정한다(app/company/page.tsx).
  이 탭에서만 기억한다. 로그아웃하면 지운다.
*/
const KEY = 'bidcheck.last-case.v1';
const LIST_KEY = 'bidcheck.last-case-list.v1';

export function rememberCase(caseId: string) {
  try {
    window.sessionStorage.setItem(KEY, caseId);
    window.sessionStorage.removeItem(LIST_KEY);
  } catch { /* 저장소를 못 쓰면 기억하지 않을 뿐이다 */ }
}

/** 검토 건 목록을 보고 있다고 적어 둔다. 보던 공고는 지우지 않는다 — 프로필 저장 뒤 재판정이 그것을 쓴다. */
export function rememberList() {
  try { window.sessionStorage.setItem(LIST_KEY, '1'); } catch { /* 무시 */ }
}

/** 「내 입찰 건」으로 돌아왔을 때 다시 열 공고. 마지막에 목록을 보고 있었으면 null. */
export function returnCaseId(): string | null {
  try {
    return window.sessionStorage.getItem(LIST_KEY) ? null : window.sessionStorage.getItem(KEY);
  } catch { return null; }
}

export function lastCaseId(): string | null {
  try { return window.sessionStorage.getItem(KEY); } catch { return null; }
}

export function forgetCase(caseId?: string) {
  try {
    if (!caseId || window.sessionStorage.getItem(KEY) === caseId) window.sessionStorage.removeItem(KEY);
    if (!caseId) window.sessionStorage.removeItem(LIST_KEY);
  } catch { /* 무시 */ }
}

export type Rejudged =
  | { state: 'done'; caseId: string; title: string; overall: QualificationJudgmentRun['overall_status'] }
  | { state: 'failed'; caseId: string; title: string; message: string };

/**
 * 마지막으로 보던 공고를 바뀐 프로필로 다시 판정한다. 이미 판정한 적이 있는 건만 한다 — 저장된 분석을 다시 쓰므로
 * 모델을 부르지 않는다. 보던 공고가 없거나, 다른 회사의 건이거나, 아직 판정한 적이 없으면 null.
 */
export async function rejudgeLastCase(companyId: string): Promise<Rejudged | null> {
  const caseId = lastCaseId();
  if (!caseId) return null;
  let title = '';
  try {
    const caseItem = await getPreflightCase(caseId);
    if (caseItem.company_id !== companyId) return null;
    title = caseItem.notice_title || caseItem.title;
    const runs = await listQualificationJudgments(caseId);
    if (!runs.length) return null;
    const run = await runQualificationJudgment(caseId);
    return { state: 'done', caseId, title, overall: run.overall_status };
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) { forgetCase(caseId); return null; }
    if (!title) return null;
    return { state: 'failed', caseId, title, message: cause instanceof Error ? cause.message : '다시 판정하지 못했습니다.' };
  }
}
