'use client';

import { useState } from 'react';
import { Check, LoaderCircle, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { regionByCode } from '@/lib/company-regions';
import { lookupProcurementCompany, type ProcurementCompany } from '@/lib/qualification-api';

/*
  사업자등록번호로 조달청 나라장터의 등록 정보를 불러와 프로필에 반영한다(2026-10-13).
  조회는 보여 주기만 하고, 「프로필에 반영」을 눌러야 값이 들어간다. 무엇이 들어가는지는 누르기 전에 화면에 적는다.
  나라장터에 입찰참가자격을 등록한 업체만 나온다. 기업 구분·인력·실적·인증은 여기서 알 수 없어 직접 넣는다.
*/

const PRODUCTS_SHOWN = 8;

export function ProcurementLookup({ savedNumber, applyHint, applyLabel = '프로필에 반영', disabled = false, onApply }: {
  /** 회사에 이미 저장된 사업자등록번호. 있으면 그 번호로만 조회한다. */
  savedNumber?: string | null;
  /** 반영하면 어떻게 되는지 한 줄(예: 업종은 더하기만 한다). */
  applyHint: string;
  applyLabel?: string;
  disabled?: boolean;
  /** 반영을 마치면 사용자에게 보일 한 줄을 돌려준다. */
  onApply: (found: ProcurementCompany) => Promise<string> | string;
}) {
  const [number, setNumber] = useState(savedNumber ?? '');
  const [busy, setBusy] = useState<'lookup' | 'apply' | null>(null);
  const [found, setFound] = useState<ProcurementCompany | null>(null);
  const [message, setMessage] = useState<{ tone: 'ok' | 'warn'; text: string } | null>(null);
  const digits = number.replace(/\D/g, '');

  async function lookup() {
    if (digits.length !== 10 || busy) return;
    setBusy('lookup');
    setMessage(null);
    setFound(null);
    try {
      const result = await lookupProcurementCompany(digits);
      if (result.found) setFound(result);
      else setMessage({ tone: 'warn', text: '조달청 나라장터에 등록된 업체가 아닙니다. 번호를 확인하거나 아래 항목을 직접 입력해 주세요.' });
    } catch (cause) {
      setMessage({ tone: 'warn', text: cause instanceof Error ? cause.message : '조달청 조회에 실패했습니다.' });
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!found || busy) return;
    setBusy('apply');
    setMessage(null);
    try {
      setMessage({ tone: 'ok', text: await onApply(found) });
      setFound(null);
    } catch (cause) {
      setMessage({ tone: 'warn', text: cause instanceof Error ? cause.message : '프로필에 반영하지 못했습니다.' });
    } finally {
      setBusy(null);
    }
  }

  const region = found?.region_code ? regionByCode(found.region_code) : undefined;
  const registrable = found?.industries.filter((item) => item.registrable) ?? [];
  const unknown = found?.industries.filter((item) => !item.registrable) ?? [];
  return (
    <section id="procurement-lookup" className="rounded-[22px] border border-[var(--product-accent-deep)] bg-white p-6">
      <h2 className="text-[20px] font-extrabold tracking-[-0.03em] text-[var(--product-ink)]">사업자등록번호로 채우기</h2>
      <p className="mt-1 text-[13px] text-[var(--product-muted)]">조달청 나라장터에 등록된 업체 정보(회사명·소재지·업종)를 불러옵니다.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <label className="sr-only" htmlFor="procurement-number">사업자등록번호</label>
        <Input id="procurement-number" className="max-w-[240px] tabular-nums" inputMode="numeric" maxLength={12} placeholder="10자리 숫자"
          value={number} readOnly={Boolean(savedNumber)} disabled={disabled}
          onChange={(event) => setNumber(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void lookup(); } }} />
        <Button variant="outline" onClick={() => void lookup()} disabled={disabled || busy !== null || digits.length !== 10}>
          {busy === 'lookup' ? <LoaderCircle className="animate-spin" /> : <Search />}조달청에서 조회
        </Button>
      </div>
      {savedNumber && <p className="mt-2 text-[12px] text-[var(--product-muted)]">회사에 등록된 사업자등록번호로만 조회합니다.</p>}

      {found && (
        <div className="mt-5 rounded-[16px] bg-[var(--product-tint)] p-5" aria-label="조달청 조회 결과">
          <dl className="grid gap-x-6 gap-y-3 text-[14px] sm:grid-cols-[96px_minmax(0,1fr)]">
            <dt className="font-semibold text-[var(--product-muted)]">회사명</dt>
            <dd className="font-bold text-[var(--product-ink)]">{found.name ?? '—'}</dd>
            <dt className="font-semibold text-[var(--product-muted)]">소재지</dt>
            <dd>
              {region ? <strong className="text-[var(--product-ink)]">{region.name}</strong> : <span className="text-amber-800">시·도를 알 수 없어 반영하지 않습니다</span>}
              {found.address && <span className="ml-2 text-[var(--product-muted)]">{found.address}</span>}
            </dd>
            <dt className="font-semibold text-[var(--product-muted)]">등록 업종</dt>
            <dd className="flex flex-wrap gap-1.5">
              {registrable.map((item) => (
                <span key={item.code} className="rounded-full border border-[var(--product-line)] bg-white px-2.5 py-1 text-[13px]"><strong>{item.code}</strong> <span className="text-[var(--product-muted)]">{item.name}</span></span>
              ))}
              {unknown.map((item) => (
                <span key={item.code} className="rounded-full border border-dashed border-[var(--product-line)] px-2.5 py-1 text-[13px] text-[var(--product-muted)]" title="업종 코드 목록에 없어 반영하지 않습니다">{item.code} {item.name} · 반영 안 함</span>
              ))}
              {!found.industries.length && <span className="text-[var(--product-muted)]">등록된 업종이 없습니다</span>}
            </dd>
            {found.products.length > 0 && <>
              <dt className="font-semibold text-[var(--product-muted)]">공급 물품</dt>
              <dd className="text-[13px] text-[var(--product-muted)]">
                {found.products.slice(0, PRODUCTS_SHOWN).map((item) => `${item.name}(${item.code})`).join(', ')}
                {found.products.length > PRODUCTS_SHOWN && ` 외 ${found.products.length - PRODUCTS_SHOWN}건`}
                <span className="ml-1">· 참고용이며 프로필에는 넣지 않습니다</span>
              </dd>
            </>}
          </dl>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button onClick={() => void apply()} disabled={disabled || busy !== null}>
              {busy === 'apply' ? <LoaderCircle className="animate-spin" /> : <Check />}{applyLabel}
            </Button>
            <p className="text-[12px] leading-5 text-[var(--product-muted)]">{applyHint}</p>
          </div>
        </div>
      )}
      {message && (
        <p role={message.tone === 'warn' ? 'alert' : 'status'} className={`mt-4 rounded-xl px-3 py-2 text-[13px] leading-[1.7] ${message.tone === 'ok' ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>{message.text}</p>
      )}
    </section>
  );
}
