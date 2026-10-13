import { expect, test, type Page } from '@playwright/test';
import { NOTICE_PAGE_SIZE } from '../lib/notice-pagination';

const mockUser = {
  id: 'local-user', username: 'e2e-user', role: 'viewer',
  company_id: null, company_name: null,
};

type MockOptions = { authenticated?: boolean; noticesFail?: boolean };

async function mockApi(page: Page, options: MockOptions = {}) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (pathname === '/api/v1/auth/me') {
      return route.fulfill(options.authenticated === false
        ? { status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'UNAUTHORIZED', message: '인증이 만료되었습니다.' } }) }
        : { status: 200, json: mockUser });
    }
    if (pathname === '/api/v1/auth/login') {
      return route.fulfill({ status: 401, json: { error: { code: 'INVALID_CREDENTIALS', message: '로그인 정보가 올바르지 않습니다.' } } });
    }
    if (pathname === '/api/v1/companies') {
      return route.fulfill({ status: 200, json: [] });
    }
    if (pathname === '/api/v1/notices') {
      if (options.noticesFail) {
        return route.fulfill({ status: 503, json: { error: { code: 'UPSTREAM_UNAVAILABLE', message: '일시적으로 공고를 조회할 수 없습니다.' } } });
      }
      const limit = Number(url.searchParams.get('limit') ?? 20);
      const offset = Number(url.searchParams.get('offset') ?? 0);
      const all = Array.from({ length: 101 }, (_, index) => ({
        id: 'notice-' + (index + 1),
        bid_notice_no: '2026-' + String(index + 1).padStart(4, '0'),
        title: '테스트 공고 ' + (index + 1),
        business_type: 'service',
        notice_kind: 'normal',
        announcing_institution_code: null,
        announcing_institution_name: '테스트 기관',
        demanding_institution_code: null,
        demanding_institution_name: null,
        first_seen_at: '2026-10-09T00:00:00',
        last_seen_at: '2026-10-09T00:00:00',
        current_version: 1,
        qualification_status: 'unreviewed',
        current_case_id: null,
      }));
      return route.fulfill({ status: 200, json: {
        total: all.length,
        items: all.slice(offset, offset + limit),
        status_counts: { core_met: 0, core_unmet: 0, unreviewed: 101, needs_review: 0 },
      } });
    }
    // No request can escape to a real backend or an AWS endpoint during local E2E.
    return route.fulfill({ status: 404, json: { error: { message: 'Local fixture not defined' } } });
  });
}

test('login: hydration-safe form shows invalid credentials and never sends a GET password', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/login');
  const submit = page.getByRole('button', { name: '로그인' });
  await expect(submit).toBeEnabled({ timeout: 15_000 });
  await page.getByLabel('아이디').fill('invalid');
  await page.getByLabel('비밀번호').fill('invalid');
  const loginRequest = page.waitForRequest(request => request.url().includes('/api/v1/auth/login') && request.method() === 'POST');
  await submit.click();
  await loginRequest;
  await expect(page.getByRole('alert')).toContainText('로그인 정보가 올바르지 않습니다.');
  expect(page.url()).not.toContain('password=');
});

test('login without JavaScript keeps submit disabled until hydration', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto('/login');
    await expect(page.getByRole('button', { name: '로그인' })).toBeDisabled();
  } finally {
    await context.close();
  }
});
test('usage guide lives at the bottom of the notice page and the guide tab is gone', async ({ page }) => {
  await mockApi(page);
  await page.goto('/notices');
  await expect(page.locator('nav.app-primary-nav')).toBeVisible();
  const guide = page.locator('#usage-guide');
  await expect(guide.getByRole('heading', { name: '이용 안내', level: 2 })).toBeVisible();
  await expect(guide.locator('ol > li')).toHaveCount(3);
  await expect(guide.getByRole('heading', { name: '이 서비스가 하지 않는 것' })).toBeVisible();
  // 이용안내 탭은 없다. 예전 주소로 들어가면 찾을 수 없는 화면이다.
  await expect(page.locator('nav.app-primary-nav a[href="/guide"]')).toHaveCount(0);
  const response = await page.goto('/guide');
  expect(response?.status()).toBe(404);
});

