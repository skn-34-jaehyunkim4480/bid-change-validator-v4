'use client';

import { useEffect, useState } from 'react';
import { sharedQueryClient, invalidateSharedData } from '@/lib/shared-query-cache';
import { RefreshCw } from 'lucide-react';
import { NavigationLink } from '@/components/navigation-link';
import { JudgmentLinkButton } from '@/components/product/judgment-link-button';
import { Button } from '@/components/ui/button';
import { useAppUser } from '@/components/app-user-context';
import { listCompanies } from '@/lib/qualification-api';
import { listIndustryExperimentalRecommendations } from '@/lib/ml-experimental-api';
import type { MlExperimentalResponse } from '@/lib/ml-experimental-schema';
import { listNoticeMatches, type NoticeMatch } from '@/lib/notice-matching-api';
import type { MlRecommendation } from '@/lib/ml-recommendation-schema';

type RecommendationState = {
  loading: boolean;
  matchingLoading: boolean;
  companyName: string | null;
  companyId: string | null;
  matches: NoticeMatch[];
  matchingError: string | null;
  error: string | null;
};

const INITIAL: RecommendationState = {
  loading: true, matchingLoading: false,
  companyName: null, companyId: null, matches: [],
  matchingError: null, error: null,
};

const QUALIFICATION_LABEL: Record<NoticeMatch['overall_status'], string> = {
  core_met: '핵심 요건: 충족',
  core_unmet: '핵심 요건: 미충족',
  needs_review: '핵심 요건: 확인 필요',
};

const ML_QUALIFICATION_LABEL = {
  core_met: '참가자격: 충족 확인',
  core_unmet: '참가자격: 조건 미달',
  needs_review: '참가자격: 확인 필요',
  UNKNOWN: '참가자격: 확인 전',
  stale: '참가자격: 다시 검토 필요',
} as const;

function describeFailure(error: unknown) {
  return error instanceof Error ? error.message : '연결을 확인하고 다시 시도해 주세요.';
}

function groupNoticeTitles(rows: MlRecommendation[]) {
  const groups = new Map<string, MlRecommendation[]>();
  for (const item of rows) {
    const key = item.title.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase();
    const existing = groups.get(key);
    if (existing) existing.push(item);
    else groups.set(key, [item]);
  }
  return [...groups.values()].map(([item, ...duplicates]) => ({ item, duplicates }));
}

