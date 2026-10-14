'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { CalendarClock, ClipboardCheck, FileText, ListOrdered, LoaderCircle, RefreshCw, Sparkles } from 'lucide-react';
import { useAppUser } from '@/components/app-user-context';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { openMembershipIfRequired } from '@/lib/membership';
import {
  createPrepGuide, daysLeft, evaluationTotalPoints, kst, listJudgedCases, materialCounts, saveGuide, savedGuide,
  type GuideEvaluationItem, type JudgedCase, type PrepGuide,
} from '@/lib/prep-guide';

/*
  입찰 준비 지침서(2026-10-14). 참가자격 판정을 마친 공고 가운데 하나를 고르면,
  무엇을 어떤 순서로 준비해야 하는지 공고 문서와 회사 프로필을 맞대어 정리해 준다.
  제안서 글을 대신 쓰지 않는다 — 회사에 관한 사실은 프로필에 있는 항목만 가리킨다.
*/
const STATUS_TONE: Record<string, string> = {
  core_met: 'bg-emerald-50 text-emerald-800', eligible: 'bg-emerald-50 text-emerald-800',
  core_unmet: 'bg-rose-50 text-rose-800', ineligible: 'bg-rose-50 text-rose-800',
};
const LEAD_TONE: Record<string, string> = {
  '오래 걸림': 'bg-rose-50 text-rose-800', 보통: 'bg-amber-50 text-amber-800', '바로 가능': 'bg-emerald-50 text-emerald-800',
};

function deadlineText(item: JudgedCase) {
  if (item.expired) return '마감 지남';
  const left = daysLeft(item.bid_closed_at);
  if (left === null) return '마감 모름';
  return left === 0 ? '오늘 마감' : `마감 ${left}일 전`;
}