test('recommendations uses a rounded profile-style header and plain-language descriptions', async ({ page }) => {
  await mockApi(page);
  await page.goto('/recommendations');
  await expect(page.locator('.app-title-band')).toHaveCount(0);
  const hero = page.locator('.product-hero');
  await expect(hero).toHaveCount(1);
  await expect(hero).toHaveCSS('border-radius', '22px');
  await expect(hero.getByRole('heading', { name: 'AI 추천', level: 1 })).toBeVisible();
  await expect(hero.getByText('홈 › AI 추천')).toBeVisible();
  await expect(hero.getByText('우리 회사에 어울리는 입찰 공고를 찾아드립니다.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: '기업 맞춤 공고 추천' })).toBeVisible();
  await expect(page.getByText('BM25 기반 검색이며', { exact: false })).toHaveCount(0);
  for (const route of ['/qualification', '/company']) {
    await page.goto(route);
    await expect(page.locator('.app-title-band')).toHaveCount(0);
  }
});

test('qualification navigation opens latest case before the slow analysis results and skips unused notice list', async ({ page }) => {
  await mockApi(page);
  const caseItem = {
    id: 'case-e2e', company_id: null, notice_id: 'notice-e2e', bid_notice_no: '2026-5010',
    notice_title: '단계별 로딩 테스트 공고', title: '검토 테스트', status: 'READY',
    baseline_version_id: null, baseline_version_number: null,
    current_version_id: 'version-e2e', current_version_number: 1, documents: [],
    created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
  };
  let releaseAnalysis!: () => void;
  const analysisGate = new Promise<void>((resolve) => { releaseAnalysis = resolve; });
  const requests: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== 'GET') return route.fallback();
    if (path !== '/api/v1/auth/me') requests.push(path);
    if (path === '/api/v1/preflight-cases') return route.fulfill({ status: 200, json: { total: 1, limit: 100, offset: 0, items: [caseItem] } });
    if (path === '/api/v1/preflight-cases/case-e2e') return route.fulfill({ status: 200, json: caseItem });
    if (path === '/api/v1/notices/notice-e2e') return route.fulfill({ status: 200, json: { id: 'notice-e2e', title: caseItem.notice_title, announcing_institution_name: '테스트 기관' } });
    if (path === '/api/v1/notices/notice-e2e/versions') return route.fulfill({ status: 200, json: [{ id: 'version-e2e', version_number: 1, documents: [] }] });
    if (path === '/api/v1/notices/notice-e2e/versions/1/qualification-analyses') {
      await analysisGate;
      return route.fulfill({ status: 200, json: [] });
    }
    if (path === '/api/v1/preflight-cases/case-e2e/qualification-judgment-runs') return route.fulfill({ status: 200, json: [] });
    return route.fallback();
  });
  await page.goto('/recommendations');
  await page.locator('nav.app-primary-nav a[href="/qualification"]').click();
  await expect(page).toHaveURL(/\/qualification\?caseId=case-e2e$/);
  await expect(page.getByRole('heading', { name: '단계별 로딩 테스트 공고' })).toBeVisible();
  await expect(page.getByRole('status', { name: '검토 상세 불러오는 중' })).toBeVisible();
  expect(requests).not.toContain('/api/v1/notices');
  await expect(page.getByText('참가자격 검토 시작')).toHaveCount(0);
  releaseAnalysis();
  await expect(page.getByRole('status', { name: '검토 상세 불러오는 중' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '참가자격 검토 시작' }).first()).toBeVisible();

  // Cached case/notice/version GETs must survive same-session navigation.
  const cached = {
    case: requests.filter((url) => url === '/api/v1/preflight-cases/case-e2e').length,
    notice: requests.filter((url) => url === '/api/v1/notices/notice-e2e').length,
    versions: requests.filter((url) => url === '/api/v1/notices/notice-e2e/versions').length,
  };
  await page.locator('nav.app-primary-nav a[href="/recommendations"]').click();
  await page.locator('nav.app-primary-nav a[href="/qualification"]').click();
  await expect(page).toHaveURL(/\/qualification\?caseId=case-e2e$/);
  await expect(page.getByRole('button', { name: '참가자격 검토 시작' }).first()).toBeVisible();
  expect(requests.filter((url) => url === '/api/v1/preflight-cases/case-e2e')).toHaveLength(cached.case);
  expect(requests.filter((url) => url === '/api/v1/notices/notice-e2e')).toHaveLength(cached.notice);
  expect(requests.filter((url) => url === '/api/v1/notices/notice-e2e/versions')).toHaveLength(cached.versions);
});

