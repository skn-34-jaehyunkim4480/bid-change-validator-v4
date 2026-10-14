'use client';

import { useEffect, useState, useSyncExternalStore, type SyntheticEvent } from 'react';
import { Building2, CheckCircle2, LoaderCircle, ShieldCheck, UserPlus } from 'lucide-react';

import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api';
import { getCurrentUser, signup } from '@/lib/auth';
import { replaceWith } from '@/lib/navigation';
import { signupProblems } from '@/lib/signup-rules';

/*
  회원가입(2026-10-14). 아이디·비밀번호만 받는다. 만든 계정은 회사 없는 무료 요금제 사용자이고,
  가입하면 바로 로그인되어 회사 프로필 화면에서 회사를 직접 만든다.
*/
const subscribeHydration = () => () => {};

export default function SignupPage() {
  const hydrated = useSyncExternalStore(subscribeHydration, () => true, () => false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void getCurrentUser().then((current) => { if (current) replaceWith('/company'); }).catch(() => undefined);
  }, []);

  const problems = signupProblems(username, password, confirm);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    setError('');
    if (problems.length) return;
    setLoading(true);
    try {
      await signup(username, password);
      replaceWith('/company');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : '가입 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--product-tint)] px-5 py-10 sm:grid sm:place-items-center">
      <div className="mx-auto grid w-full max-w-5xl overflow-hidden rounded-3xl border border-[var(--product-line)] bg-white shadow-[0_24px_80px_rgba(20,33,61,0.12)] lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden min-h-[640px] flex-col justify-between bg-[#14213d] p-12 text-white lg:flex">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-[var(--product-accent)]"><Building2 className="size-5" /></span>
            <span className="text-lg font-bold">비드체크</span>
          </div>
          <div className="max-w-md">
            <p className="mb-4 text-sm font-semibold text-blue-200">입찰 참가자격 사전검토</p>
            <h1 className="text-4xl font-bold leading-[1.35] tracking-[-0.04em]">가입하고<br />우리 회사 기준으로 검토하세요</h1>
            <ul className="mt-6 space-y-3 text-base leading-7 text-slate-300">
              {['가입하면 바로 회사 프로필을 만듭니다.', '사업자등록번호로 조달청 정보를 불러올 수 있습니다.', '무료 요금제로 시작합니다.'].map((line) => (
                <li key={line} className="flex items-start gap-2.5"><CheckCircle2 className="mt-1 size-4 shrink-0 text-blue-300" />{line}</li>
              ))}
            </ul>
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-300">
            <ShieldCheck className="size-5 text-blue-300" />
            비밀번호는 암호화해 저장하고, 회사별 검토 내역은 서로 보이지 않습니다.
          </div>
        </section>

        <section className="flex min-h-[640px] items-center px-6 py-12 sm:px-12">
          <Card className="w-full border-0 bg-transparent shadow-none ring-0">
            <CardHeader className="px-0">
              <div className="mb-6 grid size-12 place-items-center rounded-2xl bg-blue-50 text-[var(--product-accent)] lg:hidden"><Building2 className="size-6" /></div>
              <CardTitle className="text-2xl font-bold tracking-[-0.03em]">회원가입</CardTitle>
              <CardDescription className="mt-2 text-base leading-6">아이디와 비밀번호만 정하면 바로 시작할 수 있습니다.</CardDescription>
            </CardHeader>
            <CardContent className="px-0 pt-4">
              <form className="space-y-5" method="post" onSubmit={submit} noValidate>
                <div className="space-y-2">
                  <Label htmlFor="signup-username">아이디</Label>
                  <Input id="signup-username" name="username" autoComplete="username" className="h-11 px-3 text-base"
                    value={username} onChange={(event) => setUsername(event.target.value)} maxLength={30} required />
                  <p className="text-[12.5px] text-[var(--product-muted)]">영문 소문자·숫자·. _ - 로 4~30자</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signup-password">비밀번호</Label>
                  <Input id="signup-password" name="password" type="password" autoComplete="new-password" className="h-11 px-3 text-base"
                    value={password} onChange={(event) => setPassword(event.target.value)} required />
                  <p className="text-[12.5px] text-[var(--product-muted)]">8자 이상, 아이디와 다르게</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signup-confirm">비밀번호 확인</Label>
                  <Input id="signup-confirm" name="confirm" type="password" autoComplete="new-password" className="h-11 px-3 text-base"
                    value={confirm} onChange={(event) => setConfirm(event.target.value)} required />
                </div>
                {touched && problems.length > 0 && (
                  <ul role="alert" className="space-y-1 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
                    {problems.map((problem) => <li key={problem}>{problem}</li>)}
                  </ul>
                )}
                {error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700">{error}</p>}
                <Button type="submit" size="lg" className="mt-2 h-11 w-full text-base" disabled={loading || !hydrated}>
                  {loading ? <LoaderCircle className="animate-spin" /> : <UserPlus />}
                  {loading ? '가입하는 중' : '가입하고 시작하기'}
                </Button>
                <p className="text-center text-sm text-[var(--product-muted)]">
                  이미 계정이 있나요? <NavigationLink href="/login" className="font-semibold text-[var(--product-accent-deep)] underline">로그인</NavigationLink>
                </p>
              </form>
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}
