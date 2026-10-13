'use client';

import { useState } from 'react';
import { Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { CompanyProfile } from '@/lib/qualification-api';
import type { CertificationPayload, PerformancePayload } from '@/lib/profile-records-api';

/*
  수행 실적과 인증·등록(2026-10-13: 한 번에 저장).
  여기서는 서버에 쓰지 않는다. 추가·삭제·증빙 표시는 모두 초안(RecordsDraft)에 담기고,
  회사 프로필 화면의 「변경 사항 저장」 한 번으로 업종·기본 정보와 함께 저장된다(app/company/page.tsx).
*/

export type RecordsDraft = {
  addPerformances: PerformancePayload[];
  addCertifications: CertificationPayload[];
  removePerformanceIds: string[];
  removeCertificationIds: string[];
  /** 증빙 표시를 바꾼 항목. 열쇠는 `p:<id>` 또는 `c:<id>`. */
  verified: Record<string, boolean>;
};

export const EMPTY_RECORDS_DRAFT: RecordsDraft = {
  addPerformances: [], addCertifications: [], removePerformanceIds: [], removeCertificationIds: [], verified: {},
};

export function recordsDraftCount(draft: RecordsDraft) {
  return draft.addPerformances.length + draft.addCertifications.length + draft.removePerformanceIds.length
    + draft.removeCertificationIds.length + Object.keys(draft.verified).length;
}

type Props = {
  company: CompanyProfile;
  draft: RecordsDraft;
  onDraft: (next: RecordsDraft) => void;
  disabled?: boolean;
};

const PENDING = 'rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-bold text-amber-800';

export function ProfileRecordsManager({ company, draft, onDraft, disabled = false }: Props) {
  const [error, setError] = useState('');
  const [performance, setPerformance] = useState({ name: '', client_name: '', amount: '', completed_at: '', fields: '' });
  const [certification, setCertification] = useState({ name: '', certification_code: '', certificate_number: '', issuer_name: '', issued_at: '', expires_at: '' });

  function addPerformance() {
    if (!performance.name.trim() || !performance.amount || !performance.completed_at) {
      setError('수행실적명, 금액, 완료일은 필수입니다.');
      return;
    }
    setError('');
    onDraft({ ...draft, addPerformances: [...draft.addPerformances, {
      name: performance.name.trim(),
      client_name: performance.client_name.trim() || undefined,
      amount: Number(performance.amount),
      completed_at: performance.completed_at,
      fields: performance.fields.split(',').map((item) => item.trim()).filter(Boolean),
      verified: false,
    }] });
    setPerformance({ name: '', client_name: '', amount: '', completed_at: '', fields: '' });
  }

  function addCertification() {
    if (!certification.name.trim()) {
      setError('인증·등록명은 필수입니다.');
      return;
    }
    if (certification.issued_at && certification.expires_at && certification.issued_at > certification.expires_at) {
      setError('만료일은 발급일보다 뒤여야 합니다.');
      return;
    }
    setError('');
    onDraft({ ...draft, addCertifications: [...draft.addCertifications, {
      name: certification.name.trim(),
      certification_code: certification.certification_code.trim() || undefined,
      certificate_number: certification.certificate_number.trim() || undefined,
      issuer_name: certification.issuer_name.trim() || undefined,
      issued_at: certification.issued_at || undefined,
      expires_at: certification.expires_at || undefined,
      verified: false,
    }] });
    setCertification({ name: '', certification_code: '', certificate_number: '', issuer_name: '', issued_at: '', expires_at: '' });
  }

  const toggleRemove = (key: 'removePerformanceIds' | 'removeCertificationIds', id: string) =>
    onDraft({ ...draft, [key]: draft[key].includes(id) ? draft[key].filter((item) => item !== id) : [...draft[key], id] });

  function toggleVerified(key: string, saved: boolean) {
    const next = { ...draft.verified };
    // 저장된 값으로 되돌아가면 바꾼 것이 없는 것이다.
    if (key in next) delete next[key];
    else next[key] = !saved;
    onDraft({ ...draft, verified: next });
  }

  const rowActions = (key: string, saved: boolean, removed: boolean, onRemove: () => void) => {
    const verified = draft.verified[key] ?? saved;
    return (
      <div className="flex gap-2">
        {!removed && <Button size="sm" variant="outline" className="rounded-full" disabled={disabled} onClick={() => toggleVerified(key, saved)}><Pencil /> {verified ? '증빙 보유' : '증빙 표시'}</Button>}
        <Button size="sm" variant="outline" className="rounded-full" disabled={disabled} onClick={onRemove}>{removed ? <><RotateCcw /> 삭제 취소</> : <><Trash2 /> 삭제</>}</Button>
      </div>
    );
  };

  return (
    <section className="mt-7 grid gap-5 xl:grid-cols-2">
      {error && <div className="xl:col-span-2 rounded-[14px] border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">{error}</div>}

      {/* 위 「비어 있는 항목」에서 바로 여기로 보낸다. id를 바꾸면 app/company/page.tsx의 앵커도 같이 고칠 것. */}
      <div id="profile-performance" className="scroll-mt-24 rounded-[20px] border border-[var(--product-line)] bg-white p-6">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="text-[19px] font-bold">수행 실적</h3><p className="mt-1 text-[12.5px] text-[var(--product-muted)]">건수·금액·경험 분야 판정에 사용합니다.</p></div>
          <span className="text-[12px] text-[var(--product-muted)]">{company.performances.length}건</span>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Input placeholder="실적명 *" value={performance.name} onChange={(e) => setPerformance({ ...performance, name: e.target.value })} />
          <Input placeholder="발주처" value={performance.client_name} onChange={(e) => setPerformance({ ...performance, client_name: e.target.value })} />
          <Input type="number" min="0" placeholder="계약금액(원) *" value={performance.amount} onChange={(e) => setPerformance({ ...performance, amount: e.target.value })} />
          <Input type="date" aria-label="완료일" value={performance.completed_at} onChange={(e) => setPerformance({ ...performance, completed_at: e.target.value })} />
          <Input className="sm:col-span-2" placeholder="경험 분야 (쉼표 구분)" value={performance.fields} onChange={(e) => setPerformance({ ...performance, fields: e.target.value })} />
        </div>
        <Button variant="outline" className="mt-3 rounded-full" onClick={addPerformance} disabled={disabled}><Plus /> 수행 실적 추가</Button>

        <div className="mt-5 divide-y divide-[var(--product-line-2)]">
          {draft.addPerformances.map((item, index) => (
            <div key={`new-${index}`} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><strong className="block truncate text-[14px]">{item.name} <span className={PENDING}>저장 전</span></strong><p className="mt-1 text-[12px] text-[var(--product-muted)]">{item.amount.toLocaleString()}원 · {item.completed_at}{item.fields?.length ? ` · ${item.fields.join(', ')}` : ''}</p></div>
              <Button size="sm" variant="outline" className="rounded-full" disabled={disabled} onClick={() => onDraft({ ...draft, addPerformances: draft.addPerformances.filter((_, at) => at !== index) })}><Trash2 /> 빼기</Button>
            </div>
          ))}
          {company.performances.map((item) => {
            const removed = draft.removePerformanceIds.includes(item.id);
            return (
              <div key={item.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
                <div className={`min-w-0 flex-1 ${removed ? 'opacity-50' : ''}`}><strong className={`block truncate text-[14px] ${removed ? 'line-through' : ''}`}>{item.name}{removed && <span className={`ml-2 ${PENDING}`}>삭제 예정</span>}{!removed && `p:${item.id}` in draft.verified && <span className={`ml-2 ${PENDING}`}>저장 전</span>}</strong><p className="mt-1 text-[12px] text-[var(--product-muted)]">{item.amount.toLocaleString()}원 · {item.completed_at}{item.fields.length ? ` · ${item.fields.join(', ')}` : ''}</p></div>
                {rowActions(`p:${item.id}`, item.verified, removed, () => toggleRemove('removePerformanceIds', item.id))}
              </div>
            );
          })}
          {!company.performances.length && !draft.addPerformances.length && <p className="py-5 text-center text-[13px] text-[var(--product-muted)]">등록된 수행 실적이 없습니다.</p>}
        </div>
      </div>

      <div id="profile-certification" className="scroll-mt-24 rounded-[20px] border border-[var(--product-line)] bg-white p-6">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="text-[19px] font-bold">인증 · 등록</h3><p className="mt-1 text-[12.5px] text-[var(--product-muted)]">등록·면허·인증 보유 사실 판정에 사용합니다.</p></div>
          <span className="text-[12px] text-[var(--product-muted)]">{company.certifications.length}건</span>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Input placeholder="인증·등록명 *" value={certification.name} onChange={(e) => setCertification({ ...certification, name: e.target.value })} />
          <Input placeholder="증명서 번호" value={certification.certificate_number} onChange={(e) => setCertification({ ...certification, certificate_number: e.target.value })} />
          {/* 공고가 번호로 요구하는 자격(직접생산확인의 세부품명번호 등)은 이름이 아니라 이 번호로 판정한다. */}
          <Input className="sm:col-span-2" inputMode="numeric" placeholder="품명번호·인증 코드 (공고가 번호로 요구할 때, 예: 8111189901)" aria-label="품명번호 또는 인증 코드" value={certification.certification_code} onChange={(e) => setCertification({ ...certification, certification_code: e.target.value })} />
          <Input placeholder="발급기관" value={certification.issuer_name} onChange={(e) => setCertification({ ...certification, issuer_name: e.target.value })} />
          <Input type="date" aria-label="발급일" value={certification.issued_at} onChange={(e) => setCertification({ ...certification, issued_at: e.target.value })} />
          <label className="sm:col-span-2 text-[12px] text-[var(--product-muted)]" htmlFor="certification-expires-at">만료일<Input id="certification-expires-at" className="mt-1" type="date" value={certification.expires_at} onChange={(e) => setCertification({ ...certification, expires_at: e.target.value })} /></label>
        </div>
        <Button variant="outline" className="mt-3 rounded-full" onClick={addCertification} disabled={disabled}><Plus /> 인증·등록 추가</Button>

        <div className="mt-5 divide-y divide-[var(--product-line-2)]">
          {draft.addCertifications.map((item, index) => (
            <div key={`new-${index}`} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1"><strong className="block truncate text-[14px]">{item.name} <span className={PENDING}>저장 전</span></strong><p className="mt-1 text-[12px] text-[var(--product-muted)]">{item.certification_code ? `번호 ${item.certification_code} · ` : ''}{item.issuer_name ?? '발급기관 미입력'}{item.expires_at ? ` · 만료 ${item.expires_at}` : ''}</p></div>
              <Button size="sm" variant="outline" className="rounded-full" disabled={disabled} onClick={() => onDraft({ ...draft, addCertifications: draft.addCertifications.filter((_, at) => at !== index) })}><Trash2 /> 빼기</Button>
            </div>
          ))}
          {company.certifications.map((item) => {
            const removed = draft.removeCertificationIds.includes(item.id);
            return (
              <div key={item.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
                <div className={`min-w-0 flex-1 ${removed ? 'opacity-50' : ''}`}><strong className={`block truncate text-[14px] ${removed ? 'line-through' : ''}`}>{item.name}{removed && <span className={`ml-2 ${PENDING}`}>삭제 예정</span>}{!removed && `c:${item.id}` in draft.verified && <span className={`ml-2 ${PENDING}`}>저장 전</span>}</strong><p className="mt-1 text-[12px] text-[var(--product-muted)]">{item.certification_code ? `번호 ${item.certification_code} · ` : ''}{item.issuer_name ?? '발급기관 미입력'}{item.expires_at ? ` · 만료 ${item.expires_at}` : ''}</p></div>
                {rowActions(`c:${item.id}`, item.verified, removed, () => toggleRemove('removeCertificationIds', item.id))}
              </div>
            );
          })}
          {!company.certifications.length && !draft.addCertifications.length && <p className="py-5 text-center text-[13px] text-[var(--product-muted)]">등록된 인증·등록 정보가 없습니다.</p>}
        </div>
      </div>
    </section>
  );
}