export default function RecommendationsPage() {
  const user = useAppUser();
  const [state, setState] = useState<RecommendationState>(() => sharedQueryClient().getQueryData<RecommendationState>(['view', 'recommendations']) ?? INITIAL);
  const [attempt, setAttempt] = useState(0);
  const [visibleCount, setVisibleCount] = useState(10);
  const [experimental, setExperimental] = useState<{
    loading: boolean; companyId: string | null; data: MlExperimentalResponse | null; error: string | null;
  }>({ loading: false, companyId: null, data: null, error: null });

  // Store independently resolved results for normal app navigation.
  useEffect(() => {
    if (!state.loading && state.companyId) {
      sharedQueryClient().setQueryData(['view', 'recommendations'], state);
    }
  }, [state]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const companies = await listCompanies();
        if (!active) return;
        const company = user?.company_id
          ? companies.find((item) => item.id === user.company_id)
          : companies[0];
        if (!company) {
          setState({ ...INITIAL, loading: false, error: '조회할 회사 프로필이 없습니다. 먼저 회사 프로필을 확인해 주세요.' });
          return;
        }
        setExperimental({ loading: true, companyId: company.id, data: null, error: null });
        setVisibleCount(10);
        void listIndustryExperimentalRecommendations(company.id).then(
          (data) => {
            if (active) setExperimental((previous) => previous.companyId === company.id
              ? { loading: false, companyId: company.id, data, error: null } : previous);
          },
          (error: unknown) => {
            if (active) setExperimental((previous) => previous.companyId === company.id
              ? { loading: false, companyId: company.id, data: null, error: describeFailure(error) } : previous);
          },
        );
        // The default search is BM25; no slow legacy /ml request is sent.
        setState({
          ...INITIAL, loading: false, matchingLoading: true,
          companyName: company.name, companyId: company.id,
        });
        void listNoticeMatches(company.id, 50).then(
          (matches) => {
            if (!active) return;
            setState((previous) => previous.companyId === company.id
              ? { ...previous, matches: matches.items, matchingLoading: false, matchingError: null }
              : previous);
          },
          (error: unknown) => {
            if (!active) return;
            setState((previous) => previous.companyId === company.id
              ? { ...previous, matches: [], matchingLoading: false, matchingError: describeFailure(error) }
              : previous);
          },
        );

      } catch (error) {
        if (active) setState({ ...INITIAL, loading: false, error: describeFailure(error) });
      }
    }
    void load();
    return () => { active = false; };
  }, [attempt, user?.id, user?.company_id]);

  function retry() {
    invalidateSharedData();
    setExperimental({ loading: false, companyId: null, data: null, error: null });
    setState(INITIAL);
    setAttempt((value) => value + 1);
  }


  return (
    <main className="app-shell-container min-w-0 py-8 pb-20 sm:py-12">
      <section className="product-hero" aria-labelledby="recommendations-page-title">
        <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-medium text-white/75">홈 › AI 추천</p>
            <h1 id="recommendations-page-title" className="mt-2 text-[28px] font-extrabold tracking-[-0.035em]">
              AI 추천
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6">
              우리 회사에 어울리는 입찰 공고를 찾아드립니다. 관심 있는 공고는 참가자격도 확인해 보세요.
            </p>
          </div>
          <Button type="button" variant="outline" size="sm" className="shrink-0 rounded-full"
            disabled={state.loading} onClick={retry}>
            <RefreshCw size={16} aria-hidden="true" /> 새로고침
          </Button>
        </div>
      </section>

      {state.loading ? (
        <output className="mt-8 block space-y-4 rounded-xl border bg-white p-5 text-sm" aria-live="polite">
          {[0, 1, 2].map((index) => <div key={index} className="h-20 animate-pulse rounded-xl bg-slate-100" />)}
          회사 프로필을 확인하고 있습니다.
        </output>
      ) : state.error ? (
        <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
          {state.error} <NavigationLink href="/company" className="ml-2 underline">회사 프로필로 이동</NavigationLink>
          <Button type="button" variant="outline" size="sm" className="ml-2" onClick={retry}>다시 시도</Button>
        </div>
      ) : (
        <>
          <section aria-labelledby="ml-experiment-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
            <h2 id="ml-experiment-heading" className="text-lg font-bold">기업 맞춤 공고 추천</h2>
            <p className="mt-2 text-sm leading-7 text-[var(--product-muted)]">
              회사에 등록된 업종과 업무를 바탕으로 관련 공고를 보여드립니다.
              추천 순위는 참가자격을 보장하지 않으므로, 관심 있는 공고는 별도로 확인해 주세요.
            </p>
            <p className="mt-3 text-sm text-slate-600">조회 회사: {state.companyName}</p>
            {experimental.companyId === state.companyId && experimental.loading && (
              <output className="mt-5 block rounded-xl border bg-slate-50 p-4 text-sm text-slate-700">
                맞춤 추천을 계산 중입니다.
              </output>
            )}
            {experimental.companyId === state.companyId && experimental.error && (
              <p role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                {experimental.error}
              </p>
            )}
            {experimental.companyId === state.companyId && experimental.data && (
              <div className="mt-5 space-y-5" aria-live="polite">
                <div className="text-xs leading-6 text-slate-600">
                  <p>현재 추천 대상으로 분류한 공고 {experimental.data.valid_live_candidates}건에서 찾았습니다.</p>
                  <details className="mt-1">
                    <summary className="w-fit cursor-pointer font-medium text-blue-700 underline underline-offset-2">
                      검색 범위 자세히 보기
                    </summary>
                    <p className="mt-1">
                      기존 검색 자료와 연결된 공고 {experimental.data.indexed_live_candidates}건,
                      {' '}공고명으로만 검색한 공고 {experimental.data.live_title_fallback_candidates}건입니다.
                      추천 순위만으로 공고의 세부 조건까지 확인된 것은 아닙니다.
                    </p>
                  </details>
                </div>
                {[
                  { label: '참가자격 충족이 확인된 공고', rows: experimental.data.items, empty: '아직 참가자격까지 확인된 공고가 없습니다.' },
                  { label: '추천 공고 · 참가자격 확인 필요', rows: experimental.data.needs_review_items, empty: '현재 확인할 추천 공고가 없습니다.' },
                ].map((group) => (
                  <div key={group.label}>
                    <h3 className="text-sm font-semibold">{group.label} ({group.rows.length}건)</h3>
                    {group.rows.length === 0 ? (
                      <p className="mt-2 text-xs text-slate-600">
                        {group.empty}
                      </p>
                    ) : (
                      <ul className="mt-2 divide-y rounded-xl border px-4">
                        {groupNoticeTitles(group.rows).slice(0, visibleCount).map(({ item, duplicates }) => (
                          <li key={item.notice_id} className="py-4 text-sm">
                            <NavigationLink href={'/notices/' + encodeURIComponent(item.notice_id)}
                              className="break-words font-semibold text-blue-700 underline">{item.title}</NavigationLink>
                            <p className="mt-2 text-xs text-slate-600">
                              {ML_QUALIFICATION_LABEL[item.qualification_state]}
                              {' · '}공고 버전 {item.version_number}
                              {' · '}관련도 점수 {item.relevance_score.toFixed(3)}
                            </p>
                            {item.qualification_state === 'UNKNOWN' && (
                              <p className="mt-1 text-xs text-slate-600">아직 이 공고의 참가자격을 검토하지 않았습니다.</p>
                            )}
                            <JudgmentLinkButton noticeId={item.notice_id} label="참가자격 확인하기"
                              className="mt-2 inline-flex text-xs font-semibold text-blue-700 underline disabled:opacity-60" />
                            {duplicates.length > 0 && (
                              <details className="mt-3 rounded-lg border bg-slate-50 p-3 text-xs">
                                <summary className="cursor-pointer font-medium">동일 제목의 다른 공고 {duplicates.length}건 · 별도 공고 조건 확인</summary>
                                <ul className="mt-2 space-y-2">
                                  {duplicates.map((other) => (
                                    <li key={other.notice_id}>
                                      <NavigationLink href={'/notices/' + encodeURIComponent(other.notice_id)}
                                        className="text-blue-700 underline">다른 공고 상세 · 버전 {other.version_number}</NavigationLink>
                                    </li>
                                  ))}
                                </ul>
                              </details>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {groupNoticeTitles(group.rows).length > visibleCount && (
                      <Button type="button" variant="outline" className="mt-4"
                        onClick={() => setVisibleCount((count) => count + 10)}>
                        더 보기 ({Math.min(groupNoticeTitles(group.rows).length - visibleCount, 10)}건)
                      </Button>
                    )}
                  </div>
                ))}
                <p className="text-xs text-slate-600">관련도가 높더라도 실제 참가 가능 여부는 공고별로 확인해야 합니다.</p>
              </div>
            )}
          </section>
          <section aria-labelledby="qualification-matches-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
            <h2 id="qualification-matches-heading" className="text-lg font-bold">이전에 검토한 공고</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--product-muted)]">
              이전에 저장한 참가자격 검토 결과를 보여드립니다.
              새 공고를 검토하려면 위 추천 목록에서 참가자격 확인하기를 선택하세요.
            </p>
            {state.matchingLoading ? (
              <output className="mt-4 rounded-xl border bg-slate-50 p-4 text-sm text-slate-600">
                저장된 자격판정 결과를 불러오는 중입니다.
              </output>
            ) : state.matchingError ? (
              <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{state.matchingError}</p>
            ) : state.matches.length ? (
              <ul className="mt-4 divide-y">
                {state.matches.map((match) => (
                  <li key={match.notice_id} className="flex flex-wrap justify-between gap-3 py-4 text-sm">
                    <NavigationLink href={'/notices/' + encodeURIComponent(match.notice_id)}
                      className="min-w-0 break-words font-medium text-blue-700 underline">{match.title}</NavigationLink>
                    <span className="text-xs font-semibold text-slate-600">{QUALIFICATION_LABEL[match.overall_status]}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-4 text-sm text-slate-600">아직 저장된 참가자격 검토 결과가 없습니다.</p>}
            <NavigationLink href="/notices" className="mt-5 inline-flex text-sm font-semibold text-blue-700 underline">
              공고 전체 목록에서 직접 검색
            </NavigationLink>
          </section>
        </>
      )}
    </main>
  );
}
