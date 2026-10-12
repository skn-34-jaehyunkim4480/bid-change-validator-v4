'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, RefObject } from 'react';
import { ChevronDown, Maximize2, Send, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CopilotNavigationLink } from './navigation-link';
import { CopilotMascot } from './mascot';
import { EnvelopeAnswer } from './envelope-answer';
import { useActions, useCopilot, useCopilotNavigation } from './provider';
import { isLocked } from '@/lib/copilot-actions';
import { GENERAL_CONVERSATION_ID } from '@/lib/copilot-conversation';
import { getCopilotStatusLabel, getSourceLocationLabel, splitAnswerBlocks } from '@/lib/copilot-view-model';
import { getCopilotJobs } from '@/lib/copilot-api';
import type { CopilotChatResponse, CopilotIntent, CopilotSource, GuidedJobCatalog } from '@/lib/copilot-api';
import './panel.css';

const pages = { '/qualification': 'QUALIFICATION', '/ask-back': 'ASK_BACK', '/evidence': 'EVIDENCE', '/changes': 'CHANGES' } as const;
/** 일반 도우미에 알려 줄 화면 이름. 공고를 연 화면이 아니면 패널은 일반 도우미로 뜬다. */
const SCREEN_NAMES: Array<[string, string]> = [
  ['/notices', '공고 찾기'], ['/qualification', '내 입찰 건'], ['/ask-back', '확인 필요'], ['/evidence', '근거 원문'], ['/evaluation', '평가 대응'],
  ['/changes', '변경 이력'], ['/company', '회사 프로필'], ['/recommendations', 'AI 추천'], ['/guide', '이용안내'], ['/admin', '운영 관리'], ['/copilot', 'AI Copilot'],
];
export const screenNameOf = (pathname: string) => SCREEN_NAMES.find(([prefix]) => pathname.startsWith(prefix))?.[1];
const noJudgmentCodes = ['CURRENT_JUDGMENT_REQUIRED', 'QUALIFICATION_JUDGMENT_NOT_FOUND', 'JUDGMENT_NOT_FOUND'];
const href = (page: string, caseId: string) => `${page}?caseId=${encodeURIComponent(caseId)}`;

/**
 * 스크롤 막대를 스크롤하는 동안에만 보이게 한다: 스크롤이 일어난 요소에 data-scrolling 을 달고 잠시 뒤에 뗀다.
 * 막대의 색은 panel.css 가 그 표시를 보고 정한다.
 */
export function useScrollbarWhileScrolling(root: RefObject<HTMLElement | null>, active: unknown = true) {
  useEffect(() => {
    const element = root.current;
    if (!element || !active) return;
    const timers = new Map<Element, number>();
    const onScroll = (event: Event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      target.dataset.scrolling = '';
      window.clearTimeout(timers.get(target));
      timers.set(target, window.setTimeout(() => { delete target.dataset.scrolling; timers.delete(target); }, 900));
    };
    element.addEventListener('scroll', onScroll, { capture: true, passive: true });
    return () => { element.removeEventListener('scroll', onScroll, { capture: true }); timers.forEach(timer => window.clearTimeout(timer)); };
  }, [root, active]);
}

