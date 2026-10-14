'use client';

import { useEffect, useMemo, useState } from 'react';
import { cachedGet } from '@/lib/shared-query-cache';
import {
  AlertCircle,
  Building2,
  Check,
  FileBadge2,
  LoaderCircle,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from 'lucide-react';

import { ProcurementLookup } from '@/components/product/procurement-lookup';
import { EMPTY_RECORDS_DRAFT, ProfileRecordsManager, recordsDraftCount, type RecordsDraft } from '@/components/product/profile-records-manager';
import { NavigationLink } from '@/components/navigation-link';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { COMPANY_REGION_OPTIONS, regionByCode, selectedRegionCode } from '@/lib/company-regions';
import { rejudgeLastCase, type Rejudged } from '@/lib/last-case';
import { createCertification, createPerformance, deleteCertification, deletePerformance, updateCertification, updatePerformance } from '@/lib/profile-records-api';
import { COMPANY_SIZE_LABEL, OVERALL_STATUS_BADGE, REQUIREMENT_TYPE_LABEL, labelOf } from '@/lib/status-copy';
import {
  createCompany,
  listCompanies,
  resetCompanyProfile,
  searchIndustryCodes,
  updateCompany,
  type CompanyCreatePayload,
  type CompanyProfile,
  type CompanySize,
  type MasterCode,
  type ProcurementCompany,
} from '@/lib/qualification-api';

type Busy = 'load' | 'create' | 'save' | null;

type CompanyBasics = {
  region_code: string;
  region_name: string;
  company_size: CompanySize;
  staff_total: string;
};

function basicsOf(company: CompanyProfile): CompanyBasics {
  return {
    region_code: company.region_code ?? '',
    region_name: company.region_name ?? '',
    company_size: company.company_size,
    // 인력 정보가 아예 없는 회사와 0명인 회사는 다르다. 없으면 빈 칸으로 두고 저장할 때만 보낸다.
    staff_total: company.staff ? String(company.staff.total_count) : '',
  };
}

function companyRows(company: CompanyProfile) {
  const performanceTotal = company.performances.reduce((sum, item) => sum + item.amount, 0);
  return [
    {
      label: '업종 코드',
      form: '#industry-manager' as string | null,
      value: company.industries.length
        ? company.industries.map((item) => `${item.code} · ${item.name}`).join(', ')
        : '비어 있음 · 판정하지 않습니다',
      source: company.industries.length ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'INDUSTRY',
    },
    {
      label: '소재지',
      form: '#company-basics' as string | null,
      value: company.region_name || company.region_code || '비어 있음 · 판정하지 않습니다',
      source: company.region_name || company.region_code ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'REGION',
    },
    {
      label: '기업 구분',
      form: '#company-basics' as string | null,
      value: COMPANY_SIZE_LABEL[company.company_size],
      source: '회사 입력',
      updated: company.updated_at,
      use: 'COMPANY_SIZE',
    },
    {
      label: '상시 근로자 수',
      form: '#company-basics' as string | null,
      value: company.staff ? `${company.staff.total_count.toLocaleString()}명` : '비어 있음 · 판정하지 않습니다',
      source: company.staff ? '회사 입력' : '없음',
      updated: company.updated_at,
      use: 'STAFF',
    },
    {
      label: '최근 수행 실적 건수',
      form: '#profile-performance',
      // 「0건」은 회사가 신고한 사실이 아니라 우리가 아직 받지 못했다는 뜻이다.
      value: company.performances.length ? `${company.performances.length}건` : '비어 있음 · 판정하지 않습니다',
      source: company.performances.length ? '회사 입력' : '없음',
      updated: company.performances[0]?.updated_at ?? company.updated_at,
      use: 'PERFORMANCE_COUNT',
    },
    {
      label: '최근 수행 실적 금액',
      form: '#profile-performance',
      value: company.performances.length ? `합계 ${performanceTotal.toLocaleString()}원` : '비어 있음 · 판정하지 않습니다',
      source: company.performances.length ? '회사 입력' : '없음',
      updated: company.performances[0]?.updated_at ?? company.updated_at,
      use: 'PERFORMANCE_AMOUNT',
    },
    {
      label: '인증 · 등록',
      form: '#profile-certification',
      value: company.certifications.length
        ? company.certifications.map((item) => item.name).join(', ')
        : '비어 있음 · 판정하지 않습니다',
      source: company.certifications.length ? '회사 입력' : '없음',
      updated: company.certifications[0]?.updated_at ?? company.updated_at,
      use: 'REGISTRATION_CERTIFICATION',
    },
  ];
}

export default function CompanyPage() {
  const [companies, setCompanies] = useState<CompanyProfile[]>(() => cachedGet<CompanyProfile[]>('/api/v1/companies') ?? []);
  const [selectedId, setSelectedId] = useState(() => cachedGet<CompanyProfile[]>('/api/v1/companies')?.[0]?.id ?? '');
  const [busy, setBusy] = useState<Busy>(() => cachedGet('/api/v1/companies') ? null : 'load');
  const [error, setError] = useState('');
  const [industryQuery, setIndustryQuery] = useState('');
  const [industryOptions, setIndustryOptions] = useState<MasterCode[]>([]);
  // 검색 결과는 처음에 6개만 보이고, 「더보기」를 누르면 펼쳐져 상자 안에서 넘겨 본다(2026-10-14).
  const [industryTotal, setIndustryTotal] = useState(0);
  const [industryExpanded, setIndustryExpanded] = useState(false);
  const shownIndustryOptions = industryExpanded ? industryOptions : industryOptions.slice(0, INDUSTRY_PREVIEW);
  // 저장 전 업종 목록. null이면 「서버 값 그대로」라는 뜻이고, 배열이면 편집 중이다.
  const [industryDraft, setIndustryDraft] = useState<Array<{ code: string; name: string }> | null>(null);
  // 소재지·기업 구분·상시 근로자. 업종과 같은 규칙 — null이면 「서버 값 그대로」다.
  const [basicsDraft, setBasicsDraft] = useState<CompanyBasics | null>(null);
  // 수행 실적·인증의 추가·삭제·증빙 표시도 초안이다. 「변경 사항 저장」 한 번에 함께 저장한다(2026-10-13).
  const [recordsDraft, setRecordsDraft] = useState<RecordsDraft>(EMPTY_RECORDS_DRAFT);
  // 조달청 조회로 받은 사업자등록번호(회사에 번호가 없을 때만). 저장할 때 함께 넣는다.
  const [numberDraft, setNumberDraft] = useState<string | null>(null);
  // 저장 뒤에 방금까지 보던 공고를 다시 판정한 결과.
  const [saved, setSaved] = useState<{ rejudged: Rejudged | null; reset?: boolean } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [form, setForm] = useState({
    name: '',
    business_registration_number: '',
    region_code: '11',
    region_name: '서울특별시',
    company_size: 'SMALL' as CompanySize,
    staff_total: '8',
  });

  // 회사를 처음 만들 때 고른 업종. 검색해서 직접 고른 것과 조달청에서 불러온 것이 한 목록에 모인다(2026-10-14).
  // 예전에는 목록의 첫 업종이 말없이 골라져 있었고 하나만 고를 수 있어, 고르지 않은 업종으로 회사가 만들어졌다.
  const [createIndustries, setCreateIndustries] = useState<Array<{ code: string; name: string }>>([]);

  const company = useMemo(
    () => companies.find((item) => item.id === selectedId) ?? companies[0] ?? null,
    [companies, selectedId],
  );

  const rows = company ? companyRows(company) : [];
  const filledRows = rows.filter((row) => !row.value.startsWith('비어 있음')).length;
  const missingRows = rows.filter((row) => row.value.startsWith('비어 있음'));

  const savedIndustries = company?.industries.map(({ code, name }) => ({ code, name })) ?? [];
  const industryList = industryDraft ?? savedIndustries;
  // 백엔드가 코드 오름차순으로 돌려주므로, 넣은 순서가 달라도 같은 집합이면 변경이 아니다.
  const industryDirty =
    industryDraft !== null &&
    industryList.map((item) => item.code).sort().join('|') !==
      savedIndustries.map((item) => item.code).sort().join('|');

  function addIndustry(item: MasterCode) {
    setIndustryDraft((draft) => {
      const base = draft ?? savedIndustries;
      if (base.some((row) => row.code === item.code)) return base;
      return [...base, { code: item.code, name: item.name }];
    });
  }

  function removeIndustry(code: string) {
    setIndustryDraft((draft) => (draft ?? savedIndustries).filter((row) => row.code !== code));
  }

  const savedBasics = company ? basicsOf(company) : null;
  const basics = basicsDraft ?? savedBasics;
  const basicsDirty =
    basicsDraft !== null && savedBasics !== null &&
    JSON.stringify(basicsDraft) !== JSON.stringify(savedBasics);

  function editBasics(patch: Partial<CompanyBasics>) {
    // savedBasics 가 없으면 아직 회사를 못 불러온 상태다. 그때는 편집 UI 자체가 안 뜬다.
    if (!savedBasics) return;
    setBasicsDraft((draft) => ({ ...(draft ?? savedBasics), ...patch }));
  }

  /*
    백엔드 PATCH /companies/{id} 가 받아주지 않는 상태를 저장 전에 막는다.
    누르고 나서 422를 보여주는 것보다, 누르기 전에 왜 안 되는지 말하는 편이 낫다.

    - industry_codes: []        → 스키마가 거부한다 (at least one code)
    - 소재지: 공식 시·도 선택 시 지역명과 코드가 항상 쌍으로 변경된다.
    - 과거 코드/세부 주소가 있는 기존 회사는 사용자가 지역을 바꾸지 않으면 그대로 보존한다.
    - 인력 입력이 비어 있으면 기존 DB 값을 덮어쓰지 않는다.
  */
  const industryBlock =
    industryList.length === 0 ? '업종은 최소 1개가 필요합니다. 하나는 남겨 주세요.' : null;

  const basicsBlock = (() => {
    if (!basics || !savedBasics) return null;
    const changedRegion = basics.region_code !== savedBasics.region_code || basics.region_name !== savedBasics.region_name;
    if (changedRegion && !selectedRegionCode(basics.region_code, basics.region_name)) {
      return '목록에서 소재지를 다시 선택해 주세요.';
    }
    if (savedBasics.staff_total.trim() && !basics.staff_total.trim()) {
      return '이미 저장된 상시 근로자 수는 화면에서 지울 수 없습니다. 다른 인원으로 바꾸는 것은 됩니다.';
    }
    return null;
  })();

  const dirtyCount = (industryDirty ? 1 : 0) + (basicsDirty ? 1 : 0) + (numberDraft ? 1 : 0) + recordsDraftCount(recordsDraft);
  const saveBlock = (industryDirty ? industryBlock : null) ?? (basicsDirty ? basicsBlock : null);

  function discardAll() {
    setIndustryDraft(null);
    setBasicsDraft(null);
    setRecordsDraft(EMPTY_RECORDS_DRAFT);
    setNumberDraft(null);
  }

  /** 업종·기본 정보·실적·인증의 바뀐 것을 한 번에 저장하고, 방금까지 보던 공고를 바뀐 프로필로 다시 판정한다. */
  async function saveAll() {
    if (!company || !dirtyCount || saveBlock) return;
    setBusy('save');
    setError('');
    setSaved(null);
    // 실적·인증은 건마다 요청이 나간다. 끝난 것은 초안에서 빼 두어, 중간에 실패해도 다시 저장할 때 두 번 들어가지 않게 한다.
    const left: RecordsDraft = {
      addPerformances: [...recordsDraft.addPerformances], addCertifications: [...recordsDraft.addCertifications],
      removePerformanceIds: [...recordsDraft.removePerformanceIds], removeCertificationIds: [...recordsDraft.removeCertificationIds],
      verified: { ...recordsDraft.verified },
    };
    let companySaved = false;
    try {
      const payload: Partial<CompanyCreatePayload> = {};
      if (industryDirty) payload.industry_codes = industryList.map((item) => item.code);
      if (basicsDirty && basics) {
        payload.company_size = basics.company_size;
        // Explicit selection sets both fields together. Unchanged legacy addresses stay untouched.
        if (basics.region_code !== savedBasics?.region_code || basics.region_name !== savedBasics?.region_name) {
          payload.region_code = basics.region_code;
          payload.region_name = basics.region_name;
        }
        // 빈 칸이면 인력 정보를 건드리지 않는다. 0으로 덮으면 「0명임을 확인했다」가 되어 판정이 달라진다.
        if (basics.staff_total.trim()) {
          payload.staff = {
            total_count: Number(basics.staff_total),
            verified: company.staff?.verified ?? false,
            roles: company.staff?.roles ?? [],
          };
        }
      }
      if (numberDraft) payload.business_registration_number = numberDraft;
      if (Object.keys(payload).length) await updateCompany(company.id, payload);
      companySaved = true;
      while (left.addPerformances.length) { await createPerformance(company.id, left.addPerformances[0]); left.addPerformances.shift(); }
      while (left.addCertifications.length) { await createCertification(company.id, left.addCertifications[0]); left.addCertifications.shift(); }
      for (const [key, verified] of Object.entries(left.verified)) {
        const id = key.slice(2);
        // 지우기로 한 항목의 증빙 표시는 저장할 필요가 없다.
        if (key.startsWith('p:') && !left.removePerformanceIds.includes(id)) await updatePerformance(company.id, id, { verified });
        if (key.startsWith('c:') && !left.removeCertificationIds.includes(id)) await updateCertification(company.id, id, { verified });
        delete left.verified[key];
      }
      while (left.removePerformanceIds.length) { await deletePerformance(company.id, left.removePerformanceIds[0]); left.removePerformanceIds.shift(); }
      while (left.removeCertificationIds.length) { await deleteCertification(company.id, left.removeCertificationIds[0]); left.removeCertificationIds.shift(); }
      setCompanies(await listCompanies());
      discardAll();
      setSaved({ rejudged: await rejudgeLastCase(company.id) });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필 저장에 실패했습니다.');
      // 저장된 데까지는 화면에 반영하고, 남은 것만 초안으로 둔다.
      if (companySaved) { setIndustryDraft(null); setBasicsDraft(null); setNumberDraft(null); }
      setRecordsDraft(left);
      await listCompanies().then(setCompanies).catch(() => { /* 목록은 다음 조회 때 맞춘다 */ });
    } finally {
      setBusy(null);
    }
  }

  /** 프로필 초기화: 수행 실적·인증·인력·사업자등록번호를 비운다. 끝나면 보던 공고를 다시 판정한다(저장과 같다). */
  async function resetProfile() {
    if (!company || busy !== null) return;
    setBusy('save');
    setError('');
    setSaved(null);
    setConfirmReset(false);
    try {
      await resetCompanyProfile(company.id);
      setCompanies(await listCompanies());
      discardAll();
      setSaved({ rejudged: await rejudgeLastCase(company.id), reset: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '프로필을 초기화하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  /** 조달청 조회 결과를 초안에 담는다. 업종은 더하기만 하고, 소재지는 조회한 시·도로 바꾼다. 저장은 「변경 사항 저장」으로 한다. */
  function applyProcurement(found: ProcurementCompany) {
    if (!company || !savedBasics) return '';
    const added = found.industries.filter((item) => item.registrable && !industryList.some((row) => row.code === item.code));
    if (added.length) setIndustryDraft([...industryList, ...added.map(({ code, name }) => ({ code, name }))]);
    const region = found.region_code ? regionByCode(found.region_code) : undefined;
    const current = basics ?? savedBasics;
    const regionChanged = Boolean(region) && (region?.code !== current.region_code || region?.name !== current.region_name);
    if (region && regionChanged) setBasicsDraft({ ...current, region_code: region.code, region_name: region.name });
    const numberAdded = !company.business_registration_number && numberDraft !== found.business_registration_number;
    if (numberAdded) setNumberDraft(found.business_registration_number);
    if (!added.length && !regionChanged && !numberAdded) return '조달청 정보와 프로필이 이미 같습니다. 바꾼 것이 없습니다.';
    const parts = [
      added.length ? `업종 ${added.length}개 추가` : '',
      region && regionChanged ? `소재지 ${region.name}` : '',
    ].filter(Boolean);
    return `아래 항목에 채웠습니다${parts.length ? ` — ${parts.join(', ')}` : ''}. 「변경 사항 저장」을 눌러야 저장됩니다.`;
  }

  /** 회사를 처음 만들 때: 조회 결과로 입력란을 채운다. 저장은 「회사 프로필 만들기」를 눌러야 된다. */
  function fillCreateForm(found: ProcurementCompany) {
    const region = found.region_code ? regionByCode(found.region_code) : undefined;
    setForm((current) => ({
      ...current,
      name: found.name ?? current.name,
      business_registration_number: found.business_registration_number,
      ...(region ? { region_code: region.code, region_name: region.name } : {}),
    }));
    const industries = found.industries.filter((item) => item.registrable).map(({ code, name }) => ({ code, name }));
    setCreateIndustries((current) => [...current, ...industries.filter((item) => !current.some((row) => row.code === item.code))]);
    return `입력란을 채웠습니다${industries.length ? ` — 업종 ${industries.length}개` : ''}. 확인한 뒤 「회사 프로필 만들기」를 눌러 주세요.`;
  }

  async function initialize() {
    if (!cachedGet<CompanyProfile[]>('/api/v1/companies')) setBusy('load');
    setError('');
    try {
      const [companyItems, industryResult] = await Promise.all([
        listCompanies(),
        searchIndustryCodes(),
      ]);
      setCompanies(companyItems);
      if (companyItems[0]) setSelectedId((value) => value || companyItems[0].id);
      setIndustryOptions(industryResult.items);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필을 불러오지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  // 다른 회사로 바꾸면 저장 안 한 편집은 버린다. 다른 회사에 잘못 저장되는 것보다 낫다.
  // react-compiler는 effect 안의 setState를 경고하지만, 여기서는 매 렌더가 아니라
  // company.id가 바뀔 때만 한 번 돈다. 초안을 회사 id로 들고 다니게 바꾸면 규칙을
  // 끄지 않아도 되는데, 그건 저장 경로 전체를 건드려야 해서 발표 뒤로 미룬다.
  useEffect(() => {
    // eslint-disable-next-line react/react-compiler
    setIndustryDraft(null);
    setBasicsDraft(null);
    setRecordsDraft(EMPTY_RECORDS_DRAFT);
    setNumberDraft(null);
    setSaved(null);
  }, [company?.id]);

  async function searchIndustries() {
    try {
      const result = await searchIndustryCodes(industryQuery);
      setIndustryOptions(result.items);
      setIndustryTotal(result.total);
      setIndustryExpanded(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '업종 검색에 실패했습니다.');
    }
  }

  async function submitCompany() {
    const industryCodes = createIndustries.map((item) => item.code);
    if (!industryCodes.length) {
      setError('업종을 하나 이상 골라 주세요. 업종명이나 코드로 검색해 목록에서 고를 수 있습니다.');
      return;
    }
    setBusy('create');
    setError('');
    try {
      const payload: CompanyCreatePayload = {
        name: form.name,
        business_registration_number: form.business_registration_number || undefined,
        region_code: form.region_code,
        region_name: form.region_name || undefined,
        company_size: form.company_size,
        industry_codes: industryCodes,
        staff: {
          total_count: Number(form.staff_total || 0),
          verified: false,
          // 역할별 인원은 처음에 받지 않는다. 비워 두면 역할을 요구하는 공고는 「확인 필요」로 남는다.
          roles: [],
        },
      };
      const created = await createCompany(payload);
      const refreshed = await listCompanies();
      setCompanies(refreshed);
      setSelectedId(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '회사 프로필 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  if (busy === 'load' && !company) return (
    <main className="app-shell-container space-y-6 py-12" aria-busy="true" aria-label="?? ???? ???? ????">
      <div className="h-10 w-60 animate-pulse rounded-xl bg-slate-200" />
      <div className="grid gap-5 lg:grid-cols-3">
        {[0, 1, 2].map((index) => <div key={index} className="h-36 animate-pulse rounded-2xl border border-slate-200 bg-slate-100" />)}
      </div>
      <div className="h-56 animate-pulse rounded-2xl border border-slate-200 bg-slate-100" />
    </main>
  );
  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10 md:py-12">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!company ? (
          <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
            <div className="rounded-[24px] border border-[var(--product-line)] bg-white p-8 shadow-[0_12px_35px_rgba(35,50,90,0.06)]">
              <Badge className="bg-[#eef1ff] text-[var(--product-accent-deep)]">회사 프로필 생성</Badge>
              <h1 className="mt-4 text-[32px] font-extrabold tracking-[-0.04em] text-[var(--product-ink)]">판정을 시작하려면 회사 프로필이 필요합니다</h1>
              <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--product-muted)]">
                업종, 지역, 기업 규모, 인력 정보를 먼저 저장하면 공고 참가자격 판정에서 실제 비교값으로 사용합니다.
              </p>

              <div className="mt-8">
                <ProcurementLookup applyLabel="입력란에 채우기" disabled={busy !== null} onApply={fillCreateForm}
                  applyHint="회사명·사업자등록번호·소재지·업종을 아래 입력란에 채웁니다. 기업 구분과 인원은 직접 넣어 주세요." />
              </div>

              <div className="mt-8 grid gap-5 sm:grid-cols-2">
                <label className="text-sm font-medium" htmlFor="company-name">회사명<Input id="company-name" className="mt-2" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="예: 그린브릿지 글로벌 주식회사" /></label>
                <label className="text-sm font-medium" htmlFor="company-brn">사업자등록번호<Input id="company-brn" className="mt-2" value={form.business_registration_number} onChange={(event) => setForm({ ...form, business_registration_number: event.target.value })} placeholder="10자리 숫자" /></label>
                <label className="text-sm font-medium" htmlFor="company-region-name">
                  소재지 (시·도)
                  <select id="company-region-name" className="mt-2 h-9 w-full rounded-md border border-[var(--product-line)] bg-white px-3 text-sm" value={form.region_code} onChange={(event) => {
                    const region = regionByCode(event.target.value);
                    if (region) setForm({ ...form, region_code: region.code, region_name: region.name });
                  }}>
                    {COMPANY_REGION_OPTIONS.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}
                  </select>
                </label>
                <label className="text-sm font-medium" htmlFor="company-region-code">지역 코드 (자동)<Input id="company-region-code" className="mt-2 bg-[var(--product-tint)]" value={form.region_code} readOnly /></label>
                <label className="text-sm font-medium" htmlFor="company-staff-total">전체 인원<Input id="company-staff-total" className="mt-2" type="number" min="0" value={form.staff_total} onChange={(event) => setForm({ ...form, staff_total: event.target.value })} /></label>
              </div>

              <div className="mt-6">
                <span className="text-sm font-medium">업종</span>
                <p className="mt-1 text-[12.5px] text-[var(--product-muted)]">공고의 업종 제한과 대조하는 값입니다. 여러 개를 고를 수 있습니다.</p>
                <div className="mt-2 flex flex-wrap items-center gap-2" aria-label="고른 업종">
                  {createIndustries.length ? createIndustries.map((item) => (
                    <span key={item.code} className="inline-flex items-center gap-2 rounded-full border border-[var(--product-line)] bg-[#f3f5ff] py-1.5 pl-3 pr-1.5 text-[13px]">
                      <strong>{item.code}</strong>
                      <span className="text-[var(--product-muted)]">{item.name}</span>
                      <button type="button" aria-label={`${item.name} 빼기`} onClick={() => setCreateIndustries((current) => current.filter((row) => row.code !== item.code))} className="rounded-full p-1 text-[var(--product-muted)] hover:bg-white hover:text-[var(--product-ink)]">
                        <X className="size-3.5" />
                      </button>
                    </span>
                  )) : <span className="text-[13px] text-amber-700">아직 고른 업종이 없습니다. 아래에서 검색해 고르거나, 위에서 사업자등록번호로 불러오세요.</span>}
                </div>
                <div className="mt-3 flex gap-2">
                  <Input value={industryQuery} onChange={(event) => setIndustryQuery(event.target.value)} placeholder="업종명 또는 코드 검색" aria-label="업종 검색"
                    onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void searchIndustries(); } }} />
                  <Button variant="outline" onClick={() => void searchIndustries()}><Search />검색</Button>
                </div>
                <div className={`mt-3 grid gap-2 sm:grid-cols-2 ${industryExpanded ? 'max-h-[336px] overflow-y-auto pr-1' : ''}`}>
                  {shownIndustryOptions.map((item) => {
                    const picked = createIndustries.some((row) => row.code === item.code);
                    return (
                      <button key={item.code} type="button" aria-pressed={picked}
                        onClick={() => setCreateIndustries((current) => picked ? current.filter((row) => row.code !== item.code) : [...current, { code: item.code, name: item.name }])}
                        className={`flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left text-sm ${picked ? 'border-[var(--product-accent)] bg-[#f3f5ff]' : 'border-[var(--product-line)] hover:border-[var(--product-accent)]'}`}>
                        <span className="min-w-0"><strong>{item.code}</strong><span className="ml-2 text-[var(--product-muted)]">{item.name}</span></span>
                        {picked ? <Check className="size-4 shrink-0 text-[var(--product-accent-deep)]" /> : <Plus className="size-4 shrink-0 text-[var(--product-muted)]" />}
                      </button>
                    );
                  })}
                  {industryOptions.length === 0 && <p className="text-[13px] text-[var(--product-muted)] sm:col-span-2">찾은 업종이 없습니다. 다른 낱말이나 코드로 검색해 보세요.</p>}
                </div>
                <IndustryMore shown={shownIndustryOptions.length} loaded={industryOptions.length} total={industryTotal} expanded={industryExpanded} onToggle={() => setIndustryExpanded((value) => !value)} />
              </div>

              <Button className="mt-8 rounded-full px-6" onClick={() => void submitCompany()} disabled={!form.name.trim() || createIndustries.length === 0 || busy !== null}>
                {busy === 'create' ? <LoaderCircle className="animate-spin" /> : <Plus />}
                회사 프로필 만들기
              </Button>
            </div>

            <aside className="rounded-[24px] bg-[var(--product-accent-deep)] p-8 text-white">
              <Building2 className="size-9 text-white/80" />
              <h2 className="mt-6 text-[28px] font-extrabold">프로필 값이 판정 근거가 됩니다</h2>
              <div className="mt-7 space-y-4 text-sm text-white/78">
                <p>업종 → 공고의 업종 제한과 대조합니다</p>
                <p>지역 → 공고의 핵심 지역 요건과 대조합니다</p>
                <p>기업 규모 → 기업 구분 제한과 대조합니다</p>
                <p>인력 → 상시 인력·전담 인력 요건과 대조합니다</p>
                <p>수행 실적 → 실적 건수·금액 요건과 대조합니다</p>
                <p>인증·등록 → 요구하는 면허·인증 보유 여부와 대조합니다</p>
              </div>
            </aside>
          </section>
        ) : (
          <>
            <section className="product-hero">
              <div className="flex flex-col items-center gap-4 text-center">
                <div>
                  <h1 className="text-[28px] font-extrabold tracking-[-0.035em]">프로필 항목 {filledRows}/{rows.length} 완료</h1>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Badge variant="outline">{company.name}</Badge>
                  <Button variant="outline" size="sm" onClick={() => void initialize()} disabled={busy !== null}><RefreshCw className={busy === 'load' ? 'animate-spin' : ''} />새로고침</Button>
                  <Button variant="outline" size="sm" onClick={() => setConfirmReset(true)} disabled={busy !== null}><RotateCcw />프로필 초기화</Button>
                </div>
              </div>
            </section>

            {/* 초기화는 되돌릴 수 없어 한 번 더 확인한다. 회사 관리자가 아닌 계정은 서버가 거절한다. */}
            {confirmReset && (
              <div role="alertdialog" aria-label="프로필 초기화 확인" className="mt-5 rounded-[18px] border border-rose-200 bg-rose-50 px-6 py-5">
                <p className="text-[15px] font-bold text-rose-900">프로필을 초기화할까요?</p>
                <p className="mt-1 text-[14px] leading-[1.7] text-rose-800">수행 실적, 인증·등록, 인력(상시 근로자 수·역할), 사업자등록번호를 모두 지웁니다. 회사명·업종·소재지·기업 구분은 남습니다(없으면 판정할 수 없는 값입니다). 지운 값은 되돌릴 수 없습니다.</p>
                <div className="mt-4 flex gap-2">
                  <Button className="rounded-full bg-rose-600 text-white hover:bg-rose-700" onClick={() => void resetProfile()} disabled={busy !== null}>초기화</Button>
                  <Button variant="outline" className="rounded-full" onClick={() => setConfirmReset(false)}>취소</Button>
                </div>
              </div>
            )}

            <div className="mt-5">
              <ProcurementLookup key={company.id} savedNumber={company.business_registration_number} disabled={busy !== null} onApply={applyProcurement}
                applyLabel="아래 항목에 채우기"
                applyHint="업종은 지금 프로필에 더하기만 하고(지우지 않음), 소재지는 조회한 시·도로 바꿉니다. 「변경 사항 저장」을 눌러야 저장됩니다." />
            </div>

            {missingRows.length > 0 && (
              <section className="mt-5 rounded-[22px] border border-[#e2d9a9] bg-[#fffaf0] p-6">
                <div className="flex items-center gap-2"><FileBadge2 className="size-5 text-amber-700" /><h2 className="text-[20px] font-bold">비어 있는 항목 {missingRows.length}건</h2></div>
                <div className="mt-4 divide-y divide-[#eee3bd]">
                  {missingRows.map((row) => <div key={row.label} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"><div><strong>{row.label}</strong><p className="mt-1 text-sm text-[var(--product-muted)]">이 값을 요구하는 공고는 확인 필요로 남습니다.</p></div><div className="flex shrink-0 items-center gap-2"><Badge className="bg-amber-100 text-amber-800">확인 필요</Badge>{/* 경고만 하고 끝내지 않는다. 이 화면 안에 입력 폼이 있는 항목은 거기로 바로 보낸다. */}
                    {row.form && <a href={row.form} className="rounded-full border border-amber-300 bg-white px-3 py-1.5 text-[13px] font-semibold text-amber-800 hover:bg-amber-50">입력하러 가기 →</a>}</div></div>)}
                </div>
              </section>
            )}

            <section id="industry-manager" className="mt-7 rounded-[22px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_28px_rgba(35,50,90,0.05)]">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-[22px] font-extrabold tracking-[-0.03em]">업종 코드</h2>
                  <p className="mt-1 text-[13px] text-[var(--product-muted)]">공고의 업종 제한과 대조하는 값입니다. 여러 개를 등록할 수 있습니다.</p>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-2">
                {industryList.length ? (
                  industryList.map((item) => (
                    <span key={item.code} className="inline-flex items-center gap-2 rounded-full border border-[var(--product-line)] bg-[#f3f5ff] py-1.5 pl-3 pr-1.5 text-[13px]">
                      <strong>{item.code}</strong>
                      <span className="text-[var(--product-muted)]">{item.name}</span>
                      <button type="button" aria-label={`${item.name} 제거`} onClick={() => removeIndustry(item.code)} disabled={industryList.length <= 1} title={industryList.length <= 1 ? '업종은 최소 1개가 필요합니다' : undefined} className="rounded-full p-1 text-[var(--product-muted)] transition-colors hover:bg-white hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent disabled:hover:text-[var(--product-muted)]">
                        <X className="size-3.5" />
                      </button>
                    </span>
                  ))
                ) : (
                  <p className="text-[13px] text-amber-700">등록된 업종이 없습니다. 업종을 요구하는 공고는 「확인 필요」로 남습니다. 저장하려면 업종을 하나 이상 추가해 주세요.</p>
                )}
              </div>

              <div className="mt-5 flex gap-2">
                <Input
                  value={industryQuery}
                  onChange={(event) => setIndustryQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void searchIndustries();
                  }}
                  placeholder="업종명 또는 코드 검색"
                />
                <Button variant="outline" onClick={() => void searchIndustries()}><Search />검색</Button>
              </div>

              <div className={`mt-3 grid gap-2 sm:grid-cols-2 ${industryExpanded ? 'max-h-[336px] overflow-y-auto pr-1' : ''}`}>
                {shownIndustryOptions.map((item) => {
                  const added = industryList.some((row) => row.code === item.code);
                  return (
                    <button
                      key={item.code}
                      type="button"
                      disabled={added}
                      onClick={() => addIndustry(item)}
                      className={`flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-colors ${added ? 'cursor-default border-[var(--product-line-2)] bg-[var(--product-tint)] text-[var(--product-muted)]' : 'border-[var(--product-line)] hover:border-[var(--product-accent)]'}`}
                    >
                      <span className="min-w-0"><strong>{item.code}</strong><span className="ml-2 text-[var(--product-muted)]">{item.name}</span></span>
                      {added ? <span className="shrink-0 text-[12px] font-semibold">등록됨</span> : <Plus className="size-4 shrink-0" />}
                    </button>
                  );
                })}
              </div>
              <IndustryMore shown={shownIndustryOptions.length} loaded={industryOptions.length} total={industryTotal} expanded={industryExpanded} onToggle={() => setIndustryExpanded((value) => !value)} />

              {industryBlock ? (
                <p className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-[13px] leading-[1.7] text-rose-800">{industryBlock}</p>
              ) : industryDirty ? (
                <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-[13px] leading-[1.7] text-amber-800">
                  저장하지 않은 변경이 있습니다. 화면 아래의 「변경 사항 저장」을 눌러야 판정에 반영됩니다.
                </p>
              ) : null}
            </section>

            {basics && (
              <section id="company-basics" className="mt-7 scroll-mt-24 rounded-[22px] border border-[var(--product-line)] bg-white p-6 shadow-[0_10px_28px_rgba(35,50,90,0.05)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[22px] font-extrabold tracking-[-0.03em]">회사 기본 정보</h2>
                    <p className="mt-1 text-[13px] text-[var(--product-muted)]">소재지 제한 · 기업 구분 제한 · 인력 요건 판정에 쓰는 값입니다.</p>
                  </div>
                </div>

                <div className="mt-5 grid gap-5 sm:grid-cols-2">
                  <label className="text-sm font-medium" htmlFor="basics-region-name">
                    소재지 (시·도)
                    <select id="basics-region-name" className="mt-2 h-9 w-full rounded-md border border-[var(--product-line)] bg-white px-3 text-sm" value={selectedRegionCode(basics.region_code, basics.region_name)} onChange={(event) => {
                      const region = regionByCode(event.target.value);
                      if (region) editBasics({ region_code: region.code, region_name: region.name });
                    }}>
                      {!selectedRegionCode(basics.region_code, basics.region_name) && <option value="">기존 소재지 유지 · {basics.region_name || '미설정'} ({basics.region_code || '코드 없음'})</option>}
                      {COMPANY_REGION_OPTIONS.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}
                    </select>
                  </label>
                  <label className="text-sm font-medium" htmlFor="basics-region-code">
                    지역 코드 (자동)
                    <Input id="basics-region-code" className="mt-2 bg-[var(--product-tint)]" value={basics.region_code} readOnly />
                  </label>
                  <label className="text-sm font-medium" htmlFor="basics-company-size">
                    기업 구분
                    <select
                      id="basics-company-size"
                      className="mt-2 h-9 w-full rounded-md border border-[var(--product-line)] bg-white px-3 text-sm"
                      value={basics.company_size}
                      onChange={(event) => editBasics({ company_size: event.target.value as CompanySize })}
                    >
                      {(Object.keys(COMPANY_SIZE_LABEL) as CompanySize[]).map((size) => (
                        <option key={size} value={size}>{COMPANY_SIZE_LABEL[size]}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-medium" htmlFor="basics-staff-total">
                    상시 근로자 수
                    <Input id="basics-staff-total" className="mt-2" type="number" min="0" value={basics.staff_total} onChange={(event) => editBasics({ staff_total: event.target.value })} placeholder="입력하지 않으면 「확인 필요」로 남습니다" />
                  </label>
                </div>

                {company.staff?.roles.length ? (
                  <p className="mt-4 text-[13px] text-[var(--product-muted)]">
                    역할별 인원 — {company.staff.roles.map((role) => `${role.role_name} ${role.headcount}명`).join(' · ')}
                    <span className="ml-2 text-[12px]">(역할 편집은 아직 지원하지 않습니다)</span>
                  </p>
                ) : null}

                {basicsBlock ? (
                  <p className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-[13px] leading-[1.7] text-rose-800">{basicsBlock}</p>
                ) : basicsDirty ? (
                  <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-[13px] leading-[1.7] text-amber-800">
                    저장하지 않은 변경이 있습니다. 화면 아래의 「변경 사항 저장」을 눌러야 판정에 반영됩니다.
                  </p>
                ) : null}
              </section>
            )}

            <ProfileRecordsManager company={company} draft={recordsDraft} onDraft={setRecordsDraft} disabled={busy !== null} />

            <section className="mt-7">
              <div className="flex items-center gap-3"><h2 className="text-[27px] font-extrabold tracking-[-0.035em]">프로필 항목</h2><span className="text-[14px] text-[var(--product-muted)]">판정에 실제로 들어가는 값입니다</span></div>
              <div className="mt-4 overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
                <div className="grid grid-cols-[1.2fr_1.8fr_0.9fr_0.9fr_1.1fr] bg-[var(--product-tint)] px-4 py-3 text-[12px] font-bold text-[var(--product-muted)]"><span>항목</span><span>값</span><span>출처</span><span>갱신일</span><span>이 값을 쓰는 곳</span></div>
                {rows.map((row) => (
                  <div key={row.label} className="grid grid-cols-1 gap-2 border-t border-[var(--product-line-2)] px-4 py-4 text-sm md:grid-cols-[1.2fr_1.8fr_0.9fr_0.9fr_1.1fr] md:items-center">
                    <strong>{row.label}</strong>
                    <span className={row.value.startsWith('비어 있음') ? 'text-amber-700' : ''}>{row.value}</span>
                    <span><Badge variant="outline">{row.source}</Badge></span>
                    <span>{new Date(row.updated).toLocaleDateString('ko-KR')}</span>
                    <span className="text-[12px] font-semibold text-[var(--product-accent-deep)]">{labelOf(REQUIREMENT_TYPE_LABEL, row.use)}</span>
                  </div>
                ))}
              </div>
            </section>

          </>
        )}

        {/* 저장은 여기 한 곳이다(2026-10-13). 바뀐 것이 있을 때만 화면 아래에 떠 있고, 저장하면 보던 공고를 다시 판정한다. */}
        {company && dirtyCount > 0 && (
          <div className="sticky bottom-4 z-20 mt-8 flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-[var(--product-accent-deep)] bg-white px-5 py-3 shadow-[0_12px_36px_rgba(31,42,82,0.18)]" aria-label="저장하지 않은 변경">
            <p className="text-[14px] font-semibold text-[var(--product-ink)]">
              저장하지 않은 변경 {dirtyCount}건
              {saveBlock && <span className="ml-2 font-medium text-rose-700">{saveBlock}</span>}
            </p>
            <div className="flex items-center gap-2">
              <Button variant="outline" className="rounded-full" onClick={discardAll} disabled={busy !== null}>되돌리기</Button>
              <Button className="rounded-full px-5" onClick={() => void saveAll()} disabled={saveBlock !== null || busy !== null}>
                {busy === 'save' ? <LoaderCircle className="animate-spin" /> : <Check />}변경 사항 저장
              </Button>
            </div>
          </div>
        )}
        {company && saved && dirtyCount === 0 && (
          <output className="sticky bottom-4 z-20 mt-8 flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-emerald-200 bg-emerald-50 px-5 py-3 text-[14px] text-emerald-900 shadow-[0_12px_36px_rgba(31,42,82,0.12)]">
            <span>
              <strong>{saved.reset ? '프로필을 초기화했습니다.' : '저장했습니다.'}</strong>{' '}
              {saved.rejudged?.state === 'done' && <>보던 공고 「{saved.rejudged.title}」를 다시 판정했습니다 — <strong>{OVERALL_STATUS_BADGE[saved.rejudged.overall].label}</strong></>}
              {saved.rejudged?.state === 'failed' && <span className="text-amber-800">보던 공고 「{saved.rejudged.title}」는 다시 판정하지 못했습니다. {saved.rejudged.message}</span>}
            </span>
            <span className="flex items-center gap-2">
              {saved.rejudged && <NavigationLink href={`/qualification?caseId=${encodeURIComponent(saved.rejudged.caseId)}`} className="font-bold text-[var(--product-accent-deep)] underline">결과 보기</NavigationLink>}
              <button type="button" className="text-[13px] text-emerald-800 underline" onClick={() => setSaved(null)}>닫기</button>
            </span>
          </output>
        )}
      </div>
    </main>
  );
}

const INDUSTRY_PREVIEW = 6;

/** 업종 검색 결과의 「더보기」. 눌러야 목록이 펼쳐지고, 펼친 뒤에는 상자 안에서 넘겨 본다. */
function IndustryMore({ shown, loaded, total, expanded, onToggle }: { shown: number; loaded: number; total: number; expanded: boolean; onToggle: () => void }) {
  if (loaded <= INDUSTRY_PREVIEW) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3">
      <button type="button" aria-expanded={expanded} onClick={onToggle} className="rounded-full bg-[var(--product-accent)] px-4 py-1.5 text-[13px] font-semibold text-white hover:bg-[var(--product-accent-deep)]">
        {expanded ? '접기' : `더보기 (${loaded - shown}개)`}
      </button>
      {expanded && total > loaded && <span className="text-[12.5px] tabular-nums text-[var(--product-muted)]">{total}건 중 {loaded}건입니다. 낱말을 더 넣으면 좁혀집니다.</span>}
    </div>
  );
}
