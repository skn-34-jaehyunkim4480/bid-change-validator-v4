'use client';

import { useRouter } from 'next/navigation';
import { createContext, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { ConversationStore } from '@/lib/copilot-conversation';
import { ActionController } from '@/lib/copilot-actions';
import { saveCopilotNavigationHandoff, takeCopilotNavigationHandoff } from '@/lib/copilot-navigation-handoff';

const CONVERSATIONS_KEY = 'bidcheck.copilot.conversations.v1';

const Context = createContext<{ store: ConversationStore; controller: ActionController } | null>(null);
export function CopilotProvider({ children }: { children: ReactNode }) {
  const [value] = useState(() => {
    const store = new ConversationStore();
    return { store, controller: new ActionController(undefined, undefined, (id, response) => store.publish(id, response)) };
  });
  // 공고별 대화 기록을 이 브라우저에 남긴다. 새로고침해도 전용 화면의 대화 목록이 유지된다.
  useEffect(() => {
    const { store } = value;
    try { store.hydrate(JSON.parse(window.localStorage.getItem(CONVERSATIONS_KEY) ?? 'null')); } catch { /* 깨진 값·저장소 차단 — 빈 목록으로 시작 */ }
    let timer: number | undefined;
    const save = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        try { window.localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(store.serialize())); } catch { /* 용량 초과·저장소 차단 — 이번 방문에만 유지 */ }
      }, 300);
    };
    const unsubscribe = store.subscribe(save);
    return () => { unsubscribe(); window.clearTimeout(timer); };
  }, [value]);
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