export function CopilotPanel() {
  const pathname = usePathname();
  const caseId = useSearchParams().get('caseId') ?? '';
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const casePage = pages[pathname as keyof typeof pages];
  // 공고를 연 화면이면 그 공고의 대화, 아니면 일반 도우미다. 전용 화면(/copilot)에는 떠 있는 패널을 두지 않는다.
  const general = !(casePage && caseId);
  const hidden = pathname.startsWith('/copilot') || pathname === '/login';
  const page = hidden ? undefined : casePage ?? 'QUALIFICATION';
  const activeId = general ? GENERAL_CONVERSATION_ID : caseId;
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    const media = window.matchMedia('(min-width: 1024px)');
    const display = () => {
      element.close();
      if (open && page) { if (media.matches) element.show(); else element.showModal(); }
    };
    display();
    media.addEventListener('change', display);
    return () => { media.removeEventListener('change', display); element.close(); };
  }, [open, page]);
  useScrollbarWhileScrolling(dialog, page);
  // 창 크기는 React 상태가 아니라 dialog 의 CSS 변수로 둔다 — 끄는 동안 다시 그리지 않고, 저장된 크기는 이 브라우저에 남는다.
  useEffect(() => {
    const element = dialog.current;
    if (element) applyPanelSize(element, readPanelSize());
  }, [page]);
  const startResize = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const element = dialog.current;
    if (!element) return;
    event.preventDefault();
    const handle = event.currentTarget;
    const rect = element.getBoundingClientRect();
    const origin = { x: event.clientX, y: event.clientY, w: rect.width, h: rect.height };
    let size = clampPanelSize(origin.w, origin.h);
    // 창이 오른쪽 아래에 붙어 있으므로 왼쪽 위 모서리를 끌면 왼쪽·위로 커진다.
    const move = (pointer: PointerEvent) => {
      size = clampPanelSize(origin.w + origin.x - pointer.clientX, origin.h + origin.y - pointer.clientY);
      applyPanelSize(element, size);
    };
    const stop = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', stop);
      handle.removeEventListener('pointercancel', stop);
      savePanelSize(size);
    };
    handle.setPointerCapture(event.pointerId);
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', stop);
    handle.addEventListener('pointercancel', stop);
  };
  const resizeByKey = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const element = dialog.current;
    const step = { ArrowLeft: [24, 0], ArrowRight: [-24, 0], ArrowUp: [0, 24], ArrowDown: [0, -24] }[event.key];
    if (!element || !step) return;
    event.preventDefault();
    const rect = element.getBoundingClientRect();
    const size = clampPanelSize(rect.width + step[0], rect.height + step[1]);
    applyPanelSize(element, size);
    savePanelSize(size);
  };
  const resetSize = () => {
    if (dialog.current) applyPanelSize(dialog.current, null);
    savePanelSize(null);
  };
  // 열려 있는 동안 띄움 단추는 감춘다(panel.css). 닫은 뒤 다시 보이면 초점을 돌려준다.
  const close = () => { setOpen(false); window.requestAnimationFrame(() => toggle.current?.focus()); };
  if (!page) return null;
  return <>
    <button type="button" ref={toggle} className="copilot-launch" aria-expanded={open} aria-controls="copilot-panel" onClick={() => setOpen(value => !value)}>
      <CopilotMascot /> AI Copilot
    </button>
    <dialog ref={dialog} id="copilot-panel" className="copilot-panel" aria-labelledby="copilot-title" onCancel={close}>
      <button type="button" className="copilot-resize" aria-label="도우미 창 크기 조절" title="끌어서 크기 조절 · 두 번 누르면 원래 크기"
        onPointerDown={startResize} onKeyDown={resizeByKey} onDoubleClick={resetSize} />
      <PanelHeader caseId={activeId} close={close} />
      <PanelBody key={activeId} caseId={activeId} page={page} screen={screenNameOf(pathname)} />
    </dialog>
  </>;
}

type PanelSize = { w: number; h: number };
const PANEL_SIZE_KEY = 'bidcheck.copilot.panel-size';
const PANEL_MIN: PanelSize = { w: 340, h: 420 };

/** 화면 밖으로 나가지 않게 한다. 오른쪽·아래 24px 에 붙어 있으므로 그만큼의 여백을 남긴다. */
function clampPanelSize(w: number, h: number): PanelSize {
  return {
    w: Math.round(Math.max(PANEL_MIN.w, Math.min(w, window.innerWidth - 48))),
    h: Math.round(Math.max(PANEL_MIN.h, Math.min(h, window.innerHeight - 48))),
  };
}

function applyPanelSize(element: HTMLElement, size: PanelSize | null) {
  if (size) {
    element.style.setProperty('--copilot-w', `${size.w}px`);
    element.style.setProperty('--copilot-h', `${size.h}px`);
  } else {
    element.style.removeProperty('--copilot-w');
    element.style.removeProperty('--copilot-h');
  }
}

function readPanelSize(): PanelSize | null {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(PANEL_SIZE_KEY) ?? 'null');
    if (saved && typeof saved === 'object' && 'w' in saved && 'h' in saved && typeof saved.w === 'number' && typeof saved.h === 'number') {
      return clampPanelSize(saved.w, saved.h);
    }
  } catch { /* 저장소 차단·깨진 값 — 기본 크기 */ }
  return null;
}

