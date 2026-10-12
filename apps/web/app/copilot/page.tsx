'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { PanelLeft } from 'lucide-react';
import { CopilotMascot } from '@/components/copilot/mascot';
import { PanelBody } from '@/components/copilot/panel';
import { useCopilot } from '@/components/copilot/provider';
import { NavigationLink } from '@/components/navigation-link';
import { buttonVariants } from '@/components/ui/button';
import { listPreflightCases, type PreflightCase } from '@/lib/api';
import { GENERAL_CONVERSATION_ID } from '@/lib/copilot-conversation';

/*
  AI Copilot 전용 화면(2026-10-12). 참가자격 화면의 떠 있는 패널과 같은 대화를 큰 화면에서 본다.
  왼쪽은 공고(검토 건)별 대화 목록이다 — 대화는 검토 건마다 하나씩 이어지고, 이 브라우저에 남는다.
*/
export default function CopilotPage() {
  const router = useRouter();
  const requested = useSearchParams().get('caseId') ?? '';
  const [cases, setCases] = useState<PreflightCase[] | null>(null);
  const [error, setError] = useState('');
  const [listOpen, setListOpen] = useState(true);
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

  // 고른 것이 없으면 일반 도우미를 연다. 공고별 대화는 왼쪽 목록에서 고른다.
  const activeId = requested || GENERAL_CONVERSATION_ID;
  const general = activeId === GENERAL_CONVERSATION_ID;
  const active = (cases ?? []).find(item => item.id === activeId) ?? null;
  const generalTurns = store.get(GENERAL_CONVERSATION_ID).turns;
  const open = (id: string) => router.push(`/copilot?caseId=${encodeURIComponent(id)}`);

  const renderItem = (item: PreflightCase) => {
    const turns = store.get(item.id).turns;
    const last = turns.at(-1);
    return (
      <li key={item.id}>
        <button type="button" className="copilot-page-item" aria-current={item.id === activeId ? 'page' : undefined}
          onClick={() => open(item.id)}>
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
        <div className="copilot-page" data-list={listOpen ? 'open' : 'closed'}>
          <aside className="copilot-page-list" aria-label="대화 목록">
            <h2>일반 도우미</h2>
            <div className="copilot-page-general">
              <button type="button" className="copilot-page-item" aria-current={general ? 'page' : undefined} onClick={() => open(GENERAL_CONVERSATION_ID)}>
                <strong>사이트 쓰는 법 · 입찰 일반</strong>
                <span>{generalTurns.at(-1)?.question ?? '어느 화면에서나 물어볼 수 있어요'}</span>
              </button>
            </div>
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
            {general || active ? (
              <>
                <header className="copilot-header">
                  <button type="button" className="copilot-list-toggle" aria-label={listOpen ? '대화 목록 접기' : '대화 목록 펴기'} aria-expanded={listOpen}
                    title={listOpen ? '대화 목록 접기' : '대화 목록 펴기'} onClick={() => setListOpen(value => !value)}><PanelLeft size={18} /></button>
                  <CopilotMascot />
                  <h2 className="min-w-0 truncate">{active ? (active.notice_title || active.title) : '일반 도우미'}</h2>
                  <ChatActions caseId={activeId} general={general} />
                </header>
                <PanelBody key={activeId} caseId={activeId} page="QUALIFICATION" screen="AI Copilot" />
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

function ChatActions({ caseId, general }: { caseId: string; general: boolean }) {
  const { store, state } = useCopilot(caseId);
  return (
    <div className="ml-auto flex shrink-0 items-center gap-2">
      {state.turns.length > 0 && <button type="button" className="copilot-new-conversation" disabled={state.busy} onClick={() => store.newConversation(caseId)}>새 대화</button>}
      {!general && <NavigationLink href={`/qualification?caseId=${encodeURIComponent(caseId)}`} className="text-[13px] font-semibold text-[var(--product-accent)] underline-offset-2 hover:underline">참가자격 화면</NavigationLink>}
    </div>
  );
}