export default function PrepGuidePage() {
  const user = useAppUser();
  const router = useRouter();
  const selectedId = useSearchParams().get('caseId') ?? '';
  const [cases, setCases] = useState<JudgedCase[] | null>(null);
  const [listError, setListError] = useState('');
  const [guide, setGuide] = useState<PrepGuide | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [consent, setConsent] = useState(false);

  useEffect(() => {
    let alive = true;
    listJudgedCases()
      .then((rows) => { if (alive) setCases(rows); })
      .catch((cause) => { if (alive) setListError(cause instanceof Error ? cause.message : '판정한 공고를 불러오지 못했습니다.'); });
    return () => { alive = false; };
  }, []);

  // 공고를 바꾸면 이 브라우저에 둔 지침서를 보여 준다. 없으면 만들기 전 화면이다.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setGuide(user && selectedId ? savedGuide(user.id, selectedId) : null);
      setError('');
    }, 0);
    return () => window.clearTimeout(timer);
  }, [user, selectedId]);

  const selected = (cases ?? []).find((item) => item.case_id === selectedId) ?? null;

  async function generate() {
    if (!selected || !user || busy) return;
    setBusy(true);
    setError('');
    try {
      const created = await createPrepGuide(selected.case_id);
      saveGuide(user.id, created);
      setGuide(created);
    } catch (cause) {
      if (!openMembershipIfRequired(cause, 'COPILOT_QUESTION')) setError(cause instanceof Error ? cause.message : '지침서를 만들지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell-container min-w-0 py-8 pb-20 sm:py-10">
      <header className="text-center">
        <h1 className="text-[28px] font-extrabold tracking-[-0.035em]">입찰 준비 지침서</h1>
        <p className="mx-auto mt-2 max-w-[70ch] text-[14.5px] leading-[1.7] text-[var(--product-muted)]">
          참가자격 판정을 마친 공고를 고르면, 공고 문서의 평가 항목·제출 서류·일정과 회사 프로필을 맞대어 무엇을 어떤 순서로 준비할지 정리합니다.
        </p>
      </header>

      <div className="mt-7 grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <section aria-labelledby="judged-cases-title" className="min-w-0">
          <h2 id="judged-cases-title" className="text-[15px] font-bold">판정을 마친 공고{cases ? ` ${cases.length}건` : ''}</h2>
          {listError && <p className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-[13px] text-rose-800">{listError}</p>}
          {!cases && !listError && <p className="mt-3 text-[13px] text-[var(--product-muted)]">불러오는 중…</p>}
          {cases && cases.length === 0 && (
            <div className="mt-3 rounded-[18px] border border-dashed border-[var(--product-line)] px-5 py-8 text-[13.5px] leading-[1.7] text-[var(--product-muted)]">
              아직 판정을 마친 공고가 없습니다. 공고를 골라 참가자격 검토를 먼저 해 주세요.
              <NavigationLink href="/notices" className="mt-3 block font-semibold text-[var(--product-accent-deep)] underline">공고 찾기로 가기</NavigationLink>
            </div>
          )}
          <ul className="mt-3 grid gap-2 lg:max-h-[70vh] lg:overflow-y-auto lg:pr-1" aria-label="판정을 마친 공고">
            {(cases ?? []).map((item) => {
              const active = item.case_id === selectedId;
              return (
                <li key={item.case_id}>
                  <button type="button" aria-current={active ? 'true' : undefined}
                    onClick={() => router.push(`/prep-guide?caseId=${encodeURIComponent(item.case_id)}`)}
                    className={`w-full rounded-[16px] border px-4 py-3 text-left transition-colors ${active ? 'border-[var(--product-accent)] bg-[#f3f5ff]' : item.expired ? 'border-[var(--product-line)] bg-[#eceef3]' : 'border-[var(--product-line)] bg-white hover:border-[var(--product-accent)]'}`}>
                    <strong className="block text-[14px] leading-[1.45]">{item.notice_title}</strong>
                    <span className="mt-1 block text-[12.5px] text-[var(--product-muted)]">{item.bid_notice_no}{item.institution ? ` · ${item.institution}` : ''}</span>
                    <span className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
                      <span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_TONE[item.overall_status] ?? 'bg-amber-50 text-amber-800'}`}>{item.overall_label}</span>
                      <span className={`rounded-full px-2 py-0.5 ${item.expired ? 'bg-[#5b6170] font-semibold text-white' : 'bg-[#f1f3f8] text-[var(--product-muted)]'}`}>{deadlineText(item)}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        <section aria-live="polite" className="min-w-0">
          {!selected && (
            <div className="rounded-[20px] border border-dashed border-[var(--product-line)] px-6 py-16 text-center text-[14px] text-[var(--product-muted)]">
              {cases && cases.length > 0 ? '왼쪽에서 공고를 고르면 지침서를 만들 수 있습니다.' : '판정을 마친 공고가 여기에 나옵니다.'}
            </div>
          )}

          {selected && !guide && (
            <div className="rounded-[20px] border border-[var(--product-line)] bg-white px-6 py-7">
              <h2 className="text-[19px] font-bold leading-[1.4]">{selected.notice_title}</h2>
              <p className="mt-1 text-[13px] text-[var(--product-muted)]">{selected.bid_notice_no} · 입찰 마감 {kst(selected.bid_closed_at)}</p>
              {selected.expired && <p className="mt-4 rounded-xl bg-[#eceef3] px-3 py-2 text-[13px]">마감이 지난 공고입니다. 지침서는 만들 수 있지만 이번 입찰에는 쓸 수 없습니다.</p>}
              <label className="mt-5 flex items-start gap-2.5 rounded-xl bg-[#f3f5ff] px-4 py-3 text-[13.5px] leading-[1.6]">
                <input type="checkbox" className="mt-1" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                <span>지침서를 만들 때 공고 문서의 일부와 회사 프로필이 외부 AI 로 전달됩니다. 이해하였습니다.</span>
              </label>
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <Button className="rounded-full px-6" disabled={!consent || busy} onClick={() => void generate()}>
                  {busy ? <LoaderCircle className="animate-spin" /> : <Sparkles />}{busy ? '만드는 중… (30초쯤 걸립니다)' : '지침서 만들기'}
                </Button>
                <span className="text-[12.5px] text-[var(--product-muted)]">한 번 만들 때 이 공고의 AI Copilot 질문 1회를 씁니다.</span>
              </div>
              {error && <p className="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-[13px] text-rose-800">{error}</p>}
            </div>
          )}

          {selected && guide && <GuideView guide={guide} selected={selected} busy={busy} error={error} onRegenerate={() => void generate()} />}
        </section>
      </div>
    </main>
  );
}

function Card({ icon, title, note, children }: { icon: React.ReactNode; title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[20px] border border-[var(--product-line)] bg-white px-6 py-6">
      <h3 className="flex items-center gap-2 text-[16.5px] font-bold">{icon}{title}</h3>
      {note && <p className="mt-1 text-[12.5px] text-[var(--product-muted)]">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function GuideView({ guide, selected, busy, error, onRegenerate }: { guide: PrepGuide; selected: JudgedCase; busy: boolean; error: string; onRegenerate: () => void }) {
  const counts = materialCounts(guide);
  const totalPoints = evaluationTotalPoints(guide.evaluation_items);
  const left = daysLeft(selected.bid_closed_at);
  const factText = (id: string) => guide.profile_facts.find((fact) => fact.id === id);
  return (
    <div className="grid gap-4">
      <div className="rounded-[20px] bg-[var(--product-accent-deep)] px-6 py-6 text-white">
        <p className="text-[12.5px] text-white/75">{guide.notice.bid_notice_no}{guide.notice.institution ? ` · ${guide.notice.institution}` : ''}</p>
        <h2 className="mt-1 text-[21px] font-extrabold leading-[1.4] tracking-[-0.02em]">{guide.notice.title}</h2>
        <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-[13.5px]">
          <div><dt className="text-white/70">입찰 마감</dt><dd className="font-semibold tabular-nums">{kst(selected.bid_closed_at)}{left !== null && (left < 0 ? ' (지남)' : ` (${left}일 남음)`)}</dd></div>
          <div><dt className="text-white/70">평가 항목</dt><dd className="font-semibold tabular-nums">{guide.evaluation_items.length}개{totalPoints !== null ? ` · 배점 합 ${totalPoints}` : ''}</dd></div>
          <div><dt className="text-white/70">준비 자료</dt><dd className="font-semibold tabular-nums">{counts.total}개 중 프로필에 있음 {counts.held} · 준비 필요 {counts.needed}</dd></div>
        </dl>
        <div className="mt-5 flex flex-wrap items-center gap-3 text-[12.5px] text-white/80">
          <button type="button" disabled={busy} onClick={onRegenerate} className="inline-flex items-center gap-1.5 rounded-full border border-white/40 px-3.5 py-1.5 font-semibold text-white hover:bg-white/10 disabled:opacity-60">
            {busy ? <LoaderCircle className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}{busy ? '다시 만드는 중…' : '다시 만들기'}
          </button>
          <span>{kst(guide.generated_at)}에 만듦 · 다시 만들면 질문 1회를 더 씁니다</span>
        </div>
      </div>
      {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-[13px] text-rose-800">{error}</p>}
      {guide.warnings.map((warning) => <p key={warning} className="rounded-xl bg-amber-50 px-4 py-3 text-[13.5px] leading-[1.6] text-amber-900">{warning}</p>)}

      {guide.steps.length > 0 && (
        <Card icon={<ListOrdered className="size-5 text-[var(--product-accent)]" />} title="준비 순서" note="발급·확인에 오래 걸리는 것부터 앞에 두었습니다.">
          <ol className="grid gap-3">
            {guide.steps.map((step, index) => (
              <li key={`${index}-${step.title}`} className="flex gap-3">
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-[#f3f5ff] text-[12.5px] font-bold tabular-nums text-[var(--product-accent-deep)]">{index + 1}</span>
                <div className="min-w-0">
                  <p className="text-[14.5px] font-semibold">{step.title}<span className={`ml-2 rounded-full px-2 py-0.5 align-[1px] text-[11.5px] font-semibold ${LEAD_TONE[step.lead_time] ?? ''}`}>{step.lead_time}</span></p>
                  <p className="mt-0.5 text-[13.5px] leading-[1.65] text-[var(--product-muted)]">{step.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <Card icon={<CalendarClock className="size-5 text-[var(--product-accent)]" />} title="일정" note="공고에 등록된 일정과, 공고 문서에 적힌 날짜입니다. 문서의 날짜는 적힌 그대로 옮겼습니다.">
        {guide.schedule.length === 0 ? <p className="text-[13.5px] text-[var(--product-muted)]">확인된 일정이 없습니다.</p> : (
          <ul className="grid gap-2">
            {guide.schedule.map((row, index) => (
              <li key={`${index}-${row.label}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-[var(--product-line)] pb-2 last:border-0 last:pb-0">
                <span className="min-w-[96px] text-[14px] font-semibold">{row.label}</span>
                <span className="text-[14px] tabular-nums">{row.at ? kst(row.at) : row.when}</span>
                <span className="text-[12px] text-[var(--product-muted)]">{row.source}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {guide.evaluation_items.length > 0 && (
        <Card icon={<ClipboardCheck className="size-5 text-[var(--product-accent)]" />} title="평가 항목별 준비물" note="배점이 큰 항목부터입니다. 「프로필에 있음」은 회사 프로필에 근거가 되는 항목이 있다는 뜻이고, 증빙 서류가 준비됐다는 뜻은 아닙니다.">
          <ul className="grid gap-4">
            {guide.evaluation_items.map((item) => <EvaluationItem key={item.name} item={item} factText={factText} />)}
          </ul>
        </Card>
      )}

      {(guide.submission_documents.length > 0 || guide.format_rules.length > 0) && (
        <Card icon={<FileText className="size-5 text-[var(--product-accent)]" />} title="제출 서류와 작성 지침" note="공고 문서에서 인용문과 함께 뽑았습니다. 제출 전에 원문으로 한 번 더 확인해 주세요.">
          <div className="grid gap-5 md:grid-cols-2">
            <Checklist title="제출 서류" rows={guide.submission_documents} empty="문서에서 제출 서류 목록을 찾지 못했습니다." />
            <Checklist title="작성·제출 지침" rows={guide.format_rules} empty="문서에서 작성 지침을 찾지 못했습니다." />
          </div>
        </Card>
      )}

      <p className="text-[12.5px] leading-[1.7] text-[var(--product-muted)]">
        읽은 문서: {guide.documents_read.length ? guide.documents_read.join(', ') : '없음'}. 이 지침서는 AI 가 공고 문서를 읽고 정리한 것이라 빠진 항목이 있을 수 있습니다. 최종 판단은 공고 원문으로 해 주세요.
      </p>
    </div>
  );
}

function EvaluationItem({ item, factText }: { item: GuideEvaluationItem; factText: (id: string) => { kind: string; text: string } | undefined }) {
  return (
    <li className="rounded-[14px] border border-[var(--product-line)] px-4 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-[15px] font-bold">{item.name}{item.kind === '가격' && <span className="ml-2 text-[12px] font-normal text-[var(--product-muted)]">가격 평가</span>}</h4>
        <span className="text-[13px] font-semibold tabular-nums text-[var(--product-accent-deep)]">{item.points !== null ? `배점 ${item.points}` : '배점 모름'}</span>
      </div>
      {item.focus && <p className="mt-1 text-[13.5px] leading-[1.6]">{item.focus}</p>}
      <p className="mt-1 text-[12px] text-[var(--product-muted)]">공고: “{item.quote}”</p>
      {item.materials.length > 0 && (
        <ul className="mt-3 grid gap-2">
          {item.materials.map((material) => {
            const facts = material.company_facts.map(factText).filter((fact): fact is { kind: string; text: string } => Boolean(fact));
            return (
              <li key={material.text} className="flex flex-wrap items-start gap-x-2 gap-y-1 text-[13.5px] leading-[1.6]">
                <span className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[11.5px] font-semibold ${facts.length ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>{facts.length ? '프로필에 있음' : '준비 필요'}</span>
                <span className="min-w-0 flex-1">{material.text}
                  {facts.map((fact) => <span key={fact.text} className="mt-0.5 block text-[12.5px] text-[var(--product-muted)]">↳ {fact.kind}: {fact.text}</span>)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

function Checklist({ title, rows, empty }: { title: string; rows: Array<{ text: string; quote: string }>; empty: string }) {
  return (
    <div className="min-w-0">
      <h4 className="text-[14px] font-bold">{title}</h4>
      {rows.length === 0 ? <p className="mt-2 text-[13px] text-[var(--product-muted)]">{empty}</p> : (
        <ul className="mt-2 grid gap-2">
          {rows.map((row) => (
            <li key={row.text} className="flex items-start gap-2 text-[13.5px] leading-[1.6]">
              <input type="checkbox" className="mt-1.5 shrink-0" aria-label={`${row.text} 준비함`} />
              <span className="min-w-0" title={`공고: ${row.quote}`}>{row.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
