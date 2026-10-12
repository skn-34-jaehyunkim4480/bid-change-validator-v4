'use client';

import { useEffect, useState } from 'react';
import { LoaderCircle, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { listCompanies } from '@/lib/qualification-api';
import { listNoticeMatches, type NoticeMatch } from '@/lib/notice-matching-api';
import { useRouter } from 'next/navigation';
import { analysisBadgeLabel, OVERALL_STATUS_BADGE } from '@/lib/status-copy';

const PAGE_SIZE = 12;

export function CachedNoticeMatches() {
  const router = useRouter();
  const [matches, setMatches] = useState<NoticeMatch[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError('');
      try {
        const companies = companyId ? null : await listCompanies();
        const id = companyId || companies?.[0]?.id;
        if (!id) {
          if (active) setMatches([]);
          return;
        }
        const result = await listNoticeMatches(id, PAGE_SIZE, offset);
        if (!active) return;
        setCompanyId(id);
        setMatches(result.items);
        setTotal(result.analyzed_notice_count);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : '회사 판정 이력을 불러오지 못했습니다.');
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [companyId, offset]);

  if (loading && !companyId) return <section className="app-shell-container py-8"><div className="grid min-h-28 place-items-center rounded-[22px] border border-[var(--product-line)]"><LoaderCircle className="size-6 animate-spin text-[var(--product-accent)]" /></div></section>;
  if (!companyId && !error) return null;

  return (
    <section className="app-shell-container pt-10 pb-12">
      <div>
        <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <h2 className="text-[28px] font-extrabold tracking-[-0.035em]">우리 회사의 판정 이력</h2>
          <span className="text-[13px] text-[var(--product-muted)]">판정한 공고·차수 {total}건</span>
        </div>
        {error && <p className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-[13px] text-rose-700">{error}</p>}
        {loading && <p className="mt-4 text-[13px] text-[var(--product-muted)]">판정 이력을 불러오는 중입니다.</p>}
        {!loading && matches.length ? (
          <>
            <div className="mt-5 grid gap-4 lg:grid-cols-3">
              {matches.map((item) => {
                const meta = OVERALL_STATUS_BADGE[item.overall_status];
                return (
                  <article key={`${item.notice_id}:${item.version_number}`} className="rounded-[20px] border border-[var(--product-line)] bg-white p-5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-3 py-1 text-[13px] font-bold ${meta.className}`}>{meta.label}</span>
                      <span className="text-[13px] text-[var(--product-muted)]">{analysisBadgeLabel(item.analysis_status)}</span>
                      {!item.is_current_version && <span className="rounded-full bg-amber-50 px-3 py-1 text-[12px] text-amber-800">이전 차수 판정</span>}
                    </div>
                    <h3 className="mt-4 line-clamp-2 text-[15px] font-bold leading-6">{item.title}</h3>
                    <p className="mt-2 text-[13px] text-[var(--product-muted)]">{item.institution_name ?? '기관 미상'} · {item.bid_notice_no} · {item.version_number}차</p>
                    {item.satisfied_count + item.unknown_count + item.unsatisfied_count > 0 ? (
                      <div className="mt-4 flex gap-3 text-[13px]"><span className="text-emerald-700">충족 {item.satisfied_count}</span><span className="text-amber-700">확인 {item.unknown_count}</span><span className="text-rose-700">미달 {item.unsatisfied_count}</span></div>
                    ) : <p className="mt-4 text-[13px] text-[var(--product-muted)]">{item.requirement_count === 0 ? '자격요건 미확보' : '판정된 항목 없음'}</p>}
                    <Button size="sm" className="mt-5 rounded-full" onClick={() => router.push(`/qualification?caseId=${item.case_id}`)}>검토 열기 <ArrowRight /></Button>
                  </article>
                );
              })}
            </div>
            {total > PAGE_SIZE && (
              <div className="mt-5 flex items-center justify-between gap-3">
                <span className="text-[13px] text-[var(--product-muted)]">{offset + 1}–{offset + matches.length} / {total}건</span>
                <div className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>이전</Button><Button variant="outline" disabled={offset + matches.length >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>다음</Button></div>
              </div>
            )}
          </>
        ) : !loading && !error && <div className="mt-5 rounded-[20px] border border-dashed border-[var(--product-line)] px-6 py-10 text-center text-[13px] text-[var(--product-muted)]">우리 회사의 판정 이력이 없습니다. 자격 검토에서 판정을 실행하면 이곳에 표시됩니다.</div>}
      </div>
    </section>
  );
}
