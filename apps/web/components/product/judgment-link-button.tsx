'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { ArrowRight, LoaderCircle } from 'lucide-react';

import { judgmentHref } from '@/lib/open-judgment';

/*
  공고 한 건을 판정 화면(참가자격 검토)으로 여는 단추(2026-10-13).
  AI Copilot 이 찾아 준 공고와 AI 추천 화면의 공고가 같이 쓴다. 검토 건이 없으면 누를 때 만든다.
  autostart 를 주면 판정 화면이 열리면서 검토를 바로 시작한다.
*/
export function JudgmentLinkButton({ noticeId, bidNoticeNo, autostart = false, label, className = '' }: {
  noticeId: string;
  bidNoticeNo?: string;
  autostart?: boolean;
  label?: string;
  className?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState('');
  async function open() {
    if (busy) return;
    setBusy(true);
    setFailure('');
    try {
      router.push(await judgmentHref(noticeId, { bidNoticeNo, autostart }));
    } catch (cause) {
      setFailure(cause instanceof Error ? cause.message : '판정 화면을 열지 못했습니다.');
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button type="button" className={className} onClick={() => void open()} disabled={busy}>
        {label ?? (autostart ? '판정하기' : '판정 화면으로')}
        {busy ? <LoaderCircle size={14} className="animate-spin" aria-hidden="true" /> : <ArrowRight size={14} aria-hidden="true" />}
      </button>
      {failure && <span role="alert" className="text-[12px] text-rose-700">{failure}</span>}
    </span>
  );
}
