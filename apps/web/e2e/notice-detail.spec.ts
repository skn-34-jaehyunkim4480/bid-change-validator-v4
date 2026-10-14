import { expect, test, type Page } from '@playwright/test';

const noticeId = 'b544cef4-b9f0-46e2-a059-2616f26db4c6';
const caseId = '0aa365e2-e8b0-486f-83b0-cda45444ddab';
const companyId = 'j13-company';
const latestDocument = {
  id: 'j13-excel', document_order: 3,
  name: '중간처리 내역서.xlsx', viewer_type: 'DOWNLOAD',
  extraction_status: 'UNSUPPORTED', extracted_char_count: null,
  render_source_url: '/api/v1/notices/' + noticeId + '/versions/1/documents/j13-excel/source',
  text_url: '/api/v1/notices/' + noticeId + '/versions/1/documents/j13-excel/text',
  preview_url: null, file_size_bytes: 31007,
};
const version1 = {
  id: 'j13-v1', version_number: 1, bid_notice_order: '00', is_current: true,
  notice_kind: 'NORMAL', registration_type: null, is_reannouncement: false,
  posted_at: '2026-10-10T00:00:00Z', changed_at: null,
  bid_started_at: null, bid_closed_at: '2026-10-16T01:00:00Z',
  opened_at: null, allocated_budget: null, estimated_price: null,
  contract_method: null, change_reason: null, detail_url: null,
  collected_at: '2026-10-10T00:00:00Z', documents: [latestDocument],
};
const notice = {
  id: noticeId, bid_notice_no: 'R26BK01766092',
  title: '울산삼일고등학교 본관교사동 건설폐기물 중간처리 용역',
  business_type: 'SERVICE', announcing_institution_name: '울산삼일고등학교',
  demanding_institution_name: '울산삼일고등학교',
  current_version: 1, latest: version1,
};

async function setupNotice(page: Page, versions = [version1]) {
  const caseQueries: string[] = [];
  const createdCases: string[] = [];
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === 'POST' && path === '/api/v1/preflight-cases') {
      createdCases.push(path);
      return route.fulfill({ status: 201, json: { id: caseId } });
    }
    if (path === '/api/v1/auth/me') {
      return route.fulfill({ status: 200, json: {
        id: 'j13-user', username: 'golden-j13', company_id: companyId,
        company_name: '합성회사 J13', role: 'viewer',
      } });
    }
    if (path === '/api/v1/notices/' + noticeId) return route.fulfill({ status: 200, json: {
      ...notice, current_version: versions.at(-1)?.version_number ?? 1,
      latest: versions.at(-1) ?? version1,
    } });
    if (path === '/api/v1/notices/' + noticeId + '/versions') {
      return route.fulfill({ status: 200, json: versions });
    }
    if (path === '/api/v1/companies') return route.fulfill({ status: 200, json: [{ id: companyId, name: '합성회사 J13' }] });
    if (path === '/api/v1/preflight-cases') {
      caseQueries.push(url.search);
      return route.fulfill({ status: 200, json: { total: 1, limit: 100, offset: 0, items: [{
        id: caseId, notice_id: noticeId, company_id: companyId,
        current_version_number: versions.at(-1)?.version_number ?? 1, status: 'DRAFT',
      }] } });
    }
    return route.fulfill({ status: 404, json: { error: { message: 'fixture only' } } });
  });
  return { caseQueries, createdCases };
}

test('J13: the detail page opens the matching case and shows no change link for v1', async ({ page }) => {
  const { caseQueries, createdCases } = await setupNotice(page);
  await page.goto('/notices/' + noticeId);
  await expect(page.getByRole('heading', { name: notice.title })).toBeVisible();
  await expect(page.getByText('변경 이력 없음 (최초 공고)')).toBeVisible();
  await expect(page.getByRole('link', { name: '변경공고 확인' })).toHaveCount(0);
  await expect(page.getByText('이 파일은 화면 미리보기를 지원하지 않습니다.')).toBeVisible();
  await expect(page.getByRole('link', { name: '원본 파일 열기' })).toHaveAttribute('href', /j13-excel\/source$/);
  await page.getByRole('button', { name: '참가자격 검토 열기' }).click();
  await expect(page).toHaveURL(new RegExp('/qualification\\?caseId=' + caseId + '$'));
  expect(caseQueries.some(query => query.includes('notice_id=' + noticeId) && query.includes('company_id=' + companyId))).toBe(true);
  expect(createdCases).toHaveLength(0);
});

test('change button supplies caseId for notices with two versions', async ({ page }) => {
  const version2 = { ...version1, id: 'j13-v2', version_number: 2, is_current: true, documents: [] };
  await setupNotice(page, [{ ...version1, is_current: false }, version2]);
  await page.goto('/notices/' + noticeId);
  await expect(page.getByRole('button', { name: '변경공고 확인' })).toBeVisible();
  await page.getByRole('button', { name: '변경공고 확인' }).click();
  await expect(page).toHaveURL(new RegExp('/changes\\?caseId=' + caseId + '$'));
});
