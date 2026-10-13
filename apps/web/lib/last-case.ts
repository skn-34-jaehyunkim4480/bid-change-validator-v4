import { ApiError, getPreflightCase } from './api';
import { listQualificationJudgments, runQualificationJudgment, type QualificationJudgmentRun } from './qualification-api';

/*
  마지막으로 보던 검토 건(2026-10-13).
  - 「내 입찰 건」으로 돌아오면 목록 대신 보던 공고를 다시 연다(app/qualification/page.tsx).
  - 회사 프로필을 저장하면 그 공고를 다시 판정한다(app/company/page.tsx).
  이 탭에서만 기억한다. 로그아웃하면 지운다.
*/
const KEY = 'bidcheck.last-case.v1';

export function rememberCase(caseId: string) {
  try { window.sessionStorage.setItem(KEY, caseId); } catch { /* 저장소를 못 쓰면 기억하지 않을 뿐이다 */ }
}

export function lastCaseId(): string | null {
  try { return window.sessionStorage.getItem(KEY); } catch { return null; }
}

export function forgetCase(caseId?: string) {
  try {
    if (!caseId || window.sessionStorage.getItem(KEY) === caseId) window.sessionStorage.removeItem(KEY);
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
