'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { CopilotMascot } from '@/components/copilot/mascot';
import { PanelBody } from '@/components/copilot/panel';
import { useCopilot } from '@/components/copilot/provider';
import { NavigationLink } from '@/components/navigation-link';
import { buttonVariants } from '@/components/ui/button';
import { listPreflightCases, type PreflightCase } from '@/lib/api';

/*
  AI Copilot 전용 화면(2026-10-12). 참가자격 화면의 떠 있는 패널과 같은 대화를 큰 화면에서 본다.
  왼쪽은 공고(검토 건)별 대화 목록이다 — 대화는 검토 건마다 하나씩 이어지고, 이 브라우저에 남는다.
*/
export default function CopilotPage() {
  const router = useRouter();
  const requested = useSearchParams().get('caseId') ?? '';
  const [cases, setCases] = useState<PreflightCase[] | null>(null);
  const [error, setError] = useState('');
  const { store } = useCopilot(requested);
  // 어느 검토 건에 대화가 있는지. 저장소가 바뀔 때마다 다시 읽는다.
  const talkedKey = useSyncExternalStore(store.subscribe, () => store.caseIds().join(','), () => '');

  useEffect(() => {
    let alive = true;
    listPreflightCases()
      .then(result => { if (alive) setCases(result.items); })
      .catch(cause => { if (alive) setError(cause instanceof Error ? cause.message : '검토 건 목록을 불러오지 못했습니다.'); });
    return () => { alive = false; };
  }, []);

  const groups = useMemo(() => {
    const talked = new Set(talkedKey ? talkedKey.split(',') : []);
    const items = cases ?? [];
    return { talked: items.filter(item => talked.has(item.id)), fresh: items.filter(item => !talked.has(item.id)) };
  }, [cases, talkedKey]);

  // 고른 것이 없으면 대화가 있는 첫 건, 없으면 첫 검토 건을 연다.
  const activeId = requested || groups.talked[0]?.id || groups.fresh[0]?.id || '';
  useEffect(() => {
    if (!requested && activeId) router.replace(`/copilot?caseId=${encodeURIComponent(activeId)}`);
  }, [requested, activeId, router]);
  const active = (cases ?? []).find(item => item.id === activeId) ?? null;

  const renderItem = (item: PreflightCase) => {
    const turns = store.get(item.id).turns;
    const last = turns.at(-1);
    return (
      <li key={item.id}>
        <button type="button" className="copilot-page-item" aria-current={item.id === activeId ? 'page' : undefined}
          onClick={() => router.push(`/copilot?caseId=${encodeURIComponent(item.id)}`)}>
          <strong>{item.notice_title || item.title}</strong>
          <span>{last ? `${last.question}` : `${item.bid_notice_no} · 대화 없음`}</span>
        </button>
      </li>
    );
  };

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="copilot-page-shell">
        {error && <p role="alert" className="mb-4 rounded-[14px] border border-rose-200 bg-rose-50 px-4 py-3 text-[15px] text-rose-700">{error}</p>}
        <div className="copilot-page">
          <aside className="copilot-page-list" aria-label="공고별 대화">
            <h2>공고별 대화</h2>
            {cases === null && !error && <p className="px-[18px] text-[13px] text-[var(--product-muted)]">불러오는 중…</p>}
            {cases?.length === 0 && <p className="px-[18px] text-[13px] leading-5 text-[var(--product-muted)]">검토 중인 공고가 없습니다. 공고 찾기에서 검토를 시작하면 여기에 나옵니다.</p>}
            <ul>
              {groups.talked.length > 0 && <li className="copilot-page-group" aria-hidden>대화한 공고</li>}
              {groups.talked.map(renderItem)}
              {groups.fresh.length > 0 && <li className="copilot-page-group" aria-hidden>{groups.talked.length > 0 ? '아직 대화하지 않은 공고' : '검토 중인 공고'}</li>}
              {groups.fresh.map(renderItem)}
            </ul>
          </aside>
          <section className="copilot-panel copilot-page-chat" aria-label="AI Copilot 대화">
            {active ? (
              <>
                <header className="copilot-header">
                  <CopilotMascot />
                  <h2 className="min-w-0 truncate">{active.notice_title || active.title}</h2>
                  <ChatActions caseId={active.id} />
                </header>
                <PanelBody key={active.id} caseId={active.id} page="QUALIFICATION" />
              </>
            ) : (
              <div className="copilot-page-empty">
                <CopilotMascot size={64} />
                <p>{cases?.length === 0 ? '대화할 공고가 아직 없습니다.' : '왼쪽에서 공고를 고르면 대화가 열립니다.'}</p>
                <NavigationLink href="/notices" className={buttonVariants({ variant: 'outline' })}>공고 찾기</NavigationLink>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function ChatActions({ caseId }: { caseId: string }) {
  const { store, state } = useCopilot(caseId);
  return (
    <div className="ml-auto flex shrink-0 items-center gap-2">
      {state.turns.length > 0 && <button type="button" className="copilot-new-conversation" disabled={state.busy} onClick={() => store.newConversation(caseId)}>새 대화</button>}
      <NavigationLink href={`/qualification?caseId=${encodeURIComponent(caseId)}`} className="text-[13px] font-semibold text-[var(--product-accent)] underline-offset-2 hover:underline">참가자격 화면</NavigationLink>
    </div>
  );
}
