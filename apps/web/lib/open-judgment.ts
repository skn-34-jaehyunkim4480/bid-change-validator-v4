import { findPreflightCasesByNotice, getNoticeVersions } from './api';
import { createPreflightCaseWithCompany, listCompanies } from './qualification-api';

/*
  공고 한 건의 판정 화면(참가자격 검토) 주소를 만든다(2026-10-13).
  AI Copilot 이 찾아 준 공고와 AI 추천 화면의 공고가 같은 길로 판정 화면에 간다 — 공고 찾기의 「검토 시작」과 같은 절차다:
  이 회사가 그 공고의 현재 차수로 만든 검토 건이 있으면 그것을 열고, 없으면 새로 만든다.
*/

/** 판정 화면을 열자마자 검토를 시작하게 하는 표시. app/qualification/page.tsx 가 읽고 지운다. */
export const AUTOSTART_PARAM = 'autostart';

export async function judgmentHref(noticeId: string, options: { bidNoticeNo?: string; autostart?: boolean } = {}): Promise<string> {
  const company = (await listCompanies())[0];
  if (!company) throw new Error('회사 프로필이 필요합니다. 회사 프로필을 먼저 만들어 주세요.');
  const versions = await getNoticeVersions(noticeId);
  const current = versions.find((item) => item.is_current) ?? versions[0];
  if (!current) throw new Error('현재 공고 버전을 찾지 못했습니다.');
  const known = await findPreflightCasesByNotice(noticeId, company.id);
  let caseId = known.items.find((item) => item.current_version_number === current.version_number)?.id;
  if (!caseId) {
    const baseline = versions
      .filter((item) => item.version_number < current.version_number)
      .sort((a, b) => b.version_number - a.version_number)[0];
    const created = await createPreflightCaseWithCompany({
      notice_id: noticeId,
      company_id: company.id,
      baseline_version_number: baseline?.version_number,
      current_version_number: current.version_number,
      title: `${options.bidNoticeNo ?? '공고'} 참가자격 검토`,
    });
    caseId = created.id;
  }
  return `/qualification?caseId=${encodeURIComponent(caseId)}${options.autostart ? `&${AUTOSTART_PARAM}=1` : ''}`;
}