test('cached notice list survives route round trip without another GET or empty-state flash', async ({ page }) => {
  let noticeGets = 0;
  let companyGets = 0;
  await mockApi(page);
  page.on('request', (request) => {
    const u = new URL(request.url());
    if (request.method() !== 'GET') return;
    if (u.pathname === '/api/v1/notices') noticeGets++;
    if (u.pathname === '/api/v1/companies') companyGets++;
  });
  await page.goto('/notices');
  await expect(page.getByText('2026-0001').first()).toBeVisible({ timeout: 20_000 });
  const before = { noticeGets, companyGets };
  expect(before.noticeGets).toBe(1);
  expect(before.companyGets).toBe(1);

  for (let index = 0; index < 3; index++) {
    await page.locator('nav.app-primary-nav a[href="/recommendations"]').click();
    await expect(page).toHaveURL(/\/recommendations$/);
    await page.locator('nav.app-primary-nav a[href="/notices"]').click();
    await expect(page).toHaveURL(/\/notices$/);
    await expect(page.getByText('2026-0001').first()).toBeVisible();
    await expect(page.getByLabel('?? ?? ???? ?')).toHaveCount(0);
  }
  expect(noticeGets).toBe(before.noticeGets);
  expect(companyGets).toBe(before.companyGets);
});

test('session expiration redirects safely to login', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/recommendations');
  await expect(page).toHaveURL(/\/login$/);
});

for (const width of [360, 768, 1440]) {
  test('authenticated shell and keyboard access at width ' + width, async ({ page }, testInfo) => {
    await mockApi(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/recommendations');
    await expect(page.getByRole('navigation', { name: '주요 메뉴' })).toBeVisible({ timeout: 15_000 });
    const skip = page.getByRole('link', { name: '본문으로 건너뛰기' });
    await skip.focus();
    await expect(skip).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main-content')).toBeFocused();
    const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(size.document).toBeLessThanOrEqual(size.viewport + 1);
    await page.screenshot({ path: testInfo.outputPath('recommendations-' + width + '.png'), fullPage: true });
  });
}

test('notice list traverses beyond the 100th result through server pagination', async ({ page }) => {
  await mockApi(page);
  const offsets: number[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/v1/notices?')) {
      offsets.push(Number(new URL(request.url()).searchParams.get('offset') ?? 0));
    }
  });
  await page.goto('/notices');
  await expect(page.getByText('테스트 공고 1', { exact: true })).toBeVisible();
  const next = page.getByRole('button', { name: '다음 페이지' });
  const pageCount = Math.ceil(101 / NOTICE_PAGE_SIZE);
  for (let i = 1; i < pageCount; i++) {
    await next.click();
    await expect(page.getByText((i + 1) + ' / ' + pageCount + ' 페이지')).toBeVisible();
  }
  await expect(page.getByText('테스트 공고 101', { exact: true })).toBeVisible();
  expect(offsets).toContain(100);
});

