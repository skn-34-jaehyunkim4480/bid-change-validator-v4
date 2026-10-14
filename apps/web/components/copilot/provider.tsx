'use client';

import { useRouter } from 'next/navigation';
import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ConversationStore } from '@/lib/copilot-conversation';
import { ActionController } from '@/lib/copilot-actions';
import { saveCopilotNavigationHandoff, takeCopilotNavigationHandoff } from '@/lib/copilot-navigation-handoff';

// 대화 기록은 계정마다 따로 남긴다(2026-10-13). 예전에는 열쇠 하나를 브라우저의 모든 계정이 같이 써서,
// 다른 계정으로 로그인해도 앞 계정의 일반 도우미·공고 대화가 그대로 보였다.
const LEGACY_SHARED_KEY = 'bidcheck.copilot.conversations.v1';
const conversationsKey = (userId: string) => `bidcheck.copilot.conversations.v2:${userId}`;

const Context = createContext<{ store: ConversationStore; controller: ActionController } | null>(null);
/** userId 는 로그인한 계정의 id 다. 로그인 없이 쓰는 개발 환경과 로그인 화면에서는 'anonymous' 를 준다. */
export function CopilotProvider({ userId, children }: { userId: string; children: ReactNode }) {
  const [value] = useState(() => {
    const store = new ConversationStore();
    return { store, controller: new ActionController(undefined, undefined, (id, response) => store.publish(id, response)) };
  });
  // 공고별 대화 기록을 이 브라우저에 남긴다. 새로고침해도 전용 화면의 대화 목록이 유지된다.
  useEffect(() => {
    const { store } = value;
    // 계정이 바뀌면 앞 계정의 대화를 화면에서 비우고, 이 계정의 기록만 읽는다.
    store.reset();
    try { window.localStorage.removeItem(LEGACY_SHARED_KEY); } catch { /* 저장소 차단 */ }
    const key = conversationsKey(userId);
    try { store.hydrate(JSON.parse(window.localStorage.getItem(key) ?? 'null')); } catch { /* 깨진 값·저장소 차단 — 빈 목록으로 시작 */ }
    let timer: number | undefined;
    const write = () => {
      timer = undefined;
      try { window.localStorage.setItem(key, JSON.stringify(store.serialize())); } catch { /* 용량 초과·저장소 차단 — 이번 방문에만 유지 */ }
    };
    const save = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(write, 300);
    };
    const unsubscribe = store.subscribe(save);
    return () => {
      unsubscribe();
      // 계정이 바뀌기 직전에 남기려던 것이 있으면 이 계정의 열쇠에 마저 쓴다.
      if (timer !== undefined) { window.clearTimeout(timer); write(); }
    };
  }, [value, userId]);
  useEffect(() => {
    const handoff = takeCopilotNavigationHandoff();
    if (!handoff) return;
    // 넘겨받은 대화가 이 브라우저에 남은 기록보다 짧으면 오래된 것이다 — 같은 화면 안에서 옮겨 오면 넘김 기록이
    // 쓰이지 않은 채 남고, 그 뒤 새로고침하면 그것이 더 긴 최신 대화를 덮어썼다.
    if (handoff.conversation && handoff.conversation.turns.length >= value.store.get(handoff.caseId).turns.length) {
      value.store.restore(handoff.caseId, handoff.conversation);
    }
    if (handoff.action) value.controller.restore(handoff.caseId, handoff.action);
    if (handoff.reopenPanel) {
      // The destination page renders a fresh CopilotPanel after document navigation.
      // Reuse its public launcher rather than duplicating dialog state here.
      window.requestAnimationFrame(() => {
        const launcher = document.querySelector<HTMLButtonElement>('.copilot-launch[aria-expanded="false"]');
        launcher?.click();
      });
    }
  }, [value]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
function useStores() {
  const stores = useContext(Context);
  if (!stores) throw new Error('CopilotProvider required');
  return stores;
}
export function useCopilot(caseId: string) {
  const { store } = useStores();
  const state = useSyncExternalStore(store.subscribe, () => store.get(caseId), () => store.get(caseId));
  return { store, state };
}
export function useActions(caseId: string) {
  const { controller } = useStores();
  const action = useSyncExternalStore(controller.subscribe, () => controller.get(caseId), () => controller.get(caseId));
  return { controller, action };
}
export function useCopilotNavigation(caseId: string) {
  const router = useRouter();
  const { store, controller } = useStores();
  const stage = (destination: string, reopenPanel = false) => saveCopilotNavigationHandoff(
    destination,
    caseId,
    store.snapshot(caseId),
    controller.snapshot(caseId),
    reopenPanel,
  );
  return {
    stage,
    navigate: (destination: string, reopenPanel = true) => {
      stage(destination, reopenPanel);
      router.push(destination);
    },
  };
}