function savePanelSize(size: PanelSize | null) {
  try {
    if (size) window.localStorage.setItem(PANEL_SIZE_KEY, JSON.stringify(size));
    else window.localStorage.removeItem(PANEL_SIZE_KEY);
  } catch { /* 저장소 차단 — 이번 방문에만 유지 */ }
}

function PanelHeader({ caseId, close }: { caseId: string; close: () => void }) {
  const { store, state } = useCopilot(caseId);
  const last = [...state.turns].reverse().find(turn => turn.response?.product_state)?.response?.product_state;
  const summary = last && 'overall_status' in last ? last : null;
  const version = last && ('version_number' in last.provenance ? last.provenance.version_number : last.provenance.current.version_number);
  return <header className="copilot-header">
    <CopilotMascot /><h2 id="copilot-title">AI Copilot</h2>{caseId === GENERAL_CONVERSATION_ID && <span className="copilot-mode">일반 도우미</span>}
    <div className="copilot-header-badges" aria-label="최근 조회한 판정 기준">
      {version != null && <span className="copilot-badge">조회 v{version}</span>}
      {summary && !state.error && <span className={`copilot-badge copilot-status-${summary.overall_status}`}>{getCopilotStatusLabel(summary.overall_status)}</span>}
    </div>
    {caseId && state.turns.length > 0 && <button type="button" className="copilot-new-conversation"
      disabled={state.busy} onClick={() => store.newConversation(caseId)}>새 대화</button>}
    {caseId && <CopilotNavigationLink caseId={caseId} className="copilot-expand" href={href('/copilot', caseId)} aria-label="큰 화면에서 보기" title="큰 화면에서 보기"><Maximize2 size={16} /></CopilotNavigationLink>}
    <button type="button" className="copilot-close" aria-label="도우미 닫기" onClick={close}><X size={18} /></button>
  </header>;
}

// v2: 안내 문구를 바꾸면서 열쇠를 새로 했다. 예전 체크를 이어받으면 새 안내를 한 번도 보지 못한다.
const consentKey = (kind: 'semantic' | 'document') => `bidcheck.copilot.notice.v2.${kind}`;
const consentListeners = new Set<() => void>();
// 저장소를 못 쓰는 브라우저에서도 이번 방문 동안은 고른 값이 유지되게 한다.
const consentMemory = new Map<string, boolean>();

function readConsent(kind: 'semantic' | 'document') {
  const key = consentKey(kind);
  if (consentMemory.has(key)) return consentMemory.get(key)!;
  try { return window.localStorage.getItem(key) === 'true'; } catch { return false; }
}

function subscribeConsent(listener: () => void) {
  consentListeners.add(listener);
  window.addEventListener('storage', listener);
  return () => { consentListeners.delete(listener); window.removeEventListener('storage', listener); };
}

/** 동의 체크박스 값. 처음에는 꺼져 있고, 사용자가 바꾼 값만 이 브라우저에 남긴다. */
function useRememberedConsent(kind: 'semantic' | 'document') {
  const value = useSyncExternalStore(subscribeConsent, () => readConsent(kind), () => false);
  const update = (next: boolean) => {
    consentMemory.set(consentKey(kind), next);
    try { window.localStorage.setItem(consentKey(kind), String(next)); } catch { /* 저장소 차단 — 이번 방문에만 유지 */ }
    consentListeners.forEach(listener => listener());
  };
  return [value, update] as const;
}

export type CopilotSourcePage = typeof pages[keyof typeof pages];