test('server errors show an actionable retry instead of false success', async ({ page }) => {
  await mockApi(page, { noticesFail: true });
  await page.goto('/notices');
  await expect(page.getByText('일시적으로 공고를 조회할 수 없습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: /다시 시도/ })).toBeEnabled();
});
test('primary BM25 recommendations load automatically, hide legacy fallback, group duplicates and page results', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/companies', (route) => route.fulfill({
    status: 200, json: [{ id: 'company-j20', name: '합성회사 J20' }],
  }));
  let legacyCalls = 0;
  await page.route('**/api/v1/recommendations/ml', (route) => {
    legacyCalls++;
    return route.fulfill({ status: 200, json: { items: [], needs_review_items: [] } });
  });
  const item = (number: number, title = '행사 운영 ' + number) => ({
    notice_id: 'notice-' + number, title, rank: number, relevance_score: 30 - number,
    reason: 'Model-generated text similarity; no directly matching keyword identified',
    version_number: 1, analysis_run_id: null, analysis_version: null, analysis_status: 'UNKNOWN',
    qualification_state: 'UNKNOWN', qualification_reason: 'No successful current-version analysis',
    rule_version: null, is_stale: false, deadline_source: 'explicit', effective_deadline: null,
  });
  const rows = [...Array.from({ length: 12 }, (_, i) => item(i + 1)), item(13, '행사 운영 1')];
  let actualSearchCalls = 0;
  await page.route('**/api/v1/recommendations/ml-experimental', (route) => {
    actualSearchCalls++;
    expect(route.request().postDataJSON()).toMatchObject({
      company_id: 'company-j20', limit: 50, mode: 'bm25', query_strategy: 'industry_v1',
    });
    return route.fulfill({ status: 200, json: {
      experiment: 'offline_task_corpus_v1', query_strategy_used: 'industry_v1',
      mode_requested: 'bm25', mode_used: 'bm25', fallback_used: true,
      fallback_reason: 'UNINDEXED_LIVE_TITLE_FALLBACK',
      valid_live_candidates: 3589, indexed_live_candidates: 344,
      live_title_fallback_candidates: 3245, stale_source_documents: 0,
      retrieval_latency_ms: 31, task_source_status: 'UNVERIFIED_NO_INDEPENDENT_ACCURACY',
      note: 'Not independently validated', items: [], needs_review_items: rows,
    } });
  });
  await page.goto('/recommendations');
  await expect(page.getByRole('heading', { name: '기업 맞춤 공고 추천' })).toBeVisible();
  await expect(page.getByText('현재 추천 대상으로 분류한 공고 3589건에서 찾았습니다.')).toBeVisible();
  await page.getByText('검색 범위 자세히 보기').click();
  await expect(page.getByText('공고명으로만 검색한 공고 3245건', { exact: false })).toBeVisible();
  await expect(page.getByText('참가자격: 확인 전', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('행사 운영 1', { exact: true })).toBeVisible();
  await expect(page.getByText('행사 운영 11', { exact: true })).toHaveCount(0);
  await expect(page.getByText('동일 제목의 다른 공고 1건', { exact: false })).toBeVisible();
  await expect(page.getByText('Model-generated text similarity', { exact: false })).toHaveCount(0);
  await expect(page.getByText('model_not_configured')).toHaveCount(0);
  expect(legacyCalls).toBe(0);
  expect(actualSearchCalls).toBe(1);
  await page.getByRole('button', { name: /더 보기/ }).click();
  await expect(page.getByText('행사 운영 11', { exact: true })).toBeVisible();
});

test('primary recommendations fail closed without showing legacy pseudo-recommendations', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/companies', (route) => route.fulfill({
    status: 200, json: [{ id: 'company-j20', name: '합성회사 J20' }],
  }));
  await page.route('**/api/v1/recommendations/ml-experimental', (route) => route.fulfill({
    status: 503, json: { detail: 'Artifacts not configured' },
  }));
  await page.goto('/recommendations');
  await expect(page.getByRole('heading', { name: '기업 맞춤 공고 추천' })).toBeVisible();
  await expect(page.locator('section[aria-labelledby="ml-experiment-heading"]').getByRole('alert')).toContainText('서버에서 비활성');
  await expect(page.getByText('학습 모델 미적용')).toHaveCount(0);
});

test('admin view denies non-admin and does not invoke mutations (MOCK)', async ({ page }) => {
  await mockApi(page);
  await page.goto('/admin');
  await expect(page.getByRole('alert')).toContainText('관리자만 접근할 수 있습니다.');
  await page.route('**/api/v1/auth/me', route => route.fulfill({
    status: 200, json: { ...mockUser, role: 'SYSTEM_ADMIN' },
  }));
  await page.route('**/api/v1/admin/history-jobs?*', route => route.fulfill({ status: 200, json: [] }));
  await page.route('**/api/v1/admin/processing-jobs?*', route => route.fulfill({ status: 200, json: [] }));
  await page.route('**/api/v1/admin/relevance-labels?*', route => route.fulfill({ status: 200, json: [] }));
  const writes: string[] = [];
  page.on('request', request => {
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.method());
  });
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: '공고 이력 수집 작업' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '공고 차수별 처리 작업' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '기업–공고 연관성 사람 검수' })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('임베딩·LLM 워커는 기본 비활성');
  expect(writes).toEqual([]);
});

