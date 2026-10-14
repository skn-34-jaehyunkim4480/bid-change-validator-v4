'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Check, X } from 'lucide-react';
import { ApiError } from '@/lib/api';
import { getMembership, membershipModal, membershipUsage, subscribeWithCode, won, type Membership, type MembershipKind, type MembershipPlan, type PlanCode } from '@/lib/membership';
import './membership-modal.css';

/*
  멤버십 창(2026-10-13). 무료 한도를 넘으면 뜬다.
    1) 요금제 안내 → 2) '가입' 을 누르면 같은 창 안이 결제 정보 입력으로 바뀐다 → 3) 적용 완료
  결제는 붙어 있지 않다. 카드 입력 칸은 모양만 있고 어디로도 보내지 않으며, 시연에서는 아래의 멤버십 코드로 가입한다.
*/

type ChatLimits = Pick<MembershipPlan, 'copilot_questions' | 'general_questions' | 'copilot_total'>;

// 참가자격 확인은 한 달에 몇 건으로 센다. Copilot 질문은 요금제에 따라 공고마다·일반 도우미 따로 세거나(무료), 둘을 합쳐 한 달로 센다(베이직).
const noticeLimit = (value: number | null) => (value == null ? '참가자격 확인 제한 없음' : `참가자격 확인 월 ${value}건`);
function copilotLimit(plan: ChatLimits | null | undefined) {
  if (!plan) return 'AI Copilot 질문';
  if (plan.copilot_total != null) return `AI Copilot 질문 월 ${plan.copilot_total}회(공고 대화와 일반 도우미 합산)`;
  if (plan.copilot_questions == null && plan.general_questions == null) return 'AI Copilot 질문 제한 없음';
  return `공고마다 AI Copilot 질문 ${plan.copilot_questions ?? 0}회, 일반 도우미 월 ${plan.general_questions ?? 0}회`;
}

function titleOf(kind: MembershipKind, plan: ChatLimits | undefined) {
  if (kind === 'NOTICE_CHECK') return '이번 달에 확인할 수 있는 공고를 모두 썼습니다';
  if (plan?.copilot_total != null) return '이번 달 AI Copilot 질문을 모두 썼습니다';
  return kind === 'GENERAL_QUESTION' ? '이번 달 일반 도우미 질문을 모두 썼습니다' : '이 공고에서 물을 수 있는 AI Copilot 질문을 모두 썼습니다';
}

function leadText(kind: MembershipKind, membership: Membership, plan: ChatLimits | undefined) {
  // 이미 유료 요금제를 쓰는 계정에는 가입을 다시 권하지 않는다.
  const more = membership.plan === 'FREE' ? '멤버십에 가입하면 더 쓸 수 있습니다.' : '다음 달에 다시 쓸 수 있습니다.';
  if (kind === 'NOTICE_CHECK') {
    return `${membership.plan_name} 요금제는 한 달에 공고 ${membership.limits.notice_checks ?? 0}건까지 참가자격을 확인할 수 있습니다(이번 달 ${membership.used.notice_checks ?? 0}건 사용). ${more}`;
  }
  if (plan?.copilot_total != null) return `${membership.plan_name} 요금제는 공고 대화와 일반 도우미를 합쳐 한 달에 AI Copilot 질문을 ${plan.copilot_total}회까지 쓸 수 있습니다. ${more}`;
  if (kind === 'GENERAL_QUESTION') return `${membership.plan_name} 요금제는 일반 도우미에 한 달 ${plan?.general_questions ?? 0}회까지 물을 수 있습니다. ${more}`;
  return `${membership.plan_name} 요금제는 공고 하나에서 AI Copilot 질문을 ${plan?.copilot_questions ?? 0}회까지 쓸 수 있습니다. ${more}`;
}

export function MembershipModal() {
  const kind = useSyncExternalStore(membershipModal.subscribe, membershipModal.get, () => null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (kind && !element.open) element.showModal();
    if (!kind && element.open) element.close();
  }, [kind]);
  return (
    <dialog ref={dialog} className="membership-modal" aria-labelledby="membership-title" onCancel={() => membershipModal.close()} onClose={() => membershipModal.close()}>
      {kind && <MembershipSteps key={kind} kind={kind} />}
    </dialog>
  );
}