/** 대화 본문(안내·추천 질문·대화·입력창). 떠 있는 패널과 전용 화면(/copilot)이 함께 쓴다. */
export function PanelBody({ caseId, page, screen }: { caseId: string; page: CopilotSourcePage; screen?: string }) {
  const general = caseId === GENERAL_CONVERSATION_ID;
  const { store, state } = useCopilot(caseId);
  const [question, setQuestion] = useState('');
  // AI 처리 동의는 사용자가 직접 켠다. 한 번 고른 값은 이 브라우저에 기억해, 패널을 열 때마다 다시 켜지 않아도 된다.
  const [semanticProcessing, setSemanticProcessing] = useRememberedConsent('semantic');
  // 안내를 확인하면 공고문도 함께 읽어 답한다. 공고문은 공개 문서라 따로 묻지 않는다(2026-10-12 사용자 결정).
  const documentProcessing = semanticProcessing;
  const [jobsOpen, setJobsOpen] = useState({ page, open: true });
  const [catalogState, setCatalogState] = useState<{ caseId: string; catalog: GuidedJobCatalog | null; error: string }>({ caseId: '', catalog: null, error: '' });
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [state.turns, state.busy]);
  useEffect(() => {
    if (!caseId || general) return;   // 추천 질문은 공고별 대화에만 있다
    const controller = new AbortController();
    void getCopilotJobs(caseId, controller.signal)
      .then(catalog => setCatalogState({ caseId, catalog, error: '' }))
      .catch(error => { if (!controller.signal.aborted) setCatalogState({ caseId, catalog: null, error: error instanceof Error ? error.message : '질문 목록을 불러오지 못했습니다.' }); });
    return () => controller.abort();
  }, [caseId, general]);
  const catalog = catalogState.caseId === caseId ? catalogState.catalog : null;
  const catalogError = catalogState.caseId === caseId ? catalogState.error : '';
  // SPA navigation keeps the panel mounted; each destination starts with its
  // guided questions visible, as it did after a document navigation.
  const jobsExpanded = jobsOpen.page === page ? jobsOpen.open : true;
  const ask = (text: string, intent?: CopilotIntent, guided?: { jobId: string; questionId: string }, free = false) => {
    if (!caseId || state.busy || !text.trim()) return;
    setJobsOpen({ page, open: false });
    if (general) { void store.askGeneral(text.trim(), screen, semanticProcessing); return; }
    void store.ask(caseId, text.trim(), intent, page, semanticProcessing, free ? documentProcessing : false, guided, free);
  };
  // 추천 질문의 두 묶음은 답하는 길이 다르다(2026-10-12).
  //   변경 공고 대응 — 안내형 경로 그대로. 변경 카드·확인 항목·답변 입력 버튼을 그 경로가 만든다. 공고문은 싣지 않는다.
  //   입찰 참여 준비 — 공고문을 읽어야 답할 수 있는 질문이라 입력창 질문과 같은 자유 대화로 보낸다. 안내형 경로는
  //                    공고문을 실으면 입력 한도를 넘겨 "공고문 근거가 너무 많아 답변을 생성하지 못했습니다" 로 끝났다.
  const readsDocuments = (jobId: string) => jobId === 'bid_preparation';
  const askRecommended = (job: { job_id: string; label: string }, item: { question_id: string; label: string }) => {
    if (readsDocuments(job.job_id)) ask(`${job.label}: ${item.label}`, undefined, undefined, true);
    else ask(item.label, undefined, { jobId: job.job_id, questionId: item.question_id });
  };
  const noJudgment = noJudgmentCodes.includes(state.errorCode);
  const empty = !state.turns.length;
  return <>
    <div className={`copilot-content${empty ? ' copilot-content-empty' : ''}`}>
      {empty && <div className="copilot-empty" data-state="EMPTY">
        <CopilotMascot size={64} />
        <h3>{general ? '무엇이든 물어보세요' : caseId ? '이 공고에 대해 물어보세요' : '검토할 공고를 먼저 선택해 주세요'}</h3>
        <p>{general
          ? '비드체크 쓰는 법과 입찰 절차·용어에 답해 드려요. 특정 공고의 판정이나 서류는 그 공고를 연 화면에서 물어봐 주세요.'
          : '저장된 판정 결과와 공고문을 근거로 답해 드려요. 아래 입력창에 자유롭게 질문하거나 추천 질문을 고를 수 있어요.'}</p>
      </div>}
      {/* 사용 전 안내는 처음 한 번만 보인다. 확인하면 이 브라우저에서 다시 묻지 않는다. */}
      {caseId && !semanticProcessing && <div className="copilot-processing-options" aria-label="사용 전 안내">
        <p className="copilot-consent-notice">이 챗봇을 사용하면 회사 정보가 외부 API로 전달될 수 있습니다.</p>
        <label className="copilot-consent-check" htmlFor="copilot-semantic-processing">
          <input id="copilot-semantic-processing" type="checkbox" checked={semanticProcessing} disabled={state.busy}
            onChange={event => setSemanticProcessing(event.target.checked)} />
          <span>이해하였습니다.</span>
        </label>
      </div>}
      {caseId && catalog && <section className="copilot-jobs" aria-label="검증된 업무 질문">
        <button type="button" className="copilot-jobs-toggle" aria-expanded={jobsExpanded} onClick={() => setJobsOpen({ page, open: !jobsExpanded })}>
          <span><ChevronDown size={16} aria-hidden="true" />추천 질문 6개</span>
          <span>{jobsExpanded ? '접기' : '보기'}</span>
        </button>
        {jobsExpanded && <div className="copilot-jobs-list">{catalog.jobs.map(job => {
          // 묶음 안의 질문이 모두 같은 이유로 막혀 있으면 이유를 질문마다 되풀이하지 않고 묶음 아래에 한 번만 적는다.
          const reasons = job.questions.map(item => item.unavailable_reason ?? '');
          const sharedReason = reasons.length > 1 && reasons[0] && reasons.every(reason => reason === reasons[0]) ? reasons[0] : null;
          return <section className={job.job_id === 'changed_notice' ? 'copilot-job copilot-job-change' : 'copilot-job'} key={job.job_id}>
            <h4>{job.label}</h4>
            <ol>{job.questions.map(item => <li key={item.question_id}>
              <Button type="button" variant="ghost" className="copilot-quiet"
                disabled={state.busy || item.availability === 'BLOCKED' || (readsDocuments(job.job_id) && !semanticProcessing)}
                title={item.unavailable_reason ?? item.answer_scope}
                onClick={() => { store.focus(caseId, null); askRecommended(job, item); }}>
                {item.order}. {item.label}
              </Button>
              {item.unavailable_reason && !sharedReason && <small>{item.unavailable_reason}</small>}
            </li>)}</ol>
            {sharedReason && <small>{sharedReason}</small>}
          </section>;
        })}</div>}
      </section>}
      {caseId && !general && !catalog && !catalogError && <p className="copilot-limitation">검증된 질문을 확인하고 있어요…</p>}
      {catalogError && <p role="alert" className="copilot-error">{catalogError}</p>}
      {state.focus && <button type="button" className="copilot-focus" onClick={() => store.focus(caseId, null)}>선택한 요건 해제 · 전체 보기</button>}
      <div role="log" aria-label="공고 도우미 대화" aria-live="polite">
        {state.turns.map(turn => {
          const guided = turn.response?.envelope?.guided;
          const job = guided && catalog?.jobs.find(item => item.job_id === guided.job_id);
          const current = guided && job?.questions.find(item => item.question_id === guided.question_id);
          const followUps = current ? job?.questions.filter(item => item.order > current.order && item.availability === 'AVAILABLE').slice(0, 2) ?? [] : [];
          return <div key={turn.id} className="copilot-turn">
            <p className="copilot-question">{turn.question}</p>
            {turn.response && <Answer response={turn.response} caseId={caseId} onSelect={key => {
              store.focus(caseId, key, turn.response?.reply_context);
              ask('그 조건 근거 보여줘', 'REQUIREMENT_EVIDENCE');
            }} />}
            {followUps.length > 0 && <div className="copilot-followups" aria-label="관련 후속 질문">
              <strong>이어서 확인하기</strong>
              {followUps.map(item => <Button type="button" variant="outline" className="copilot-quiet" key={item.question_id}
                disabled={state.busy} onClick={() => askRecommended(job!, item)}>
                {item.label}
              </Button>)}
            </div>}
          </div>;
        })}
      </div>
      {state.busy && <div className="copilot-answer copilot-loading" data-state="LOADING">
        {/* 무엇을 하고 있는지는 방금 보낸 질문의 종류로 정한다. 일반 도우미와 안내형 질문은 공고문을 읽지 않는다. */}
        <output>{general ? '답변을 준비하고 있어요…' : state.turns.at(-1)?.free && documentProcessing ? '공고문 근거를 확인하고 있어요…' : semanticProcessing ? '판정 결과를 이해하기 쉽게 정리하고 있어요…' : '현재 검토 결과를 확인하고 있어요…'}</output>
        <div className="copilot-skeleton" aria-hidden="true"><span /><span /><span /></div>
      </div>}
      {state.error && <div role="alert" className={noJudgment ? 'copilot-notice' : 'copilot-error'} data-state={noJudgment ? 'NO_JUDGMENT' : 'ERROR'}>
        <strong>{noJudgment ? '저장된 판정이 아직 없습니다' : '요청을 완료하지 못했습니다'}</strong>
        <p>{noJudgment ? '참가자격 화면에서 검토 상태를 확인해 주세요. 화면 이동만으로 분석이나 저장을 시작하지 않습니다.' : state.error}</p>
        {caseId && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={href('/qualification', caseId)}>참가자격 화면에서 확인</CopilotNavigationLink>}
        <Button type="button" variant="outline" className="copilot-quiet" disabled={state.busy} onClick={() => void store.retry(caseId, semanticProcessing, documentProcessing)}>실패한 질문 다시 조회</Button>
      </div>}
      <div ref={end} />
    </div>
    <form className="copilot-input" onSubmit={event => {
      event.preventDefault();
      if (!question.trim() || state.busy || !caseId) return;
      ask(question, undefined, undefined, true);
      setQuestion('');
    }}>
      <div className="copilot-input-row">
        <label className="sr-only" htmlFor="copilot-question">공고와 참가자격 질문</label>
        <textarea id="copilot-question" rows={1} maxLength={2000} value={question}
          onChange={event => setQuestion(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder={caseId && !semanticProcessing ? '안내를 확인하면 질문할 수 있어요' : general ? '무엇이든 물어보세요' : '이 공고에 대해 물어보세요'}
          disabled={!caseId || state.busy || !semanticProcessing} />
        <button type="submit" aria-label="질문 보내기" disabled={!caseId || state.busy || !question.trim()}><Send size={18} /></button>
      </div>
      <small>Enter 전송 · Shift+Enter 줄바꿈</small>
    </form>
  </>;
}

function SourceChip({ source, caseId, analysisRunId }: { source: CopilotSource; caseId: string; analysisRunId?: string }) {
  if (source.source_origin !== 'PRODUCT_EVIDENCE') return <span className="copilot-evidence-chip">[{source.ref}] {getSourceLocationLabel(source)}</span>;
  return <CopilotNavigationLink caseId={caseId} className="copilot-evidence-chip" href={`${href('/evidence', caseId)}&evidence=${encodeURIComponent(source.evidence.evidence_key)}${analysisRunId ? '&analysisRunId=' + encodeURIComponent(analysisRunId) : ''}`}>
    [{source.ref}] {getSourceLocationLabel(source)} · 원문
  </CopilotNavigationLink>;
}

/** 자유 대화 답변: 본문 문단을 먼저 그리고, '요약' 줄 아래의 목록은 구분선으로 나눈 요약 상자에 그린다. */
function FreeAnswer({ answer }: { answer: string }) {
  const blocks = splitAnswerBlocks(answer);
  const summaryAt = blocks.findIndex(block => block.kind === 'text' && /^요약\s*[:：]?$/.test(block.text));
  const renderBlock = (block: (typeof blocks)[number], index: number) => block.kind === 'list'
    ? <ul key={index}>{block.items.map((item, itemIndex) => {
      // "제출 방법: 나라장터에 직접 입력" 처럼 짧은 머리말이 있으면 굵게 해 훑어보기 쉽게 한다.
      const label = /^([^:：]{2,16})[:：]\s+(.+)$/.exec(item);
      return <li key={itemIndex}>{label ? <><strong>{label[1]}</strong>{label[2]}</> : item}</li>;
    })}</ul>
    : <p key={index}>{block.text}</p>;
  if (summaryAt < 0) return <div className="copilot-free-answer">{blocks.map(renderBlock)}</div>;
  return <div className="copilot-free-answer">
    {blocks.slice(0, summaryAt).map(renderBlock)}
    <section className="copilot-answer-summary" aria-label="요약">
      <h5>요약</h5>
      {blocks.slice(summaryAt + 1).map(renderBlock)}
    </section>
  </div>;
}

function Answer({ response, caseId, onSelect }: { response: CopilotChatResponse; caseId: string; onSelect: (key: string) => void }) {
  const p = response.presentation;
  const { controller, action } = useActions(caseId);
  const { navigate } = useCopilotNavigation(caseId);
  const state = response.product_state;
  const changed = Boolean(state && 'changes' in state);
  const analysisRunId = state && 'analysis_run_id' in state.provenance ? state.provenance.analysis_run_id : undefined;
  const insufficient = response.sources.length === 0 && (
    response.intent === 'REQUIREMENT_EVIDENCE' || (response.intent === 'DOCUMENT_QA' && response.external_processing_used)
  );
  const kind = insufficient ? 'INSUFFICIENT_EVIDENCE' : changed ? 'CHANGED_NOTICE' : state && 'questions' in state ? 'NEEDS_CHECK' : 'ANSWER';
  const reasons = p?.reasons.filter(reason => reason.requirement_key) ?? [];
  const outside = p?.reasons.filter(reason => !reason.requirement_key) ?? [];
  const renderReason = (reason: NonNullable<typeof p>['reasons'][number], i: number) => <div key={`${reason.requirement_key ?? 'scope'}-${i}`} className="copilot-reason">
    {reason.requirement_key && <span className="copilot-reason-label">판정 요건 {i + 1}</span>}
    <p>{reason.text}</p>
    <div className="copilot-evidence-chips">{reason.evidence_refs.map(ref => {
      const source = response.sources.find(item => item.ref === ref);
      return source ? <SourceChip key={ref} source={source} caseId={caseId} analysisRunId={analysisRunId} /> : null;
    })}</div>
    {reason.requirement_key && <button type="button" className="copilot-detail-link" onClick={() => onSelect(reason.requirement_key!)}>이 요건 근거 보기</button>}
  </div>;
  return <article className={`copilot-answer${insufficient ? ' copilot-no-evidence' : ''}`} data-state={kind}>
    {response.envelope ? <EnvelopeAnswer envelope={response.envelope} /> : p ? <>
      <p className="copilot-conclusion">{p.conclusion}</p>
      {reasons.map(renderReason)}
      {outside.length > 0 && <div className="copilot-scope"><strong>{response.intent === 'DOCUMENT_QA' ? '사용한 공고문 근거' : '직접 확인할 공고 항목'}</strong>{outside.map(renderReason)}
        {response.intent !== 'DOCUMENT_QA' && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={`${href('/qualification', caseId)}#analysis-scope`}>참가자격 화면에서 함께 확인</CopilotNavigationLink>}
      </div>}
      {p.limitations.map((text, i) => <p className="copilot-limitation" key={i}>{text}</p>)}
      {p.next_action && <p>{p.next_action.label}</p>}
    </> : <FreeAnswer answer={response.answer} />}
    {response.sources.length > 0 && <details><summary>원문 근거 {response.sources.length}건</summary>
      {response.sources.map(source => <div className="copilot-source" key={source.ref}>
        <SourceChip source={source} caseId={caseId} analysisRunId={analysisRunId} />
        <blockquote>{source.source_origin === 'PRODUCT_EVIDENCE' ? source.evidence.quote : source.quote}</blockquote>
      </div>)}
    </details>}
    {(insufficient || response.intent === 'DOCUMENT_QA') && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={href('/evidence', caseId)}>근거 원문 직접 확인</CopilotNavigationLink>}
    {changed && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={href('/changes', caseId)}>변경사항 상세 보기 · 06</CopilotNavigationLink>}
    {state && 'profile_snapshot' in state && <details><summary>판정 당시 회사정보 · 현재 프로필과 다를 수 있음</summary><pre>{JSON.stringify(state.profile_snapshot, null, 2)}</pre></details>}
    {state && 'questions' in state && state.questions.filter(q => q.askable).map(q =>
      <Button type="button" variant="outline" className="copilot-quiet" key={q.requirement_key} disabled={isLocked(action)} onClick={async () => {
        await controller.beginAnswer(caseId, q.requirement_key,
          response.reply_context?.last_read_receipt?.kind === 'product' ? response.reply_context.last_read_receipt.provenance.judgment_run_id : undefined);
        navigate(href('/ask-back', caseId));
      }}>{q.question} · 답변 입력</Button>)}
    {response.actions.map((proposal, i) => <Button type="button" variant="outline" className="copilot-quiet" key={i} disabled={isLocked(action)} onClick={() => {
      controller.adopt(caseId, proposal);
      navigate(href(proposal.action_type === 'REVALIDATE' ? '/changes' : '/ask-back', caseId));
    }}>서버 제안 검토 · 아직 실행 안 함</Button>)}
  </article>;
}