test('notice detail renders empty original instead of pretending extraction succeeded (MOCK)', async ({ page }) => {
  await mockApi(page);
  const notice = {
    id: 'notice-a', bid_notice_no: '2026-1', title: '테스트 공고 상세',
    announcing_institution_name: '기관', demanding_institution_name: null,
    current_version: 1, latest: {
      id: 'v1', version_number: 1, is_current: true, bid_closed_at: null, documents: [],
    },
  };
  await page.route('**/api/v1/notices/notice-a', route => route.fulfill({ status: 200, json: notice }));
  await page.route('**/api/v1/notices/notice-a/versions', route => route.fulfill({ status: 200, json: [notice.latest] }));
  await page.goto('/notices/notice-a');
  await expect(page.getByRole('heading', { name: '테스트 공고 상세' })).toBeVisible();
  await expect(page.getByText('해당 버전의 첨부 원문이 없습니다.')).toBeVisible();
});
test('seven existing product routes remain reachable with local API mocks', async ({ page }) => {
  await mockApi(page);
  for (const route of ['/notices', '/qualification', '/ask-back', '/evidence', '/evaluation', '/changes', '/company']) {
    await page.goto(route);
    await expect(page.locator('#main-content')).toBeVisible();
    await expect(page.getByRole('navigation', { name: '주요 메뉴' })).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(new RegExp(route.replace('/', '\\/') + '$'));
  }
});
test('Copilot never submits a question without a selected case (MOCK)', async ({ page }) => {
  await mockApi(page);
  const mutations: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/v1/copilot') && request.method() !== 'GET') mutations.push(request.url());
  });
  await page.goto('/qualification');
  await page.getByRole('button', { name: /AI Copilot/ }).click();
  await expect(page.getByRole('dialog', { name: 'AI Copilot' })).toBeVisible();
  await expect(page.getByRole('button', { name: '질문 보내기' })).toBeDisabled();
  expect(mutations).toEqual([]);
});

test('admin navigation does not overflow narrow mobile view (MOCK)', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/auth/me', route => route.fulfill({
    status: 200, json: { ...mockUser, role: 'SYSTEM_ADMIN' },
  }));
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: '운영 작업 관리' })).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(361);
});
test('recommendations and admin reuse AppShell session without duplicate auth checks', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/auth/me', route => route.fulfill({
    status: 200, json: { ...mockUser, role: 'SYSTEM_ADMIN' },
  }));
  let authChecks = 0;
  let documentLoads = 0;
  const errors: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/v1/auth/me') authChecks++;
    if (request.resourceType() === 'document') documentLoads++;
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/notices');
  await expect(page.locator('nav.app-primary-nav a[href="/admin"]')).toBeVisible();
  await expect.poll(() => authChecks).toBe(1);
  await page.evaluate(() => { (window as Window & { __authStateProof?: string }).__authStateProof = 'kept'; });
  const initialDocuments = documentLoads;
  for (let index = 0; index < 5; index++) {
    for (const pathname of ['/recommendations', '/admin', '/notices']) {
      await page.locator('nav.app-primary-nav a[href="' + pathname + '"]').click();
      await expect(page).toHaveURL(new RegExp(pathname + '$'));
    }
  }
  expect(await page.evaluate(() => (window as Window & { __authStateProof?: string }).__authStateProof)).toBe('kept');
  expect(documentLoads).toBe(initialDocuments);
  expect(authChecks).toBe(1);
  expect(errors).toEqual([]);
});
test('client navigation preserves document and avoids repeated auth checks', async ({ page }) => {
  let authChecks = 0;
  let documentLoads = 0;
  await mockApi(page);
  page.on('request', request => {
    if (request.resourceType() === 'document') documentLoads++;
    if (new URL(request.url()).pathname === '/api/v1/auth/me') authChecks++;
  });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));

  await page.goto('/recommendations');
  await expect(page.locator('nav.app-primary-nav')).toBeVisible();
  await page.evaluate(() => { (window as Window & { __navigationProof?: string }).__navigationProof = 'kept'; });
  const initialDocuments = documentLoads;

  for (let index = 0; index < 20; index++) {
    const pathname = index % 2 ? '/recommendations' : '/notices';
    await page.locator(`nav.app-primary-nav a[href="${pathname}"]`).click();
    await expect(page).toHaveURL(new RegExp(`${pathname}$`));
  }
  await page.goBack();
  await page.goForward();
  await expect(page).toHaveURL(/\/recommendations$/);

  expect(await page.evaluate(() => (window as Window & { __navigationProof?: string }).__navigationProof))
    .toBe('kept');
  expect(documentLoads).toBe(initialDocuments);
  expect(authChecks).toBe(1);
  expect(errors).toEqual([]);
});