function MembershipSteps({ kind }: { kind: MembershipKind }) {
  const [membership, setMembership] = useState<Membership | null>(null);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<Exclude<PlanCode, 'FREE'> | null>(null);
  const [done, setDone] = useState<Membership | null>(null);
  useEffect(() => {
    let alive = true;
    getMembership().then((value) => { if (alive) setMembership(value); })
      .catch((cause) => { if (alive) setLoadError(cause instanceof Error ? cause.message : '요금제 정보를 불러오지 못했습니다.'); });
    return () => { alive = false; };
  }, []);
  const close = () => membershipModal.close();

  if (done) {
    const plan = done.plans.find((item) => item.code === done.plan);
    return (
      <div className="membership-body">
        <span className="membership-done-mark" aria-hidden><Check size={22} /></span>
        <h2 id="membership-title">{done.plan_name} 요금제가 적용되었습니다</h2>
        <p className="membership-lead">
          {noticeLimit(plan?.notice_checks ?? null)}, {copilotLimit(plan)}까지 쓸 수 있습니다.
          하던 작업을 다시 시도해 주세요.
        </p>
        <div className="membership-actions"><button type="button" className="membership-primary" onClick={close}>확인</button></div>
      </div>
    );
  }

  const paidPlans = (membership?.plans ?? []).filter((plan): plan is MembershipPlan & { code: Exclude<PlanCode, 'FREE'> } => plan.code !== 'FREE');
  const chosen = paidPlans.find((plan) => plan.code === selected) ?? null;
  const currentPlan = membership?.plans.find((plan) => plan.code === membership.plan);
  return (
    <div className="membership-body">
      <button type="button" className="membership-close" aria-label="닫기" onClick={close}><X size={18} /></button>
      {chosen && membership ? (
        <PaymentStep plan={chosen} codeEnabled={membership.demo_code_enabled} onBack={() => setSelected(null)} onDone={(next) => { setDone(next); membershipUsage.refresh(); }} />
      ) : (
        <>
          <h2 id="membership-title">{titleOf(kind, currentPlan)}</h2>
          <p className="membership-lead">
            {membership ? leadText(kind, membership, currentPlan) : loadError || '요금제 정보를 불러오고 있습니다…'}
          </p>
          <ul className="membership-plans">
            {paidPlans.map((plan) => (
              <li key={plan.code} className="membership-plan">
                <div>
                  <strong>{plan.name}</strong>
                  <span className="membership-price">월 {won(plan.monthly_price)}</span>
                </div>
                <ul>
                  <li>{noticeLimit(plan.notice_checks)}</li>
                  <li>{copilotLimit(plan)}</li>
                </ul>
                <button type="button" className="membership-primary" onClick={() => setSelected(plan.code)}>가입</button>
              </li>
            ))}
          </ul>
          <div className="membership-actions"><button type="button" className="membership-quiet" onClick={close}>나중에</button></div>
        </>
      )}
    </div>
  );
}

function PaymentStep({ plan, codeEnabled, onBack, onDone }: {
  plan: MembershipPlan & { code: Exclude<PlanCode, 'FREE'> };
  codeEnabled: boolean;
  onBack: () => void;
  onDone: (membership: Membership) => void;
}) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const applyCode = async () => {
    if (!code.trim() || busy) return;
    setBusy(true);
    setMessage('');
    try {
      onDone(await subscribeWithCode(plan.code, code.trim()));
    } catch (cause) {
      setMessage(cause instanceof ApiError ? cause.message : '멤버십 코드를 확인하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <h2 id="membership-title">결제 정보 입력</h2>
      <p className="membership-lead"><strong>{plan.name}</strong> 요금제 · 월 {won(plan.monthly_price)} · 매달 자동 결제</p>
      {/* 카드 입력은 모양만 있다. name 을 주지 않고 제출도 막아 어디로도 보내지 않는다. */}
      <form className="membership-form" onSubmit={(event) => { event.preventDefault(); setMessage('이 환경에서는 카드 결제를 지원하지 않습니다. 아래에 멤버십 코드를 입력해 주세요.'); }}>
        <label>카드 번호<input type="text" inputMode="numeric" autoComplete="off" placeholder="0000 0000 0000 0000" maxLength={19} /></label>
        <div className="membership-form-row">
          <label>유효기간<input type="text" inputMode="numeric" autoComplete="off" placeholder="MM / YY" maxLength={7} /></label>
          <label>CVC<input type="text" inputMode="numeric" autoComplete="off" placeholder="000" maxLength={4} /></label>
          <label>비밀번호 앞 2자리<input type="password" inputMode="numeric" autoComplete="off" placeholder="••" maxLength={2} /></label>
        </div>
        <label>카드 소유자<input type="text" autoComplete="off" placeholder="이름" maxLength={40} /></label>
        <p className="membership-note">시연 환경입니다. 실제 결제는 이루어지지 않고, 입력한 카드 정보는 전송되거나 저장되지 않습니다.</p>
        <button type="submit" className="membership-primary" disabled={busy}>{won(plan.monthly_price)} 결제하기</button>
      </form>
      <div className="membership-code">
        <label htmlFor="membership-code-input">멤버십 코드</label>
        <div className="membership-code-row">
          <input id="membership-code-input" type="text" inputMode="numeric" autoComplete="off" value={code} placeholder={codeEnabled ? '코드 입력' : '이 환경에서는 쓸 수 없습니다'}
            disabled={!codeEnabled || busy} maxLength={32}
            onChange={(event) => setCode(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void applyCode(); } }} />
          <button type="button" className="membership-secondary" disabled={!codeEnabled || busy || !code.trim()} onClick={() => void applyCode()}>{busy ? '확인 중…' : '코드 적용'}</button>
        </div>
        <p className="membership-note">멤버십 코드는 베이직 요금제에 적용됩니다.</p>
      </div>
      {message && <p role="alert" className="membership-alert">{message}</p>}
      <div className="membership-actions"><button type="button" className="membership-quiet" onClick={onBack} disabled={busy}>요금제 다시 고르기</button></div>
    </>
  );
}
